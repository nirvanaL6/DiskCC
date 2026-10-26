"""清理执行器：安全校验 -> 备份清单 -> 回收站/永久删除 -> 命令执行 -> 审计日志。"""

from __future__ import annotations

import os
import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .config import Config
from .models import CleanRecord, CleanReport, ItemKind, Risk, ScanItem, human_size
from .utils import fs, win


class CleanTask:
    """清理任务的不可变快照（v1.2.0）。

    清理在后台线程执行，期间同一个 ScanItem 可能被 AI 识别改写（分类/风险/说明），
    也可能被用户重新勾选。直接持有原对象会出现"边删边被改"的竞态：
    例如刚通过安全校验的项目，执行时风险等级已被 AI 改成高危。
    这里把清理真正需要的字段定格下来。
    """

    __slots__ = ("path", "name", "kind", "size", "risk", "protected",
                 "command", "patterns", "extra", "category_label", "reason", "id")

    def __init__(self, item: ScanItem):
        # v1.3.0：带上原项 id，清理记录据此回连到界面上的那一行
        self.id = getattr(item, "id", "") or ""
        self.path = item.path
        self.name = item.name
        self.kind = item.kind
        self.size = item.size
        self.risk = item.risk
        self.protected = bool(item.protected)
        self.command = item.command
        self.patterns = list(item.patterns or [])
        self.extra = dict(item.extra) if isinstance(item.extra, dict) else {}
        self.category_label = item.category_label
        self.reason = item.reason


# 超过该体积的项目在删除前给出提示：大文件走回收站时可能明显卡住一段时间
LARGE_ITEM_BYTES = 1024 * 1024 * 1024


