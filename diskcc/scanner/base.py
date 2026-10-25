"""扫描器基类与扫描上下文。"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable, Dict, List, Optional, Set

from ..ai.analyzer import AIAnalyzer
from ..config import Config
from ..models import CATEGORIES, Category, ItemKind, Risk, ScanItem
from ..utils import fs, win


class ScanContext:
    """扫描过程共享的上下文（路径、配置、AI、进度回调等）。"""

    def __init__(
        self,
        cfg: Config,
        ai: Optional[AIAnalyzer] = None,
        log: Optional[Callable[[str], None]] = None,
        progress: Optional[Callable[[str, float], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        drive: str = "",
    ):
        self.cfg = cfg
        self.ai = ai or AIAnalyzer(cfg, log)
        self.log = log or (lambda m: None)
        self.progress = progress or (lambda m, p: None)
        self.cancel = cancel_event or threading.Event()
        self.items: List[ScanItem] = []
        self.errors: List[str] = []
        self._installed: Optional[Dict[str, Dict[str, str]]] = None
        self._procs: Optional[Set[str]] = None
        self._lock = threading.Lock()
        self._seen: Set[str] = set()
        self._exclude_cache: Optional[List[str]] = None

        # AI 分析候选队列（由扫描器收集，manager 在独立的“AI 分析”步骤统一执行）
        self.ai_pf_targets: List[Dict[str, Any]] = []
        self.ai_pf_keys: Set[str] = set()
        self.ai_ad_targets: List[Dict[str, Any]] = []
        self.ai_ad_keys: Set[str] = set()

        self.drive = drive or os.environ.get("SYSTEMDRIVE", "C:") + "\\"
        if not self.drive.endswith("\\"):
            self.drive += "\\"
        home = os.path.expanduser("~")
        self.userprofile = os.environ.get("USERPROFILE") or home
        self.appdata = os.environ.get("APPDATA") or os.path.join(self.userprofile, "AppData", "Roaming")
        self.localappdata = os.environ.get("LOCALAPPDATA") or os.path.join(self.userprofile, "AppData", "Local")
        self.locallow = os.path.join(self.userprofile, "AppData", "LocalLow")
        self.programdata = os.environ.get("PROGRAMDATA") or os.path.join(self.drive, "ProgramData")
        self.temp = os.environ.get("TEMP") or os.path.join(self.localappdata, "Temp")
        self.win_temp = os.path.join(self.drive, "Windows", "Temp")
        self.windows_dir = os.environ.get("WINDIR") or os.path.join(self.drive, "Windows")
        pf = os.environ.get("PROGRAMFILES") or os.path.join(self.drive, "Program Files")
        pf86 = os.environ.get("PROGRAMFILES(X86)") or os.path.join(self.drive, "Program Files (x86)")
        self.program_files = [p for p in (pf, pf86) if p]
        self.user_programs = os.path.join(self.localappdata, "Programs")

    # ------------------------------------------------------------ 便捷属性
    @property
    def min_size(self) -> int:
        return int(float(self.cfg.get("min_size_mb", 1)) * 1024 * 1024)

    @property
    def idle_days(self) -> int:
        return int(self.cfg.get("idle_days", 90))

    @property
    def exclude(self) -> List[str]:
        # v1.2.0：排除列表在扫描期间视为不变，缓存规范化结果。
        # 原实现每加入一个项目都要重新规范化全部排除路径，大磁盘下是纯浪费。
        if getattr(self, "_exclude_cache", None) is None:
            self._exclude_cache = [fs.norm(p) for p in self.cfg.get("exclude_paths", []) or []]
        return self._exclude_cache

    def is_excluded(self, path: str) -> bool:
        p = fs.norm(path)
        for ex in self.exclude:
            if p == ex or p.startswith(ex + "\\") or p.startswith(ex + "/"):
                return True
        return False

    # ------------------------------------------------------------ 懒加载
    @property
    def installed(self) -> Dict[str, Dict[str, str]]:
        # v1.2.0：并行扫描下双重检查加锁，避免多线程重复读注册表（很耗时）
        if self._installed is None:
            with self._lock:
                if self._installed is None:
                    self._installed = win.read_installed_software()
                    self.log(f"[注册表] 读取到 {len(self._installed)} 条安装记录")
        return self._installed

    @property
    def processes(self) -> Set[str]:
        if self._procs is None:
            with self._lock:
                if self._procs is None:
                    self._procs = win.running_process_names()
        return self._procs

    # ------------------------------------------------------------ AI 候选队列
    def queue_ai_pf(self, feat: Dict[str, Any], key: str) -> None:
        """登记一个待 AI 分析的 Program Files 目录（线程安全）。"""
        with self._lock:
            self.ai_pf_keys.add(key)
            self.ai_pf_targets.append(feat)

    def queue_ai_ad(self, feat: Dict[str, Any], key: str) -> None:
        """登记一个待 AI 分析的 AppData 目录（线程安全）。"""
        with self._lock:
            self.ai_ad_keys.add(key)
            self.ai_ad_targets.append(feat)

    def is_running(self, path: str) -> bool:
        base = os.path.basename(path).lower()
        return base in self.processes

    # ------------------------------------------------------------ 输出
    def add(self, item: ScanItem) -> Optional[ScanItem]:
        if not item.path:
            return None
        # v1.3.0：已取消时不再收项。并行扫描下已启动的任务是"孤儿"，
        # 它们会各自检查 stopped() 后退出，但退出前仍可能提交最后几个结果；
        # 取消后继续入项会让"停止"的语义变得模糊。
        if self.stopped():
            return None
        if self.is_excluded(item.path):
            return None
        # Windows 目录下的直接子文件夹通常受系统保护、无法删除，不应作为清理项；
        # 仅允许显式白名单内的目录（已是各项扫描器有意加入的安全清理目标）。
        if item.kind == ItemKind.DIR and self._windows_child_blocked(item.path):
            return None

        if (
            item.size < self.min_size
            and item.kind != ItemKind.COMMAND
            and item.category not in ("bad_shortcut", "empty_dir")
        ):
            return None
        # 同路径同类型去重（不同扫描器可能命中同一目标）。
        # v1.2.0：并行扫描下必须把"查重 + 登记"放进同一把锁，否则会重复入项。
        dedup_key = f"{fs.norm(item.path)}|{item.kind.value}"
        # v1.1.3：扫描结果默认不勾选任何项目，由用户自行甄别后手动勾选，
        # 避免误删（Category.default_checked 字段保留，仅作展示用途）。
        item.checked = False
        with self._lock:
            if dedup_key in self._seen:
                return None
            self._seen.add(dedup_key)
            self.items.append(item)
        return item

    def add_many(self, items: List[ScanItem]) -> None:
        for it in items:
            self.add(it)

    def error(self, msg: str) -> None:
        with self._lock:
            self.errors.append(msg)
        self.log(f"[错误] {msg}")

    def stopped(self) -> bool:
        return self.cancel.is_set()

    # ------------------------------------------------------------ Windows 子目录保护
    # 允许作为清理项直接加入的 Windows 直接子目录白名单（小写）。其余一律视为系统保护、不可删。
    WINDOWS_DELETABLE = {
        "temp", "softwaredistribution", "prefetch", "logs", "minidump", "panther",
        "downloaded program files", "downloaded installations", "serviceprofiles",
        "softwaredownload", "inf", "temp", "winsxs",  # winsxs 仅当以命令方式清理，目录本身不删
    }

    def _windows_child_blocked(self, path: str) -> bool:
        """path 是否为 C:\Windows 下的直接子文件夹且不在可删除白名单内。"""
        try:
            norm_path = fs.norm(path)
            norm_win = fs.norm(self.windows_dir)
        except Exception:
            return False
        if not (norm_path == norm_win or norm_path.startswith(norm_win + "\\")
                or norm_path.startswith(norm_win + "/")):
            return False
        # 仅判断 Windows 的直接子级（path 的父目录就是 windows_dir）
        parent = os.path.dirname(norm_path.rstrip("\\/"))
        if parent != norm_win:
            return False
        name = os.path.basename(norm_path.rstrip("\\/")).lower()
        return name not in self.WINDOWS_DELETABLE


class ScannerBase:
    """扫描器基类。"""

    key = "base"
    title = "基础扫描"

    def __init__(self, ctx: ScanContext):
        self.ctx = ctx

    # 是否启用（由配置控制）
    def enabled(self) -> bool:
        return True

    def scan(self) -> List[ScanItem]:
        raise NotImplementedError

    # ------------------------------------------------------------ 辅助
    def _mk(
        self,
        path: str,
        category: str,
        kind: Any = None,
        size: Optional[int] = None,
        risk: Optional[Risk] = None,
        reason: str = "",
        software: str = "",
        source: str = "rule",
        protected: bool = False,
        **kwargs: Any,
    ) -> Optional[ScanItem]:
        from ..models import ItemKind

        if kind is None:
            kind = ItemKind.DIR
        if size is None:
            if kind == ItemKind.DIR:
                size, cnt = fs.dir_size(path)
                kwargs.setdefault("file_count", cnt)
            else:
                size = fs.get_size(path)
        cat = CATEGORIES.get(category)
        if risk is None:
            risk = cat.default_risk if cat else Risk.MEDIUM
        item = ScanItem(
            path=path,
            category=category,
            kind=kind,
            size=size,
            risk=risk,
            reason=reason,
            software=software,
            source=source,
            protected=protected,
            mtime=fs.get_mtime(path),
            **kwargs,
        )
        return self.ctx.add(item)

    def _dir_item(
        self,
        path: str,
        category: str,
        reason: str,
        software: str = "",
        risk: Optional[Risk] = None,
        source: str = "rule",
        protected: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Optional[ScanItem]:
        if not fs.is_dir(path):
            return None
        size, cnt = fs.dir_size(path)
        return self._mk(
            path,
            category,
            None,
            size,
            risk,
            reason,
            software,
            source,
            protected,
            file_count=cnt,
            extra=extra or {},
        )
