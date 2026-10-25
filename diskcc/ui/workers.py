"""后台线程：扫描、清理与手动 AI 识别。"""

from __future__ import annotations

import os
import time
from typing import Callable, List, Optional

from PySide6.QtCore import QThread, Signal

from ..ai.analyzer import AIAnalyzer
from ..cleaner import Cleaner
from ..config import Config
from ..models import CleanReport, ScanItem, ScanResult
from ..scanner.appdata import _apply_ai_ad
from ..scanner.manager import ScanManager
from ..scanner.programfiles import ProgramFilesScanner, _apply_ai_pf
from ..utils import fs


class _Throttle:
    """进度信号节流器（v1.3.2）。

    扫描器会在遍历的每个小阶段回调进度，真实磁盘上动辄上万次。每次回调都会
    跨线程往 GUI 线程投递一个事件，UI 线程光处理这些事件就忙不过来，表现为
    "扫描时界面很卡"。这里按【时间间隔 + 百分比变化】双重条件合并：
    默认最快 80ms 一次，且进度至少动 1% 才发射；最后一个百分点（99→100）
    一定会发出，避免界面停在 99%。
    """

    def __init__(self, emit: Callable[[str, int], None],
                 min_interval: float = 0.08, min_step: float = 1.0):
        self._emit = emit
        self._min_interval = min_interval
        self._min_step = min_step
        self._last_t = 0.0
        self._last_pct = -1.0

    def __call__(self, text: str, pct: float) -> None:
        try:
            p = max(0.0, min(100.0, float(pct)))
        except Exception:
            p = 0.0
        now = time.perf_counter()
        enough_time = (now - self._last_t) >= self._min_interval
        enough_step = abs(p - self._last_pct) >= self._min_step
        if not (enough_time and enough_step):
            return
        self._last_t = now
        self._last_pct = p
        self._emit(text, int(p))


def _appdata_feat(item: ScanItem) -> dict:
    """构造 AppData 目录用于 AI 分析的特征（右键识别时按需采集）。"""
    p = item.path
    # v1.3.2：一次 scandir 取代两轮 listdir + 逐项 stat
    _subdirs, _files = fs.scan_dir(p)
    subdirs = _subdirs[:12]
    files = _files[:10]
    return {
        "path": p,
        "folder": item.name,
        "size": item.size,
        "file_count": item.file_count,
        "subdirs": subdirs,
        "files": files,
        "last_modified": fs.mtime_text(p),
    }


class ScanWorker(QThread):
    progress = Signal(str, int)
    logged = Signal(str)
    finished = Signal(object)

    def __init__(self, cfg: Config, ai: AIAnalyzer, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.ai = ai
        self.manager: Optional[ScanManager] = None

    def stop(self) -> None:
        if self.manager:
            self.manager.stop()

    def run(self) -> None:  # pragma: no cover - 线程入口
        # v1.3.2：进度经节流后再跨线程发射，避免高频回调淹没 GUI 线程
        self.manager = ScanManager(
            self.cfg,
            self.ai,
            log=lambda m: self.logged.emit(m),
            progress=_Throttle(lambda m, p: self.progress.emit(m, p)),
        )
        try:
            result = self.manager.run()
        except Exception as e:
            result = ScanResult(errors=[str(e)])
            self.logged.emit(f"[严重错误] {e}")
        self.finished.emit(result)


class CleanWorker(QThread):
    progress = Signal(str, int)
    logged = Signal(str)
    finished = Signal(object)

    def __init__(self, cfg: Config, items: List, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.items = items
        self.cleaner: Optional[Cleaner] = None

    def stop(self) -> None:
        if self.cleaner:
            self.cleaner.stop()

    def run(self) -> None:  # pragma: no cover - 线程入口
        self.cleaner = Cleaner(
            self.cfg,
            log=lambda m: self.logged.emit(m),
            progress=_Throttle(lambda m, p: self.progress.emit(m, p)),   # v1.3.2：节流
        )
        try:
            report = self.cleaner.clean(self.items)
        except Exception as e:
            report = CleanReport()
            report.records = []
            self.logged.emit(f"[严重错误] {e}")
        self.finished.emit(report)


class AIWorker(QThread):
    """在后台对单个目录执行手动 AI 识别（规则库识别不出的项目，用户主动触发）。"""

    progress = Signal(str, int)
    logged = Signal(str)
    finished = Signal(object)   # dict: {"item": ScanItem, "ok": bool, "msg": str}

    def __init__(self, cfg: Config, ai: AIAnalyzer, item: ScanItem, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.ai = ai
        self.item = item

    def run(self) -> None:  # pragma: no cover - 线程入口
        item = self.item
        # v1.2.0：记录识别前的分类。AI 可能把项目重新归类，界面需要据此决定
        # 是否保留原分类节点、是否跟随项目跳转。
        old_category = item.category
        if not self.ai or not self.ai.enabled:
            self.finished.emit({"item": item, "ok": False, "old_category": old_category,
                                "msg": "AI 未启用或未配置 API"})
            return
        self.progress.emit(f"AI 识别：{item.name}", 10)
        try:
            if item.category.startswith("pf_"):
                feat = ProgramFilesScanner._features(item.path)
                res = self.ai.analyze_program_files([feat])
                key = f"pf:{os.path.basename(item.path).lower()}"
                ai_res = res.get(key)
                if ai_res is None:
                    self.finished.emit(
                        {"item": item, "ok": False, "old_category": old_category,
                         "msg": "AI 未返回有效结论（可能网络超时或未命中）"})
                    return
                _apply_ai_pf(item, ai_res)
            elif item.category.startswith("appdata_"):
                feat = _appdata_feat(item)
                res = self.ai.analyze_appdata([feat])
                key = f"ad:{item.path.lower().replace(chr(92), '/')}"
                ai_res = res.get(key)
                if ai_res is None:
                    self.finished.emit(
                        {"item": item, "ok": False, "old_category": old_category,
                         "msg": "AI 未返回有效结论（可能网络超时或未命中）"})
                    return
                _apply_ai_ad(item, ai_res)
            else:
                # 不支持的项已由右键菜单置灰拦截，此处仅兜底记录，不弹窗
                self.finished.emit({"item": item, "ok": False, "old_category": old_category,
                                "msg": "该类型暂不支持 AI 识别", "no_popup": True})
                return
            self.ai.save_cache()
            self.progress.emit(f"AI 识别：{item.name}", 100)
            self.finished.emit({"item": item, "ok": True, "old_category": old_category,
                            "msg": "AI 识别完成"})
        except Exception as e:
            self.finished.emit({"item": item, "ok": False, "old_category": old_category,
                            "msg": f"识别失败：{e}"})