class Cleaner:
    def __init__(
        self,
        cfg: Config,
        log: Optional[Callable[[str], None]] = None,
        progress: Optional[Callable[[str, float], None]] = None,
        extra_roots: Optional[List[str]] = None,
    ):
        self.cfg = cfg
        self.log = log or (lambda m: None)
        self.progress = progress or (lambda m, p: None)
        self.cancel = False
        self.extra_roots = list(extra_roots or [])

    def stop(self) -> None:
        self.cancel = True

    # ---------------------------------------------------------------- 安全校验
    def allowed_roots(self) -> List[str]:
        return [r for r in self._system_roots() + self.extra_roots if r]

    def _system_roots(self) -> List[str]:
        drive = os.environ.get("SYSTEMDRIVE", "C:") + "\\"
        roots = [
            drive,
            os.environ.get("USERPROFILE", ""),
            os.environ.get("APPDATA", ""),
            os.environ.get("LOCALAPPDATA", ""),
            os.environ.get("PROGRAMDATA", ""),
            os.environ.get("PROGRAMFILES", ""),
            os.environ.get("PROGRAMFILES(X86)", ""),
            os.environ.get("TEMP", ""),
        ]
        return [r for r in roots if r]

    def check_item(self, item: "ScanItem | CleanTask") -> Tuple[bool, str]:
        """返回 (是否允许清理, 原因)。

        v1.3.0：同时接受原始 ScanItem 与清理快照 CleanTask——右键"立即删除此项"
        走的是 ScanItem，批量清理走的是快照，两条路径必须共用同一套校验。
        """
        if item.protected:
            return False, "受系统保护，禁止删除"
        if item.risk == Risk.DANGEROUS:
            return False, "危险项（已安装程序/系统文件），请通过卸载程序处理"
        if item.kind != ItemKind.COMMAND:
            if fs.is_forbidden(item.path):
                return False, "位于系统关键目录，禁止删除"
            if not fs.is_safe_target(item.path, self.allowed_roots()):
                return False, "路径不在允许清理的范围内"
            if not fs.exists(item.path):
                return False, "路径不存在"
            if self.cfg.get("use_recycle_bin") and item.risk.value >= 3:
                # 高风险项强制走回收站，允许事后还原
                pass
        return True, ""

    # ---------------------------------------------------------------- 备份清单
    def write_backup_list(self, items: List[CleanTask]) -> str:
        folder = os.path.join(fs.app_data_dir(), "clean_logs")
        os.makedirs(folder, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(folder, f"clean_{ts}.txt")
        lines = [
            f"# DiskCC 清理清单 {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"# 共 {len(items)} 项，合计 {human_size(sum(i.size for i in items))}",
            "# 说明：本文件仅记录清理目标，用于审计与回溯；使用回收站删除的文件可在回收站还原。",
            "",
        ]
        for i in items:
            lines.append(
                f"[{i.risk.label}]\t{i.category_label}\t{human_size(i.size)}\t{i.path}\t{i.reason}"
            )
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        self.log(f"[备份] 清理清单已写入：{path}")
        return path

    # ---------------------------------------------------------------- 执行
    def clean(self, items: List[ScanItem]) -> CleanReport:
        report = CleanReport()
        # v1.2.0：先快照，避免清理过程中原对象被并发修改
        selected: List[CleanTask] = [CleanTask(i) for i in items if i.checked]
        if self.cfg.get("create_backup_list", True):
            report.log_file = self.write_backup_list(selected)

        dry = bool(self.cfg.get("dry_run", False))
        if dry:
            self.log("[演练] 当前为演练模式，不会真正删除任何文件")

        n = max(1, len(selected))
        for idx, item in enumerate(selected):
            if self.cancel:
                self.log("[清理] 已取消")
                break
            self.progress(f"清理中：{item.name}", idx / n * 100)
            ok, why = self.check_item(item)
            if not ok:
                report.records.append(CleanRecord(item.path, item.kind.value, False, "skip", why,
                                                  item.size, item.id))
                report.failed += 1
                self.log(f"[跳过] {item.name}：{why}")
                continue

            if dry:
                report.records.append(CleanRecord(item.path, item.kind.value, True, "dry-run", "演练",
                                                  item.size, item.id))
                report.freed += item.size
                continue

            if (not dry and item.kind != ItemKind.COMMAND
                    and item.size >= LARGE_ITEM_BYTES):
                # 大文件走回收站可能明显卡一段时间：提前告知，避免被误认为"卡死"
                self.log(f"[大文件] {item.name}（{human_size(item.size)}）体积较大，"
                         "移入回收站可能耗时较久，界面仍可操作，请耐心等待…")

            try:
                if item.kind == ItemKind.COMMAND:
                    ok, msg = self._run_command(item)
                elif item.kind == ItemKind.FILES:
                    ok, msg = self._clean_pattern(item)
                elif item.kind == ItemKind.DIR:
                    ok, msg = self._clean_path(item.path, is_dir=True)
                else:
                    ok, msg = self._clean_path(item.path, is_dir=False)
            except Exception as e:  # pragma: no cover
                ok, msg = False, str(e)

            method = "command" if item.kind == ItemKind.COMMAND else (
                "recycle" if self.cfg.get("use_recycle_bin") else "delete")
            report.records.append(CleanRecord(item.path, item.kind.value, ok, method, msg,
                                              item.size, item.id))
            if ok:
                report.freed += item.size
                self.log(f"[完成] {item.name} · {human_size(item.size)}")
            else:
                report.failed += 1
                self.log(f"[失败] {item.name}：{msg}")

        report.finished_at = time.time()
        return report

    # ---------------------------------------------------------------- 各类清理
    def _run_command(self, item: ScanItem) -> Tuple[bool, str]:
        if not item.command:
            return False, "命令为空"
        if not win.is_admin():
            return False, "需要管理员权限，请以管理员身份重新运行本程序"
        self.log(f"[命令] 执行：{item.command}")
        rc, out = win.run_command(item.command, timeout=900)
        tail = out[-300:].replace("\n", " | ") if out else ""
        if rc == 0:
            return True, f"执行成功 {tail}"
        return False, f"返回码 {rc}：{tail}"

    def _delete_one(self, path: str, is_dir: bool) -> Tuple[bool, str]:
        """永久删除单个文件/目录（不走回收站）。"""
        if is_dir:
            return fs.remove_dir_tree(path)
        ok = fs.force_remove_file(path)
        return ok, "" if ok else "文件删除失败（可能被占用或需要管理员权限）"

    def _clean_path(self, path: str, is_dir: bool) -> Tuple[bool, str]:
        use_bin = bool(self.cfg.get("use_recycle_bin", True))
        if use_bin:
            ok, msg, code = win.delete_to_bin([path])
            if ok:
                return True, "已移入回收站（可还原）"
            # 路径类错误（0x7C / 0x79 / 0x81 / 0xB7）多为超过 MAX_PATH 的深层缓存
            # 目录：回收站 API 本身无解，改用支持长路径的直接删除，避免"能删却报失败"。
            if code in win.SHFILEOP_PATH_ERRORS:
                ok2, msg2 = self._delete_one(path, is_dir)
                if ok2:
                    return True, "已永久删除（路径过长，回收站不支持，已改为直接删除）"
                return False, f"移入回收站失败：{msg}；改为直接删除也失败：{msg2}"
            if code in win.SHFILEOP_ACCESS_ERRORS:
                return False, f"移入回收站失败：{msg}。请以管理员身份运行后重试"
            return False, f"移入回收站失败：{msg}"
        return self._delete_one(path, is_dir)

    def _flush_batch(self, batch: List[str], use_bin: bool) -> Tuple[bool, str]:
        """删除一批文件；回收站不接受的路径回退为永久删除。"""
        if not use_bin:
            return self._delete_batch(batch)
        ok, msg, code = win.delete_to_bin(batch)
        if ok:
            return True, ""
        # 只在"回收站 API 确实处理不了这种路径"时回退；权限类错误回退也删不掉，
        # 不如保留可还原的机会并把原因如实告知用户。
        if code in win.SHFILEOP_PATH_ERRORS:
            return self._delete_batch(batch)
        return False, msg

    def _clean_pattern(self, item: ScanItem) -> Tuple[bool, str]:
        """按模式删除一组文件。"""
        max_depth = int(item.extra.get("max_depth", 3)) if isinstance(item.extra, dict) else 3
        files = list(fs.iter_files(item.path, item.patterns or ["*"], max_depth=max_depth, max_results=20000))
        if not files:
            return True, "无匹配文件"
        use_bin = bool(self.cfg.get("use_recycle_bin", True))
        done = 0
        failed = 0
        detail = ""
        batch: List[str] = []
        # 每批 20 个：SHFileOperation 的 pFrom 缓冲区对路径数量与总长度敏感，
        # 一次塞太多会整批失败（表现为返回 124 / DE_INVALIDFILES）。
        for f in files:
            batch.append(f)
            if len(batch) >= 20:
                ok, detail = self._flush_batch(batch, use_bin)
                done += len(batch) if ok else 0
                failed += 0 if ok else len(batch)
                batch = []
        if batch:
            ok, detail = self._flush_batch(batch, use_bin)
            done += len(batch) if ok else 0
            failed += 0 if ok else len(batch)
        msg = f"共 {len(files)} 个文件，成功 {done}，失败 {failed}"
        if failed and detail:
            msg += f"（{detail}）"
        return failed == 0, msg

    @staticmethod
    def _delete_batch(paths: List[str]) -> Tuple[bool, str]:
        ok = True
        for p in paths:
            if not fs.force_remove_file(p):
                ok = False
        return ok, ""

    # ---------------------------------------------------------------- 辅助
    @staticmethod
    def open_uninstall(item: ScanItem) -> bool:
        """打开某个 Program Files 项的卸载程序（若注册表提供）。"""
        cmd = ""
        if isinstance(item.extra, dict):
            cmd = item.extra.get("uninstall_string", "")
        if not cmd:
            return False
        try:
            import subprocess

            subprocess.Popen(cmd, shell=True)
            return True
        except Exception:
            return False
