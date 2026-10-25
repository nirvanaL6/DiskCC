"""AppData 目录作用分析：梳理每个目录存放什么、哪些可以放心清理。

识别顺序：内置规则库 -> 通用缓存目录名 -> 已安装软件校验 -> AI 兜底。
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from ..knowledge import appdata_rules, software_map
from ..models import ItemKind, Risk, ScanItem
from ..utils import fs
from .base import ScannerBase

# 根级大文件扩展名（AppData 下常见的大体积可回收文件）
BIG_FILE_EXTS = (".log", ".dmp", ".tmp", ".bak", ".old", ".etl", ".mdmp", ".crash")


class AppDataScanner(ScannerBase):
    key = "appdata"
    title = "AppData 目录分析"

    def enabled(self) -> bool:
        return bool(self.ctx.cfg.get("scan_appdata", True))

    # ---------------------------------------------------------------- 工具
    def _roots(self) -> List[Tuple[str, str]]:
        out = []
        for tag, path in (("Local", self.ctx.localappdata),
                          ("Roaming", self.ctx.appdata),
                          ("LocalLow", self.ctx.locallow)):
            if fs.is_dir(path):
                out.append((tag, path))
        return out

    def _software_installed(self, name: str) -> bool:
        """判断某软件是否仍然安装着（注册表或 Program Files 中存在）。"""
        nm = software_map.normalize(name)
        if not nm:
            return False
        for info in self.ctx.installed.values():
            iname = software_map.normalize(info.get("name", ""))
            if iname and (nm in iname or iname in nm):
                return True
        for pf in self.ctx.program_files:
            pf_dirs, _unused = fs.scan_dir(pf)
            for sub in pf_dirs:
                if software_map.normalize(sub) == nm:
                    return True
        return False

    # ---------------------------------------------------------------- 已知路径
    def _known_paths(self) -> List[ScanItem]:
        items: List[ScanItem] = []
        base = {"Local": self.ctx.localappdata, "Roaming": self.ctx.appdata,
                "LocalLow": self.ctx.locallow}
        for tag, rel, desc in appdata_rules.KNOWN_BIG_CACHE_PATHS:
            root = base.get(tag)
            if not root:
                continue
            p = os.path.join(root, rel.replace("\\", os.sep))
            if not fs.is_dir(p):
                continue
            size, cnt = fs.dir_size(p, max_files=50000)
            it = ScanItem(
                path=p,
                category="appdata_cache",
                kind=ItemKind.DIR,
                size=size,
                file_count=cnt,
                risk=Risk.SAFE,
                reason=f"{desc}；删除后软件会自动重建，不影响个人数据",
                software=desc,
                source="rule",
            )
            added = self.ctx.add(it)
            if added:
                items.append(added)
        return items

    # ---------------------------------------------------------------- 递归分析
    def _walk(self, root: str, tag: str, rel_prefix: str, depth: int,
              buckets: Dict[str, object]) -> None:
        """遍历 root 下的目录，按规则分类填充 buckets。"""
        if depth > int(self.ctx.cfg.get("max_depth_appdata", 3)):
            return
        for name in sorted(fs.subdir_names(root)):   # v1.3.2：scandir 一次拿到类型
            if self.ctx.stopped():
                return
            p = os.path.join(root, name)
            if appdata_rules.is_reserved(name):
                continue
            rel = f"{rel_prefix}/{name}" if rel_prefix else name
            is_cache = appdata_rules.is_cache_dir(name)
            size, cnt = fs.dir_size(p, max_files=40000)

            if is_cache or size >= self.ctx.min_size:
                rule = appdata_rules.lookup_dir(name)
                if is_cache:
                    desc = appdata_rules.cache_dir_desc(name)
                    parent_sw = appdata_rules.lookup_dir(os.path.basename(root))
                    sw = parent_sw[0] if parent_sw else (rule[0] if rule else "")
                    buckets.setdefault("cache", []).append({
                        "path": p, "rel": f"{tag}/{rel}", "name": name, "size": size,
                        "count": cnt, "desc": desc, "software": sw,
                        "age": fs.days_since(fs.get_mtime(p)),
                    })
                    continue  # 缓存目录内部不再下潜
                if size >= self.ctx.min_size:
                    # v1.3.2：这两行原本各自 listdir 一遍再对每个名字 stat，
                    # 现共用同一次 scandir 的结果（原来 2 次遍历 + N 次 stat）。
                    _subdirs, _files = fs.scan_dir(p)
                    buckets.setdefault("unknown_or_data", []).append({
                        "path": p, "rel": f"{tag}/{rel}", "name": name, "size": size,
                        "count": cnt, "rule": rule, "age": fs.days_since(fs.get_mtime(p)),
                        "subdirs": _subdirs[:12],
                        "files": _files[:10],
                    })
            self._walk(p, tag, rel, depth + 1, buckets)

    # ---------------------------------------------------------------- 主流程
    def scan(self) -> List[ScanItem]:
        ctx = self.ctx
        ctx.log("[扫描] AppData 目录作用分析...")
        items: List[ScanItem] = list(self._known_paths())

        buckets: Dict[str, object] = {}
        for tag, root in self._roots():
            self._walk(root, tag, "", 1, buckets)

        cache_entries = buckets.get("cache", []) or []
        ctx.log(f"[扫描] 命中 {len(cache_entries)} 个通用缓存目录")

        # ---- 缓存目录：可直接标记为可放心清理 ----
        for e in cache_entries:
            idle = e["age"] > ctx.idle_days
            reason = f"{e['desc']}"
            if e["software"]:
                reason += f"（属于 {e['software']}）"
            reason += "；删除后由软件自动重建，不影响账号、配置与个人数据"
            if idle:
                reason += f"；已 {int(e['age'])} 天未更新"
            it = ScanItem(
                path=e["path"], name=e["name"], category="appdata_cache",
                kind=ItemKind.DIR, size=e["size"], file_count=e["count"],
                risk=Risk.SAFE, reason=reason, software=e["software"] or "",
                source="rule", mtime=fs.get_mtime(e["path"]),
                extra={"idle": idle, "rel": e["rel"]},
            )
            added = ctx.add(it)
            if added:
                items.append(added)

        # ---- 数据目录：规则库命中 -> 说明作用；未命中且够大 -> AI ----
        data_entries = buckets.get("unknown_or_data", []) or []
        need_ai: List[Dict] = []
        for e in data_entries:
            rule = e["rule"]
            if rule:
                sw, desc, whole_deletable = rule
                installed = self._software_installed(sw) or self._software_installed(e["name"])
                if whole_deletable:
                    it = ScanItem(
                        path=e["path"], name=e["name"], category="appdata_cache",
                        kind=ItemKind.DIR, size=e["size"], file_count=e["count"],
                        risk=Risk.SAFE,
                        reason=f"{sw} 的 {desc}；纯缓存数据，可放心清理",
                        software=sw, source="rule", mtime=fs.get_mtime(e["path"]),
                        extra={"rel": e["rel"]},
                    )
                elif not installed and e["age"] > ctx.idle_days:
                    it = ScanItem(
                        path=e["path"], name=e["name"], category="appdata_residue",
                        kind=ItemKind.DIR, size=e["size"], file_count=e["count"],
                        risk=Risk.MEDIUM,
                        reason=f"{sw} 的 {desc}；注册表中未发现安装记录，且已 {int(e['age'])} 天未更新，"
                               "疑似软件卸载后的残留数据（请确认后再删）",
                        software=sw, source="rule", mtime=fs.get_mtime(e["path"]),
                        extra={"rel": e["rel"], "installed": False},
                    )
                else:
                    it = ScanItem(
                        path=e["path"], name=e["name"], category="appdata_data",
                        kind=ItemKind.DIR, size=e["size"], file_count=e["count"],
                        risk=Risk.MEDIUM,
                        reason=f"{sw} 的 {desc}；软件仍在安装，删除可能丢失配置/登录状态/个人数据",
                        software=sw, source="rule", mtime=fs.get_mtime(e["path"]),
                        extra={"rel": e["rel"], "installed": True},
                    )
                added = ctx.add(it)
                if added:
                    items.append(added)
            else:
                need_ai.append({
                    "path": e["rel"], "folder": e["name"], "size": e["size"],
                    "file_count": e["count"], "subdirs": e["subdirs"], "files": e["files"],
                    "last_modified": fs.mtime_text(e["path"]),
                    "_abs": e["path"],
                })

        # ---- 收集 AI 候选（实际分析推迟到 manager 的独立“AI 分析”步骤） ----
        if need_ai:
            ctx.log(f"[规则库] {len(need_ai)} 个 AppData 目录未能识别"
                    + ("（将在后续的 AI 分析步骤中处理）" if ctx.ai.enabled else
                       "（未开启 AI 增强，保持规则库判断）"))
            for e in need_ai:
                it = ScanItem(
                    path=e["_abs"], name=e["folder"], category="appdata_data",
                    kind=ItemKind.DIR, size=e["size"], file_count=e["file_count"],
                    risk=Risk.MEDIUM,
                    reason="内置规则库未收录该目录，建议开启 AI 识别或手动确认",
                    source="rule", mtime=fs.get_mtime(e["_abs"]),
                    extra={"rel": e["path"]},
                )
                added = ctx.add(it)
                if added:
                    items.append(added)
                    if ctx.ai.enabled:
                        rel_path = e["path"].lower().replace("\\", "/")
                        ai_key = f"ad:{rel_path}"
                        it.extra["ai_key"] = ai_key
                        ctx.queue_ai_ad(e, ai_key)

        # ---- AppData 下的大体积可回收文件 ----
        items += self._big_files()
        return items

    def _big_files(self) -> List[ScanItem]:
        out: List[ScanItem] = []
        threshold = max(self.ctx.min_size * 5, 20 * 1024 * 1024)
        for tag, root in self._roots():
            for name in fs.file_names(root):   # v1.3.2：省去每个文件的 is_file stat
                p = os.path.join(root, name)
                if not name.lower().endswith(BIG_FILE_EXTS):
                    continue
                size = fs.get_size(p)
                if size < threshold:
                    continue
                it = ScanItem(
                    path=p, category="appdata_cache", kind=ItemKind.FILE, size=size,
                    risk=Risk.LOW,
                    reason=f"AppData 根目录下的{os.path.splitext(name)[1]}文件（日志/转储/临时），可删除",
                    source="rule", mtime=fs.get_mtime(p),
                )
                added = self.ctx.add(it)
                if added:
                    out.append(added)
        return out


def _apply_ai_ad(item: "ScanItem", ai: "AIAnalysis") -> None:
    """用 AI 结论覆盖 AppData 项的归属与风险判断（被 manager 与右键识别共用）。"""
    from ..models import Risk

    item.extra["ai_confidence"] = round(ai.confidence or 0, 2)
    item.extra["data_type"] = ai.data_type or ""
    item.software = ai.software or item.software
    item.reason = f"AI 判断：{ai.purpose}（{ai.data_type}）；{ai.reason}"
    if ai.deletable:
        item.category = "appdata_cache"
        item.risk = ai.risk if ai.risk is not None else Risk.MEDIUM
        item.checked = (ai.risk.value <= 1) if ai.risk is not None else False
    else:
        item.category = "appdata_data"
        item.risk = Risk.MEDIUM
        item.checked = False
    item.source = "ai"
