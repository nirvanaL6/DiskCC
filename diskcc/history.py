"""清理历史：记录每次清理的结果，便于事后追溯与查找备份清单。

市面上工具被吐槽最多的一点就是"删完就找不回来了"，DiskCC 每次清理都会写入
备份清单，但用户往往不知道清单在哪。这里把每次清理的关键信息落盘，
配合界面上的【清理记录】即可一键定位清单文件。
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from .utils.fs import app_data_dir

HISTORY_FILE = "clean_history.json"
MAX_RECORDS = 100          # 最多保留条数
MAX_PATHS = 30             # 每条记录最多保存的路径数


@dataclass
class HistoryEntry:
    time: str = ""             # 本地时间字符串
    ts: float = 0.0            # 时间戳（排序用）
    ok: int = 0                # 成功项数
    failed: int = 0            # 失败项数
    freed: int = 0             # 释放字节数
    dry_run: bool = False
    method: str = ""           # recycle / delete / mixed
    log_file: str = ""         # 备份清单路径
    paths: List[str] = field(default_factory=list)
    elapsed: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "HistoryEntry":
        return HistoryEntry(
            time=d.get("time", ""),
            ts=float(d.get("ts", 0) or 0),
            ok=int(d.get("ok", 0) or 0),
            failed=int(d.get("failed", 0) or 0),
            freed=int(d.get("freed", 0) or 0),
            dry_run=bool(d.get("dry_run", False)),
            method=d.get("method", ""),
            log_file=d.get("log_file", ""),
            paths=list(d.get("paths", []) or []),
            elapsed=float(d.get("elapsed", 0) or 0),
        )


class CleanHistory:
    """线程安全的清理历史读写。"""

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(app_data_dir(), HISTORY_FILE)
        self._lock = threading.RLock()

    # ---------------------------------------------------------------- 读
    def load(self) -> List[HistoryEntry]:
        try:
            if not os.path.isfile(self.path):
                return []
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        out: List[HistoryEntry] = []
        for d in data:
            try:
                out.append(HistoryEntry.from_dict(d))
            except Exception:
                continue
        out.sort(key=lambda e: e.ts, reverse=True)
        return out

    # ---------------------------------------------------------------- 写
    def append(self, entry: HistoryEntry) -> None:
        with self._lock:
            records = self.load()
            records.insert(0, entry)
            del records[MAX_RECORDS:]
            self._save(records)

    def record_from_report(self, report, dry_run: bool = False) -> HistoryEntry:
        """从 CleanReport 生成一条历史记录并写入。"""
        methods = {r.method for r in report.records if r.ok}
        if len(methods) > 1:
            method = "mixed"
        elif methods:
            method = next(iter(methods))
        else:
            method = "-"
        entry = HistoryEntry(
            time=time.strftime("%Y-%m-%d %H:%M:%S"),
            ts=time.time(),
            ok=report.ok_count,
            failed=report.failed,
            freed=report.freed,
            dry_run=dry_run,
            method=method,
            log_file=getattr(report, "log_file", "") or "",
            paths=[r.path for r in report.records if r.ok][:MAX_PATHS],
            elapsed=max(0.0, (report.finished_at or time.time()) - report.started_at),
        )
        self.append(entry)
        return entry

    def remove(self, ts: float) -> None:
        with self._lock:
            records = [e for e in self.load() if abs(e.ts - ts) > 1e-6]
            self._save(records)

    def clear(self) -> None:
        with self._lock:
            self._save([])

    def _save(self, records: List[HistoryEntry]) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump([e.to_dict() for e in records], f, ensure_ascii=False, indent=2)
        except Exception:
            pass
