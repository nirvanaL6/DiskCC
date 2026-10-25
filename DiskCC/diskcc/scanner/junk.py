"""系统级垃圾：临时文件、回收站、缩略图缓存、预读取、错误报告、日志、转储等。"""

from __future__ import annotations

import os
from typing import List

from ..models import ItemKind, Risk, ScanItem
from ..utils import fs, win
from .base import ScannerBase, ScanContext


class SystemJunkScanner(ScannerBase):
    key = "junk"
    title = "系统垃圾与临时文件"

    def enabled(self) -> bool:
        return bool(self.ctx.cfg.get("scan_system_junk", True))

    # ---------------------------------------------------------------- 临时目录
    def _temp_entries(self, root: str, category: str, desc: str) -> List[ScanItem]:
        """列出临时目录顶层条目（跳过近期使用与被占用的）。"""
        out: List[ScanItem] = []
        if not fs.is_dir(root):
            return out
        # v1.3.2：一次 scandir 拿到全部子项及其类型；原先每个名字还要再 stat 一次
        dirs, files = fs.scan_dir(root)
        entries = [(n, ItemKind.DIR) for n in dirs] + [(n, ItemKind.FILE) for n in files]
        for name, kind in entries:
            if self.ctx.stopped():
                break
            p = os.path.join(root, name)
            try:
                if kind is ItemKind.DIR:
                    size, cnt = fs.dir_size(p)
                else:
                    size = fs.get_size(p)
                    cnt = 1
            except Exception:
                continue
            if size < self.ctx.min_size:
                continue
            age = fs.days_since(fs.get_mtime(p))
            if 0 <= age < 1:
                continue  # 24 小时内可能正在使用
            if self.ctx.is_running(p):
                continue
            item = self._mk(
                p,
                category,
                kind,
                size,
                Risk.SAFE,
                f"{desc}；{fs.mtime_text(p)}修改",
                source="system",
                file_count=cnt,
                extra={"age_days": round(age, 1)},
            )
            if item:
                out.append(item)
        return out

    # ---------------------------------------------------------------- 通用
    def _files_item(self, root: str, patterns: List[str], category: str, reason: str,
                    risk: Risk = Risk.SAFE, max_depth: int = 3) -> List[ScanItem]:
        if not fs.is_dir(root):
            return []
        files = fs.match_files(root, patterns, max_depth=max_depth)
        total, cnt = fs.sum_files(files)
        if not files:
            return []
        item = self._mk(
            root,
            category,
            ItemKind.FILES,
            total,
            risk,
            reason,
            source="system",
            file_count=cnt,
            patterns=patterns,
            extra={"recursive": max_depth > 0, "max_depth": max_depth},
        )
        return [item] if item else []

    def _dir_item(self, path: str, category: str, reason: str, risk: Risk = Risk.SAFE,
                  protected: bool = False) -> List[ScanItem]:
        if not fs.is_dir(path):
            return []
        size, cnt = fs.dir_size(path)
        item = self._mk(path, category, ItemKind.DIR, size, risk, reason,
                        source="system", file_count=cnt, protected=protected)
        return [item] if item else []

    def _file_item(self, path: str, category: str, reason: str, risk: Risk = Risk.LOW) -> List[ScanItem]:
        if not fs.is_file(path):
            return []
        item = self._mk(path, category, ItemKind.FILE, fs.get_size(path), risk, reason, source="system")
        return [item] if item else []

    # ---------------------------------------------------------------- 主流程
    def scan(self) -> List[ScanItem]:
        ctx = self.ctx
        items: List[ScanItem] = []
        self.ctx.log("[扫描] 系统垃圾与临时文件...")

        # 1. 临时目录
        items += self._temp_entries(ctx.temp, "user_temp", "用户临时目录（%TEMP%）下的临时数据")
        items += self._temp_entries(ctx.win_temp, "win_temp", "Windows 系统临时目录 C:\\Windows\\Temp")

        # 2. 回收站
        for drive_root in [ctx.drive]:
            rb = os.path.join(drive_root, "$RECYCLE.BIN")
            items += self._dir_item(rb, "recycle_bin", "回收站中的已删除文件，清理后不可恢复", Risk.SAFE)

        # 3. 缩略图 / 图标缓存
        explorer = os.path.join(ctx.localappdata, "Microsoft", "Windows", "Explorer")
        items += self._files_item(
            explorer, ["thumbcache_*.db", "iconcache_*.db"],
            "thumbnail", "资源管理器缩略图与图标缓存，删除后系统会自动重建", Risk.SAFE)
        items += self._dir_item(
            os.path.join(ctx.localappdata, "Microsoft", "Windows", "Explorer", "ThumbCacheToDelete"),
            "thumbnail", "待删除的缩略图缓存", Risk.SAFE)

        # 4. 预读取
        items += self._files_item(
            os.path.join(ctx.windows_dir, "Prefetch"), ["*.pf"],
            "prefetch", "Prefetch 预读取缓存，删除后系统会重新生成，可略微提升磁盘可用空间", Risk.LOW, max_depth=1)

        # 5. Windows 错误报告 WER
        items += self._dir_item(os.path.join(ctx.localappdata, "Microsoft", "Windows", "WER"),
                                "wer", "Windows 错误报告队列与归档（含崩溃报告）", Risk.SAFE)
        items += self._dir_item(os.path.join(ctx.programdata, "Microsoft", "Windows", "WER"),
                                "wer", "Windows 错误报告（系统级）", Risk.SAFE)

        # 6. 崩溃转储
        items += self._dir_item(os.path.join(ctx.localappdata, "CrashDumps"),
                                "crash_dump", "应用程序崩溃转储文件", Risk.LOW)
        items += self._dir_item(os.path.join(ctx.windows_dir, "Minidump"),
                                "crash_dump", "系统蓝屏小型内存转储", Risk.LOW)
        items += self._file_item(os.path.join(ctx.windows_dir, "MEMORY.DMP"),
                                 "crash_dump", "系统蓝屏完整内存转储（通常等同内存大小）", Risk.LOW)

        # 7. 系统日志
        items += self._files_item(os.path.join(ctx.windows_dir, "Logs"), ["*.log", "*.etl", "*.cab"],
                                  "win_log", "Windows 系统日志（CBS/DISM/更新日志）", Risk.LOW)
        items += self._file_item(os.path.join(ctx.windows_dir, "CBS.log"), "win_log",
                                 "CBS 组件安装日志", Risk.LOW)
        items += self._files_item(os.path.join(ctx.windows_dir, "Panther"), ["*.log", "*.etl"],
                                  "win_log", "Windows 安装/升级日志", Risk.LOW)
        items += self._files_item(os.path.join(ctx.windows_dir, "SoftwareDistribution"),
                                  ["ReportingEvents.log", "*.log"], "win_update_log",
                                  "Windows Update 日志文件", Risk.LOW, max_depth=1)

        # 8. IE / 系统网络缓存
        items += self._dir_item(os.path.join(ctx.localappdata, "Microsoft", "Windows", "INetCache"),
                                "browser", "系统 IE/内核网络缓存", Risk.SAFE)
        items += self._dir_item(os.path.join(ctx.localappdata, "Microsoft", "Windows", "WebCache"),
                                "browser", "系统 Web 缓存数据库", Risk.SAFE)
        items += self._dir_item(os.path.join(ctx.localappdata, "Microsoft", "Windows", "Temporary Internet Files"),
                                "browser", "IE 临时 Internet 文件", Risk.SAFE)

        # 9. 传递优化缓存
        items += self._dir_item(
            os.path.join(ctx.windows_dir, "ServiceProfiles", "NetworkService", "AppData", "Local",
                         "Microsoft", "Windows", "DeliveryOptimization"),
            "delivery_opt", "Windows 传递优化（更新分发）缓存", Risk.SAFE)
        items += self._dir_item(
            os.path.join(ctx.localappdata, "Microsoft", "Windows", "DeliveryOptimization"),
            "delivery_opt", "传递优化缓存（用户级）", Risk.SAFE)

        # 10. 字体缓存
        items += self._files_item(
            os.path.join(ctx.windows_dir, "ServiceProfiles", "LocalService", "AppData", "Local", "FontCache"),
            ["*.dat"], "font_cache", "系统字体缓存，重启后自动重建", Risk.SAFE, max_depth=1)

        # 11. 已下载的程序文件 / 陈旧补丁缓存
        items += self._dir_item(os.path.join(ctx.windows_dir, "Downloaded Program Files"),
                                "other", "已下载的 ActiveX 控件与 Java 小程序", Risk.LOW)

        # 12. ProgramData 下的临时与日志
        items += self._dir_item(os.path.join(ctx.programdata, "Microsoft", "Windows", "AppRepository"),
                                "other", "应用仓库缓存", Risk.LOW)

        return [i for i in items if i]
