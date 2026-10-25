"""清理记录对话框：查看历史清理、定位备份清单。"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..history import CleanHistory, HistoryEntry
from ..models import human_size
from ..utils import win

METHOD_LABEL = {"recycle": "回收站", "delete": "永久删除", "command": "执行命令", "mixed": "混合", "-": "-"}


class HistoryDialog(QDialog):
    def __init__(self, history: CleanHistory, parent=None):
        super().__init__(parent)
        self.history = history
        self.entries: List[HistoryEntry] = []
        self.setWindowTitle("清理记录")
        self.resize(760, 460)
        self._build()
        self._reload()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        tip = QLabel(
            "每次清理都会在这里留一条记录。默认勾选的备份清单文件记录了被清理的完整路径，"
            "可在设置→清理策略中开启/关闭。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8b95a5;")
        lay.addWidget(tip)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["时间", "成功", "失败", "释放", "方式", "耗时"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_sel)
        lay.addWidget(self.table, 1)

        self.detail = QLabel("选中一条记录查看详情")
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color:#c8d0dc;")
        lay.addWidget(self.detail)

        row = QHBoxLayout()
        self.btn_open_log = QPushButton("打开备份清单")
        self.btn_open_dir = QPushButton("打开清单所在目录")
        self.btn_del = QPushButton("删除此条")
        self.btn_clear = QPushButton("清空记录")
        for b in (self.btn_open_log, self.btn_open_dir, self.btn_del, self.btn_clear):
            b.setEnabled(False)
            row.addWidget(b)
        row.addStretch(1)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.button(QDialogButtonBox.Close).setText("关闭")
        btns.rejected.connect(self.reject)
        row.addWidget(btns)
        lay.addLayout(row)

        self.btn_open_log.clicked.connect(self._open_log)
        self.btn_open_dir.clicked.connect(self._open_dir)
        self.btn_del.clicked.connect(self._delete)
        self.btn_clear.clicked.connect(self._clear)

    # ---------------------------------------------------------------- 数据
    def _reload(self) -> None:
        self.entries = self.history.load()
        self.table.setRowCount(len(self.entries))
        for r, e in enumerate(self.entries):
            vals = [
                e.time,
                f"{e.ok} 项",
                f"{e.failed} 项",
                ("演练 " if e.dry_run else "") + human_size(e.freed),
                METHOD_LABEL.get(e.method, e.method),
                f"{e.elapsed:.1f}s",
            ]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.ItemDataRole.UserRole, e.ts)
                self.table.setItem(r, c, it)
        self.table.resizeColumnsToContents()
        self._on_sel()

    def _current(self) -> Optional[HistoryEntry]:
        r = self.table.currentRow()
        if 0 <= r < len(self.entries):
            return self.entries[r]
        return None

    def _on_sel(self) -> None:
        e = self._current()
        has = e is not None
        self.btn_del.setEnabled(has)
        self.btn_clear.setEnabled(bool(self.entries))
        self.btn_open_log.setEnabled(has and bool(e.log_file) and os.path.isfile(e.log_file))
        self.btn_open_dir.setEnabled(has and bool(e.log_file))
        if not e:
            self.detail.setText("选中一条记录查看详情")
            return
        lines = [
            f"时间：{e.time}    耗时：{e.elapsed:.1f}s    方式：{METHOD_LABEL.get(e.method, e.method)}",
            f"成功 {e.ok} 项，失败 {e.failed} 项，释放 {human_size(e.freed)}"
            + ("（演练模式，未真正删除）" if e.dry_run else ""),
        ]
        lines.append(f"备份清单：{e.log_file or '（未生成）'}")
        if e.paths:
            preview = "\n".join("· " + p for p in e.paths[:10])
            more = f"\n… 另有 {len(e.paths) - 10} 条，详见备份清单" if len(e.paths) > 10 else ""
            lines.append("已清理路径（前 10 条）：\n" + preview + more)
        self.detail.setText("\n".join(lines))

    # ---------------------------------------------------------------- 动作
    @staticmethod
    def _open_path(path: str) -> bool:
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return True
        except Exception:
            return False

    def _open_log(self) -> None:
        e = self._current()
        if e and e.log_file:
            if not self._open_path(e.log_file):
                QMessageBox.warning(self, "打开失败", f"无法打开：\n{e.log_file}")

    def _open_dir(self) -> None:
        e = self._current()
        if not e or not e.log_file:
            return
        d = os.path.dirname(e.log_file)
        if os.path.isdir(d):
            win.open_in_explorer(d)
        else:
            QMessageBox.information(self, "提示", "清单文件已不存在")

    def _delete(self) -> None:
        e = self._current()
        if not e:
            return
        self.history.remove(e.ts)
        self._reload()

    def _clear(self) -> None:
        if QMessageBox.question(self, "确认", "确定清空全部清理记录吗？（不会影响已生成的历史备份清单文件）") \
                != QMessageBox.Yes:
            return
        self.history.clear()
        self._reload()
