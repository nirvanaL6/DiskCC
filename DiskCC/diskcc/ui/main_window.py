"""DiskCC 主窗口。"""

from __future__ import annotations

import os
import time
from typing import Dict, Iterable, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..cleaner import Cleaner
from ..config import Config
from ..history import CleanHistory
from ..models import CATEGORIES, Category, ItemKind, Risk, ScanItem, ScanResult, human_size
from ..utils import fs, win
from .charts import PALETTE, SpaceOverview
from .history_dialog import HistoryDialog
from .settings_dialog import SettingsDialog
from .style import qss
from .workers import AIWorker, CleanWorker, ScanWorker

COLUMNS = ["", "名称", "大小", "风险", "分类", "归属软件", "来源", "说明", "路径"]
COL_CHECK, COL_NAME, COL_SIZE, COL_RISK, COL_CAT, COL_SW, COL_SRC, COL_REASON, COL_PATH = range(9)

SOURCE_LABEL = {
    "rule": "规则库",
    "registry": "注册表",
    "pe": "文件信息",
    "ai": "AI",
    "system": "系统",
}

RISK_ORDER = {Risk.SAFE: 0, Risk.LOW: 1, Risk.MEDIUM: 2, Risk.HIGH: 3, Risk.DANGEROUS: 4}

# 分类配色（按分类展示顺序固定取色，保证多次扫描颜色稳定）
_CAT_COLORS: Dict[str, str] = {
    k: PALETTE[i % len(PALETTE)]
    for i, k in enumerate(sorted(CATEGORIES, key=lambda x: CATEGORIES[x].order))
}


class SizeTableItem(QTableWidgetItem):
    """大小列的单元格：展示人类可读文本，但排序时使用真实字节数（数值排序）。"""

    def __init__(self, size: int, text: str):
        super().__init__(text)
        self._size = size

    def data(self, role):
        if role in (Qt.ItemDataRole.UserRole, Qt.ItemDataRole.EditRole):
            return self._size
        return super().data(role)


class MainWindow(QMainWindow):
    def __init__(self, cfg: Config, ai=None):
        super().__init__()
        self.cfg = cfg
        self.ai = ai
        # v1.3.0：项目列表改为属性（见下方 items property），赋值时一并让
        # id 索引失效；_id_index 供 _item_by_id 复用，避免每次线性扫描。
        self._items: List[ScanItem] = []
        self._id_index: Optional[Dict[str, ScanItem]] = None
        self.row_items: List[ScanItem] = []
        self.result: Optional[ScanResult] = None
        self.scan_worker: Optional[ScanWorker] = None
        self.clean_worker: Optional[CleanWorker] = None
        self.ai_worker: Optional[AIWorker] = None
        self.current_cat = "__all__"
        self._sort_col = -1
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._updating = False
        self._suppress_tree_select = False
        self.cat_nodes: Dict[str, QTreeWidgetItem] = {}
        self.history = CleanHistory()

        # v1.2.0：日志与进度改为"缓冲 + 定时合并刷新"。
        # 扫描/清理时后台线程每秒可发出成百上千条信号，逐条直接操作控件会把主线程
        # 堵死（Windows 会在 5 秒无消息响应后判定"无响应"）。这里统一进缓冲区，
        # 每 120ms 合并应用一次，主线程始终保持可响应。
        self._log_buf: List[str] = []
        self._pending_progress: Optional[Tuple[str, int]] = None
        self._ui_flush_timer = QTimer(self)
        self._ui_flush_timer.setInterval(120)
        self._ui_flush_timer.timeout.connect(self._flush_ui_updates)
        self._ui_flush_timer.start()

        self.setWindowTitle(f"DiskCC · C 盘智能清理 v{__version__}")
        w = int(cfg.get("window_width", 1180))
        h = int(cfg.get("window_height", 760))
        self.resize(w, h)
        self._build_ui()
        self._apply_theme()
        self._refresh_disk()
        self.update_ai_status()
        QTimer.singleShot(300, self.start_scan)

    # ================================================================ 项目列表
    @property
    def items(self) -> List[ScanItem]:
        return self._items

    @items.setter
    def items(self, value: List[ScanItem]) -> None:
        """赋值入口：任何一次整体替换都让 id 索引随之失效。

        全项目里 items 只有整体替换（没有原地 append/pop），因此在这里统一
        失效即可保证索引与列表始终一致。
        """
        self._items = value
        self._id_index = None

    # ================================================================ 界面构建
    def _build_ui(self) -> None:
        self._build_toolbar()

        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 4, 8, 4)
        main_layout.setSpacing(6)

        # 提示条
        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        self.hint.hide()
        main_layout.addWidget(self.hint)

        # 磁盘信息
        disk_row = QHBoxLayout()
        self.disk_label = QLabel("C 盘：正在获取...")
        self.disk_bar = QProgressBar()
        self.disk_bar.setFixedHeight(16)
        self.disk_bar.setRange(0, 100)
        disk_row.addWidget(self.disk_label)
        disk_row.addWidget(self.disk_bar, 1)
        main_layout.addLayout(disk_row)

        # 空间占用构成（按分类着色的堆叠条，点击色块/图例跳到该分类）
        self.overview = SpaceOverview(central)
        self.overview.categoryClicked.connect(self._goto_category)
        main_layout.addWidget(self.overview)

        # 主体：左分类 / 右明细
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._build_left())
        split.addWidget(self._build_right())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([250, 900])
        main_layout.addWidget(split, 3)

        # 详情
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFixedHeight(110)
        self.detail.setPlaceholderText("选中某一行查看完整说明（作用、识别来源、AI 置信度等）")
        main_layout.addWidget(self.detail)

        # 日志
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(120)
        self.log_view.setPlaceholderText("运行日志")
        main_layout.addWidget(self.log_view)

        # 进度
        prog_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("就绪")
        self.status_label = QLabel("")
        prog_row.addWidget(self.progress, 1)
        prog_row.addWidget(self.btn_stop)
        main_layout.addLayout(prog_row)

        self.setCentralWidget(central)
        self.statusBar().showMessage("就绪")

    def _build_toolbar(self) -> None:
        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)

        self.btn_scan = QPushButton("🔍 开始扫描")
        self.btn_scan.setObjectName("primary")
        self.btn_scan.clicked.connect(self.start_scan)

        self.btn_stop = QPushButton("⏹ 停止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_scan)

        self.btn_clean = QPushButton("🧹 清理选中")
        self.btn_clean.setObjectName("danger")
        self.btn_clean.setEnabled(False)
        self.btn_clean.clicked.connect(self.start_clean)

        self.btn_safe = QPushButton("全选")
        self.btn_safe.setMenu(self._build_select_menu())
        self.btn_none = QPushButton("全部取消")
        self.btn_none.clicked.connect(self.select_none)
        self.btn_invert = QPushButton("反选")
        self.btn_invert.clicked.connect(self.select_invert)

        self.btn_settings = QPushButton("⚙ 设置")
        self.btn_settings.clicked.connect(self.open_settings)

        self.btn_export = QPushButton("导出报告")
        self.btn_export.clicked.connect(self.export_report)

        self.btn_history = QPushButton("📜 清理记录")
        self.btn_history.clicked.connect(self.show_history)

        self.btn_about = QPushButton("关于")
        self.btn_about.clicked.connect(self.show_about)

        self.btn_admin = QPushButton("以管理员重启")
        self.btn_admin.clicked.connect(self.relaunch_admin)
        self.btn_admin.setVisible(not win.is_admin() and fs.IS_WINDOWS)

        for w in (self.btn_scan, self.btn_clean, self.btn_safe,
                  self.btn_none, self.btn_invert, self.btn_settings, self.btn_export,
                  self.btn_history, self.btn_about, self.btn_admin):
            tb.addWidget(w)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        self.ai_status = QLabel("")
        tb.addWidget(self.ai_status)

    def _build_left(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        title = QLabel("分类")
        title.setObjectName("title")
        lay.addWidget(title)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.itemChanged.connect(self._on_tree_changed)
        self.tree.itemSelectionChanged.connect(self._on_tree_selected)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        lay.addWidget(self.tree)
        lay.addWidget(QLabel("提示：只有【安全/低风险】项会默认勾选，其余需手动确认。"))
        return w

    def _build_right(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        self.search = QComboBox()
        self.search.setEditable(True)
        self.search.setPlaceholderText("搜索名称 / 路径 / 软件...")
        self.search.setMinimumWidth(260)
        self.search.lineEdit().returnPressed.connect(self._apply_filter)
        self.search.currentTextChanged.connect(lambda _t: self._apply_filter())
        row.addWidget(self.search)

        self.risk_filter = QComboBox()
        self.risk_filter.addItem("全部风险", -1)
        for r in (Risk.SAFE, Risk.LOW, Risk.MEDIUM, Risk.HIGH, Risk.DANGEROUS):
            self.risk_filter.addItem(r.label, r.value)
        self.risk_filter.currentIndexChanged.connect(lambda _i: self._apply_filter())
        row.addWidget(self.risk_filter)

        self.lbl_count = QLabel("0 项")
        row.addWidget(self.lbl_count)
        row.addStretch(1)
        lay.addLayout(row)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemChanged.connect(self._on_table_changed)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.doubleClicked.connect(lambda _i: self.open_selected_dir())
        # 关闭 Qt 内置排序：其按文本(DisplayRole)排序会导致大小列出现
        # 17.82MB<178.78MB<18.15MB 的错位；改用自定义排序（大小/风险按数值，其余按文本）。
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_CHECK, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_NAME, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_SIZE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_RISK, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_CAT, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_SW, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_SRC, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_REASON, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_PATH, QHeaderView.Interactive)
        self.table.setColumnWidth(COL_NAME, 200)
        self.table.setColumnWidth(COL_SW, 110)
        self.table.setColumnWidth(COL_PATH, 300)
        lay.addWidget(self.table)
        return w

    def _apply_theme(self) -> None:
        QApplication.instance().setStyleSheet(qss(self.cfg.get("theme", "dark")))

    # ================================================================ 日志与状态
    def log(self, msg: str) -> None:
        """写日志：先进缓冲区，由定时器合并刷新（避免高频操作控件卡住主线程）。"""
        ts = time.strftime("%H:%M:%S")
        self._log_buf.append(f"[{ts}] {msg}")
        if len(self._log_buf) >= 200:      # 极端情况下防止缓冲区无限增长
            self._flush_ui_updates()

    def _flush_ui_updates(self) -> None:
        """一次性应用缓冲的日志与进度（始终在主线程执行）。"""
        if self._log_buf:
            text = "\n".join(self._log_buf)
            self._log_buf = []
            self.log_view.append(text)
            sb = self.log_view.verticalScrollBar()
            sb.setValue(sb.maximum())
            self._trim_log()
        pending = self._pending_progress
        if pending is not None:
            self._pending_progress = None
            text, value = pending
            self.progress.setValue(value)
            self.progress.setFormat(f"{text} %p%")
            self.statusBar().showMessage(text)
            self.update_ai_status()   # 扫描中实时刷新右上角 AI 调用/命中数

    def _trim_log(self) -> None:
        """限制日志总长度：日志越长，文本控件追加越慢，长时间运行会拖垮界面。"""
        limit = 120000
        doc = self.log_view.document()
        if doc.characterCount() > limit:
            cur = QTextCursor(doc)
            cur.setPosition(0)
            cur.setPosition(doc.characterCount() - limit // 2,
                            QTextCursor.MoveMode.KeepAnchor)
            cur.removeSelectedText()

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.btn_scan.setEnabled(not busy)
        self.btn_clean.setEnabled(not busy and bool(self.items))
        self.btn_stop.setEnabled(busy)
        self.btn_safe.setEnabled(not busy)
        self.btn_none.setEnabled(not busy)
        self.btn_invert.setEnabled(not busy)
        self.btn_export.setEnabled(not busy)
        self.btn_history.setEnabled(not busy)
        # v1.3.0：扫描/清理进行中禁止打开设置。此前可以改，但正在运行的这一轮
        # 已经按旧配置启动了（排除列表、体积阈值在上下文里已缓存），改了也只对
        # 下一次生效，反而让"我明明加了排除怎么还在"这类问题无从解释。
        self.btn_settings.setEnabled(not busy)
        self.progress.setFormat(text or "就绪")

    def _refresh_disk(self) -> None:
        drive = os.environ.get("SYSTEMDRIVE", "C:") + "\\"
        total, free = win.disk_usage(drive)
        if total:
            used_pct = int((total - free) / total * 100)
            self.disk_bar.setValue(used_pct)
            self.disk_label.setText(
                f"{drive} 总容量 {human_size(total)} · 可用 {human_size(free)} · 已用 {used_pct}%")
            self.disk_bar.setFormat(f"已用 {used_pct}%")
        else:
            self.disk_label.setText(f"{drive} 无法读取磁盘信息")
        if not win.is_admin():
            self.hint.setText(
                "⚠ 当前未以管理员身份运行：清理系统目录（Windows\\Temp、SoftwareDistribution、hiberfil.sys 等）"
                "与执行 DISM/powercfg 命令时可能失败。建议点击【以管理员重启】。")
            self.hint.show()
        else:
            self.hint.hide()

    def update_ai_status(self) -> None:
        if self.ai:
            self.ai_status.setText(self.ai.status_text())

    # ================================================================ 扫描
    def start_scan(self) -> None:
        if self.scan_worker and self.scan_worker.isRunning():
            return
        self.items = []
        self.row_items = []
        self._sort_col = -1
        self.table.setRowCount(0)
        self.tree.clear()
        self.log_view.clear()
        # v1.3.0：连缓冲区一起清。上一轮扫描若还有不足 200 条未刷新的日志，
        # 会在下一次定时刷新时带着旧时间戳追加进刚清空的日志区，出现"上轮残留"。
        self._log_buf.clear()
        self.overview.clear()
        self.log("开始扫描，请稍候（首次扫描可能持续数分钟）...")
        self._set_busy(True, "扫描中 %p%")
        self.progress.setValue(0)
        self.scan_worker = ScanWorker(self.cfg, self.ai)
        self.scan_worker.progress.connect(self._on_progress)
        self.scan_worker.logged.connect(self.log)
        self.scan_worker.finished.connect(self._on_scan_finished)
        self.scan_worker.start()

    def stop_scan(self) -> None:
        if self.scan_worker:
            self.scan_worker.stop()
            self.log("正在停止扫描...")

    def _on_progress(self, text: str, value: int) -> None:
        # v1.2.0：只记录最新值，真正的控件更新交给定时器合并处理
        self._pending_progress = (text, value)

    def _on_scan_finished(self, result: ScanResult) -> None:
        self.result = result
        self.items = list(result.items)
        self._pending_progress = None   # 丢弃待应用的进度，避免覆盖"扫描完成"状态
        self._set_busy(False)
        self.progress.setValue(100)
        self.progress.setFormat("扫描完成")
        self.log(
            f"扫描完成：共 {len(self.items)} 项，合计 {human_size(result.total_size)}，"
            f"耗时 {result.elapsed:.1f}s"
        )
        for e in result.errors[:10]:
            self.log(f"[错误] {e}")
        if self.ai and self.ai.enabled:
            self.log(f"[AI] 调用 {self.ai.calls} 次，缓存命中 {self.ai.hits}，失败 {self.ai.fails}")
        self.update_ai_status()
        self._populate_tree()
        self._apply_filter()
        self._update_space_overview()
        self._refresh_disk()
        if not self.items:
            self.log("提示：没有扫描到任何项目。可调小【忽略小于(MB)】阈值、"
                     "勾选【大文件/重复文件】，或以管理员身份运行后重试。")
        self.statusBar().showMessage(
            f"扫描完成 · 共 {len(self.items)} 项 · 耗时 {result.elapsed:.1f}s")
        # v1.3.0：立即落地本轮日志与状态，不必等下一个 120ms 刷新周期
        self._flush_ui_updates()

    # ================================================================ 分类树
    def _populate_tree(self, keep_selection: bool = False,
                       keep_categories: Optional[Iterable[str]] = None) -> None:
        """重建分类树。

        keep_categories：即使该分类已经没有任何项目也保留其节点。用于"分类里唯一的
        一项被 AI 重新归类"的场景——原分类不应凭空消失（v1.2.0 修复）。
        """
        self._updating = True
        # v1.2.0：重建期间关闭重绘，分类多时避免逐项重排
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        groups: Dict[str, List[ScanItem]] = {}
        for it in self.items:
            groups.setdefault(it.category, []).append(it)

        def add_row(parent, text: str, key: str, cat: Optional[Category]) -> QTreeWidgetItem:
            node = QTreeWidgetItem(parent)
            node.setText(0, text)
            node.setData(0, Qt.ItemDataRole.UserRole, key)
            flags = node.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate
            node.setFlags(flags)
            node.setCheckState(0, Qt.CheckState.Unchecked)
            return node

        root = self.tree.invisibleRootItem()
        all_node = add_row(root, f"全部 ({len(self.items)})", "__all__", None)
        all_node.setFlags(all_node.flags() & ~Qt.ItemFlag.ItemIsAutoTristate)

        # 已空但仍需保留的分类（如 AI 重新归类后遗留的原分类）一并纳入排序
        keys = list(groups.keys())
        for k in (keep_categories or ()):
            if k not in groups:
                keys.append(k)
        ordered = sorted(
            ((k, groups.get(k, [])) for k in keys),
            key=lambda kv: (CATEGORIES.get(kv[0], CATEGORIES["other"]).order,
                            -sum(i.size for i in kv[1])),
        )
        self.cat_nodes: Dict[str, QTreeWidgetItem] = {"__all__": all_node}
        for key, group in ordered:
            cat = CATEGORIES.get(key, CATEGORIES["other"])
            size = sum(i.size for i in group)
            checked = sum(1 for i in group if i.checked)
            empty = not group
            node = add_row(root, f"{cat.name} ({len(group)} · {human_size(size)})", key, cat)
            if empty:
                # 空分类：保留节点但置灰，勾选框保持未勾选，避免"全选"语义出错
                node.setForeground(0, QColor("#7f8c9a"))
            else:
                node.setCheckState(0, Qt.CheckState.Checked if checked == len(group) else (
                    Qt.CheckState.PartiallyChecked if checked else Qt.CheckState.Unchecked))
            node.setToolTip(0, cat.desc + ("（当前无项目）" if empty else ""))
            self.cat_nodes[key] = node
        self.tree.expandAll()
        # 保持当前分类选中（清理 / AI 识别后不再跳回"全部"）。
        # 抑制选中回调：是否刷新表格由调用方决定（避免重建表格导致刚识别的项"消失"）。
        self._suppress_tree_select = True
        try:
            target = all_node
            if keep_selection and self.current_cat != "__all__":
                node = self.cat_nodes.get(self.current_cat)
                if node is not None:
                    target = node
                else:
                    self.current_cat = "__all__"   # 该分类已无项目，回退到全部
            else:
                self.current_cat = "__all__"
            self.tree.setCurrentItem(target)
        finally:
            self._suppress_tree_select = False
        self.tree.setUpdatesEnabled(True)
        self._updating = False

    def _on_tree_changed(self, node: QTreeWidgetItem) -> None:
        if self._updating:
            return
        key = node.data(0, Qt.ItemDataRole.UserRole)
        state = node.checkState(0)
        checked = state == Qt.CheckState.Checked
        self._updating = True
        for it in self.items:
            if key == "__all__" or it.category == key:
                if not it.protected:
                    it.checked = checked
        self._refresh_table_checks()
        self._update_tree_texts()
        self._updating = False
        self._update_stats()

    def _on_tree_selected(self) -> None:
        if getattr(self, "_suppress_tree_select", False):
            return
        node = self.tree.currentItem()
        if not node:
            return
        self.current_cat = node.data(0, Qt.ItemDataRole.UserRole)
        self._apply_filter()

    def _update_tree_texts(self) -> None:
        self._updating = True
        groups: Dict[str, List[ScanItem]] = {}
        for it in self.items:
            groups.setdefault(it.category, []).append(it)
        for key, node in self.cat_nodes.items():
            if key == "__all__":
                n = len(self.items)
                sel = sum(1 for i in self.items if i.checked)
                node.setText(0, f"全部 ({n})")
                continue
            group = groups.get(key, [])
            size = sum(i.size for i in group)
            cat = CATEGORIES.get(key, CATEGORIES["other"])
            node.setText(0, f"{cat.name} ({len(group)} · {human_size(size)})")
        self._updating = False

    # ================================================================ 空间占用概览
    def _update_space_overview(self) -> None:
        """按分类统计占用并绘制构成条（Top10 + 其他合并）。"""
        if not self.items:
            self.overview.clear()
            return
        groups: Dict[str, int] = {}
        for it in self.items:
            groups[it.category] = groups.get(it.category, 0) + it.size
        ordered = sorted(groups.items(), key=lambda kv: -kv[1])
        top = [(k, v) for k, v in ordered[:10] if v > 0]
        rest = sum(v for k, v in ordered[10:])
        labels = {k: CATEGORIES[k].name if k in CATEGORIES else k for k, _ in ordered}
        segs = [(k, v, _CAT_COLORS.get(k, "#78909c")) for k, v in top]
        if rest > 0:
            labels["__rest__"] = f"其他 {len(ordered) - len(top)} 类"
            segs.append(("__rest__", rest, "#5a6270"))
        self.overview.set_data(segs, labels)

    def _goto_category(self, key: str) -> None:
        """点击构成条 / 图例跳到对应分类。"""
        node = self.cat_nodes.get(key)
        if node is None:
            return
        self.tree.setCurrentItem(node)

    # ================================================================ 表格
    def _apply_filter(self) -> None:
        text = (self.search.currentText() or "").strip().lower()
        risk_val = self.risk_filter.currentData()
        rows: List[ScanItem] = []
        for it in self.items:
            if self.current_cat != "__all__" and it.category != self.current_cat:
                continue
            if risk_val is not None and int(risk_val) >= 0 and it.risk.value != int(risk_val):
                continue
            if text and text not in (it.name.lower() + " " + it.path.lower() + " " +
                                     (it.software or "").lower()):
                continue
            rows.append(it)
        if self._sort_col >= 0:
            rows = self._sort_rows(rows, self._sort_col, self._sort_order)
        else:
            rows.sort(key=lambda i: (RISK_ORDER.get(i.risk, 9), -i.size))
        self._fill_table(rows)
        self._update_stats()

    def _fill_table(self, rows: List[ScanItem]) -> None:
        self._updating = True
        # v1.2.0：重建期间关闭重绘与信号。项目多时（数千行）这两个开关能省掉
        # 绝大部分逐行重排/重绘开销，是"扫描/清理结束瞬间卡死"的主要成因。
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(rows))
            self.row_items = rows
            for r, it in enumerate(rows):
                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                chk.setCheckState(Qt.CheckState.Checked if it.checked else Qt.CheckState.Unchecked)
                chk.setData(Qt.ItemDataRole.UserRole, it.id)
                self.table.setItem(r, COL_CHECK, chk)

                name_item = QTableWidgetItem(it.name)
                name_item.setData(Qt.ItemDataRole.UserRole, it.name)
                name_item.setToolTip(it.name + ("（受保护，禁止删除）" if it.protected else ""))
                if it.protected:
                    name_item.setForeground(QColor("#e74c3c"))
                self.table.setItem(r, COL_NAME, name_item)

                size_item = SizeTableItem(it.size, human_size(it.size))
                self.table.setItem(r, COL_SIZE, size_item)

                risk_item = QTableWidgetItem(it.risk.label)
                risk_item.setData(Qt.ItemDataRole.UserRole, it.risk.value)
                risk_item.setForeground(QColor(it.risk.color))
                self.table.setItem(r, COL_RISK, risk_item)

                cat_item = QTableWidgetItem(it.category_label)
                cat_item.setData(Qt.ItemDataRole.UserRole, it.category_label)
                self.table.setItem(r, COL_CAT, cat_item)

                sw_item = QTableWidgetItem(it.software or "-")
                sw_item.setData(Qt.ItemDataRole.UserRole, it.software or "-")
                self.table.setItem(r, COL_SW, sw_item)

                src_item = QTableWidgetItem(SOURCE_LABEL.get(it.source, it.source))
                src_item.setData(Qt.ItemDataRole.UserRole, SOURCE_LABEL.get(it.source, it.source))
                self.table.setItem(r, COL_SRC, src_item)

                reason_item = QTableWidgetItem(it.reason)
                reason_item.setData(Qt.ItemDataRole.UserRole, it.reason)
                reason_item.setToolTip(it.reason)
                self.table.setItem(r, COL_REASON, reason_item)

                path_item = QTableWidgetItem(it.path)
                path_item.setData(Qt.ItemDataRole.UserRole, it.path)
                path_item.setToolTip(it.path)
                self.table.setItem(r, COL_PATH, path_item)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
        self._updating = False
        self.lbl_count.setText(f"{len(rows)} 项")

    # ================================================================ 自定义列排序
    def _on_header_clicked(self, col: int) -> None:
        """点击列头排序（Qt 内置排序按文本，大小列会错位，故自定义）。"""
        if col == self._sort_col:
            self._sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder)
        else:
            self._sort_col = col
            self._sort_order = Qt.SortOrder.AscendingOrder
        self.table.horizontalHeader().setSortIndicator(self._sort_col, self._sort_order)
        self._apply_filter()

    def _sort_rows(self, rows: List[ScanItem], col: int, order: Qt.SortOrder) -> List[ScanItem]:
        if col == COL_SIZE:
            key = lambda it: it.size
        elif col == COL_RISK:
            key = lambda it: it.risk.value
        elif col == COL_NAME:
            key = lambda it: it.name.lower()
        elif col == COL_CAT:
            key = lambda it: it.category_label
        elif col == COL_SW:
            key = lambda it: (it.software or "-").lower()
        elif col == COL_SRC:
            key = lambda it: SOURCE_LABEL.get(it.source, it.source)
        elif col == COL_REASON:
            key = lambda it: it.reason
        elif col == COL_PATH:
            key = lambda it: it.path.lower()
        else:
            key = lambda it: 0
        return sorted(rows, key=key, reverse=(order == Qt.SortOrder.DescendingOrder))

    def _refresh_row(self, item: ScanItem) -> bool:
        """就地刷新某一行：把来源 / 说明 / 风险 / 分类 / 归属软件同步为最新（AI）结论。

        刻意不重建整张表格，这样刚识别的项目不会"消失"，视图也保持在当前分类。
        """
        target_row = -1
        for r in range(self.table.rowCount()):
            chk = self.table.item(r, COL_CHECK)
            if chk is not None and chk.data(Qt.ItemDataRole.UserRole) == item.id:
                target_row = r
                break
        if target_row < 0:
            return False
        self._updating = True
        try:
            chk = self.table.item(target_row, COL_CHECK)
            if chk is not None:
                chk.setCheckState(
                    Qt.CheckState.Checked if item.checked else Qt.CheckState.Unchecked)
            risk_item = self.table.item(target_row, COL_RISK)
            if risk_item is not None:
                risk_item.setText(item.risk.label)
                risk_item.setForeground(QColor(item.risk.color))
                risk_item.setData(Qt.ItemDataRole.UserRole, item.risk.value)
            cat_item = self.table.item(target_row, COL_CAT)
            if cat_item is not None:
                cat_item.setText(item.category_label)
                cat_item.setData(Qt.ItemDataRole.UserRole, item.category_label)
            sw_item = self.table.item(target_row, COL_SW)
            if sw_item is not None:
                sw_item.setText(item.software or "-")
                sw_item.setData(Qt.ItemDataRole.UserRole, item.software or "-")
            src_item = self.table.item(target_row, COL_SRC)
            if src_item is not None:
                src_item.setText(SOURCE_LABEL.get(item.source, item.source))
                src_item.setData(Qt.ItemDataRole.UserRole,
                                 SOURCE_LABEL.get(item.source, item.source))
            reason_item = self.table.item(target_row, COL_REASON)
            if reason_item is not None:
                reason_item.setText(item.reason)
                reason_item.setData(Qt.ItemDataRole.UserRole, item.reason)
        finally:
            self._updating = False
        return True

    def _refresh_table_checks(self) -> None:
        self._updating = True
        by_id = {i.id: i for i in self.items}
        for r in range(self.table.rowCount()):
            chk = self.table.item(r, COL_CHECK)
            if chk is None:
                continue
            it = by_id.get(chk.data(Qt.ItemDataRole.UserRole))
            if it:
                chk.setCheckState(Qt.CheckState.Checked if it.checked else Qt.CheckState.Unchecked)
        self._updating = False

    def _on_table_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or item.column() != COL_CHECK:
            return
        it = self._item_by_id(item.data(Qt.ItemDataRole.UserRole))
        if it is None:
            return
        if it.protected:
            self._updating = True
            item.setCheckState(Qt.CheckState.Unchecked)
            self._updating = False
            self.log(f"[保护] {it.name} 属于受保护项，已取消勾选")
            return
        it.checked = item.checkState() == Qt.CheckState.Checked
        self._update_tree_texts()
        self._sync_tree_states()
        self._update_stats()

    def _sync_tree_states(self) -> None:
        self._updating = True
        groups: Dict[str, List[ScanItem]] = {}
        for it in self.items:
            groups.setdefault(it.category, []).append(it)
        for key, node in self.cat_nodes.items():
            if key == "__all__":
                continue
            group = groups.get(key, [])
            if not group:
                continue
            sel = sum(1 for i in group if i.checked)
            node.setCheckState(0, Qt.CheckState.Checked if sel == len(group) else (
                Qt.CheckState.PartiallyChecked if sel else Qt.CheckState.Unchecked))
        self._updating = False

    def _item_by_id(self, item_id) -> Optional[ScanItem]:
        # v1.3.0：改为索引查找。勾选 / 右键 / 就地刷新 / 行选中都要按 id 反查，
        # 原实现是 O(N) 线性扫描，数千项时一次「全选」就是几万次比较。
        if self._id_index is None:
            self._id_index = {i.id: i for i in self._items}
        return self._id_index.get(item_id)

    def _current_item(self) -> Optional[ScanItem]:
        r = self.table.currentRow()
        if r < 0:
            return None
        chk = self.table.item(r, COL_CHECK)
        if chk is None:
            return None
        return self._item_by_id(chk.data(Qt.ItemDataRole.UserRole))

    def _on_row_selected(self) -> None:
        it = self._current_item()
        if not it:
            return
        lines = [
            f"【{it.name}】  {human_size(it.size)}  ·  {it.risk.label}",
            f"路径：{it.path}",
            f"分类：{it.category_label}    归属软件：{it.software or '未知'}    识别来源：{SOURCE_LABEL.get(it.source, it.source)}",
            f"说明：{it.reason}",
        ]
        if isinstance(it.extra, dict):
            extra_bits = []
            for k, v in it.extra.items():
                if k in ("subdirs",) and isinstance(v, list):
                    extra_bits.append(f"{k}: {', '.join(map(str, v[:8]))}")
                elif k in ("ai_confidence", "age_days", "uninstall_string", "publisher",
                           "version", "data_type", "installed", "rel", "idle", "exe_count"):
                    extra_bits.append(f"{k}: {v}")
            if extra_bits:
                lines.append("附加信息：" + " | ".join(extra_bits))
        if it.kind == ItemKind.COMMAND:
            lines.append(f"执行命令：{it.command}")
            if it.command_note:
                lines.append(f"注意：{it.command_note}")
        self.detail.setPlainText("\n".join(lines))

    def _update_stats(self) -> None:
        sel = [i for i in self.items if i.checked and not i.protected]
        size = sum(i.size for i in sel)
        high = sum(1 for i in sel if i.risk.value >= 3)
        self.status_label.setText(
            f"已选 {len(sel)} 项 · 预计释放 {human_size(size)}" + (f" · 含高风险 {high} 项" if high else ""))
        self.statusBar().showMessage(
            f"共 {len(self.items)} 项 · 已选 {len(sel)} 项 · 预计释放 {human_size(size)}")

    # ================================================================ 选择操作
    def _build_select_menu(self) -> QMenu:
        menu = QMenu(self)
        act0 = menu.addAction("仅全选安全项")
        act0.triggered.connect(lambda _checked=False: self.select_by_risk(0))
        act1 = menu.addAction("全选安全 + 低风险项")
        act1.triggered.connect(lambda _checked=False: self.select_by_risk(1))
        act2 = menu.addAction("全选安全 + 低风险 + 中等风险项")
        act2.triggered.connect(lambda _checked=False: self.select_by_risk(2))
        return menu

    def select_by_risk(self, max_risk: int) -> None:
        n = 0
        for it in self.items:
            if it.protected:
                it.checked = False
                continue
            it.checked = it.risk.value <= max_risk
            n += 1 if it.checked else 0
        self._refresh_table_checks()
        self._sync_tree_states()
        self._update_stats()
        label = {0: "安全", 1: "安全/低风险", 2: "安全/低风险/中等"}.get(max_risk, f"≤{max_risk} 级")
        self.log(f"已勾选 {n} 个{label}项")

    def select_none(self) -> None:
        for it in self.items:
            it.checked = False
        self._refresh_table_checks()
        self._sync_tree_states()
        self._update_stats()

    def select_invert(self) -> None:
        for it in self.items:
            if it.protected:
                it.checked = False
            else:
                it.checked = not it.checked
        self._refresh_table_checks()
        self._sync_tree_states()
        self._update_stats()

    # ================================================================ 清理
    def start_clean(self) -> None:
        # v1.2.0：与扫描 / AI 识别互斥，避免并发读写同一批项目
        if self.scan_worker and self.scan_worker.isRunning():
            QMessageBox.information(self, "提示", "扫描进行中，请稍候或先停止扫描")
            return
        if self.ai_worker and self.ai_worker.isRunning():
            QMessageBox.information(self, "提示", "AI 识别进行中，请稍候")
            return
        sel = [i for i in self.items if i.checked and not i.protected]
        if not sel:
            QMessageBox.information(self, "提示", "请先勾选要清理的项目")
            return
        size = sum(i.size for i in sel)
        high = [i for i in sel if i.risk.value >= 3]
        cmds = [i for i in sel if i.kind == ItemKind.COMMAND]

        tips = [f"共 {len(sel)} 项，预计释放 {human_size(size)}。"]
        if high:
            tips.append(f"⚠ 其中 {len(high)} 项为【高风险】项目，删除后可能无法恢复（如软件残留目录、旧系统残留）。")
        if cmds:
            tips.append(f"⚠ 其中 {len(cmds)} 项需要执行命令（DISM/powercfg/rd 等），必须以管理员身份运行。")
        if self.cfg.get("use_recycle_bin"):
            tips.append("当前策略：优先移入回收站，误删可在回收站还原。")
        else:
            tips.append("⚠ 当前策略为【永久删除】，删除后不可恢复！")
        if self.cfg.get("dry_run"):
            tips.append("当前为【演练模式】，不会真正删除任何文件。")

        # v1.1.2：高风险项目必须逐项确认后才能继续（市面工具最大的投诉就是"误删"）
        if high and not self._confirm_high_risk(high):
            return

        box = QMessageBox(self)
        box.setWindowTitle("确认清理")
        box.setIcon(QMessageBox.Warning)
        box.setText("\n".join(tips))
        box.setInformativeText("确定继续吗？建议先确认重要资料已备份。")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.button(QMessageBox.Yes).setText("开始清理")
        box.button(QMessageBox.No).setText("再看看")
        if box.exec() != QMessageBox.Yes:
            return

        self.log("开始清理...")
        self._set_busy(True, "清理中 %p%")
        self.progress.setValue(0)
        self.clean_worker = CleanWorker(self.cfg, sel)
        self.clean_worker.progress.connect(self._on_progress)
        self.clean_worker.logged.connect(self.log)
        self.clean_worker.finished.connect(self._on_clean_finished)
        self.clean_worker.start()

    def _confirm_high_risk(self, high: List[ScanItem]) -> bool:
        """高风险项二次确认：逐项列出路径，必须勾选确认才能继续。"""
        box = QMessageBox(self)
        box.setWindowTitle("高风险项目确认")
        box.setIcon(QMessageBox.Warning)
        box.setText(
            f"你勾选了 {len(high)} 个【高风险】项目。\n"
            "这些项目删除后可能导致软件不可用或数据丢失，请逐项核对后再继续。")
        detail = "\n".join(
            f"[{i + 1}] {it.risk.label} · {human_size(it.size)} · {it.name}\n      {it.path}"
            for i, it in enumerate(high[:20]))
        if len(high) > 20:
            detail += f"\n… 另有 {len(high) - 20} 项，可在主表中查看"
        box.setDetailedText(detail)
        cb = QCheckBox("我已逐项确认，这些项目可以删除")
        box.setCheckBox(cb)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.button(QMessageBox.Yes).setText("我已确认，继续")
        box.button(QMessageBox.No).setText("返回检查")
        box.button(QMessageBox.Yes).setEnabled(False)
        cb.toggled.connect(lambda on: box.button(QMessageBox.Yes).setEnabled(on))
        return box.exec() == QMessageBox.Yes

    def _on_clean_finished(self, report) -> None:
        self._pending_progress = None
        self._set_busy(False)
        self.progress.setValue(100)
        self.progress.setFormat("清理完成")
        freed = human_size(report.freed)
        self.log(f"清理完成：成功 {report.ok_count} 项，失败 {report.failed} 项，释放 {freed}")
        if report.log_file:
            self.log(f"清理清单：{report.log_file}")

        failed = [r for r in report.records if not r.ok]
        msg = f"释放空间：{freed}\n成功 {report.ok_count} 项，失败 {report.failed} 项。"
        if failed:
            preview = "\n".join(f"· {os.path.basename(r.path)}：{r.message}" for r in failed[:8])
            msg += "\n\n失败明细（前 8 条）：\n" + preview

        # 写入清理历史（可事后在【📜 清理记录】中定位备份清单）
        entry = self.history.record_from_report(report, dry_run=bool(self.cfg.get("dry_run")))
        if entry.log_file:
            msg += f"\n\n备份清单：{entry.log_file}"

        box = QMessageBox(self)
        box.setWindowTitle("清理完成")
        box.setIcon(QMessageBox.Information)
        box.setText(msg)
        btn_history = box.addButton("查看清理记录", QMessageBox.ActionRole)
        box.addButton("关闭", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is btn_history:
            self.show_history()

        # v1.3.0：① 按 id 剔除 —— 此前按 path，会把"同路径、未勾选、根本没清理"
        # 的另一类项目（如目录项与文件模式项）一起误删；
        # ② 演练模式一个都不删 —— 演练没动过磁盘，项目却从列表消失，
        # 用户会误以为已经清理掉了。
        if bool(self.cfg.get("dry_run")):
            self.log("[演练] 演练模式未删除任何文件，项目保留在列表中")
        else:
            ok_ids = {r.item_id for r in report.records if r.ok and r.item_id}
            ok_paths = {r.path for r in report.records if r.ok and not r.item_id}
            self.items = [i for i in self.items
                          if i.id not in ok_ids and i.path not in ok_paths]
        self._populate_tree(keep_selection=True)   # 停留在当前分类，不跳回"全部"
        self._apply_filter()
        self._update_space_overview()
        self._refresh_disk()
        self._flush_ui_updates()

    # ================================================================ 其它动作
    def ai_identify(self, item: ScanItem) -> None:
        """手动触发对单个目录的 AI 识别（规则库识别不出的项目）。"""
        ok, _suffix, tip = self._ai_identify_supported(item)
        if not ok:
            self.log(f"[AI] 无法识别 {item.name}：{tip}")
            return
        if self.ai_worker and self.ai_worker.isRunning():
            return
        self.log(f"开始 AI 识别：{item.name} ...")
        self._set_busy(True, "AI 识别中 %p%")
        self.progress.setValue(20)
        self.ai_worker = AIWorker(self.cfg, self.ai, item)
        self.ai_worker.progress.connect(self._on_progress)
        self.ai_worker.logged.connect(self.log)
        self.ai_worker.finished.connect(self._on_ai_finished)
        self.ai_worker.start()

    def _on_ai_finished(self, result: dict) -> None:
        item: ScanItem = result["item"]
        old_cat = result.get("old_category")
        self._pending_progress = None
        self._set_busy(False)
        self.progress.setValue(100)
        self.progress.setFormat("就绪")
        self.update_ai_status()
        if result["ok"]:
            self.log(f"[AI] {item.name} 识别完成：{item.category_label} · {item.risk.label} · 来源={item.source}")
            # 就地刷新该行：来源 / 说明 / 风险 / 分类 / 归属软件同步为 AI 结论。
            refreshed = self._refresh_row(item)
            # v1.2.0：AI 可能把项目重新归类。若分类里只有这一个项目，旧分类会变成空
            # 分类 —— 原实现不建空分类节点，于是"整个分类消失"并跳回"全部"。
            # 现在：保留原分类节点（置灰），并跟随项目切到新分类，让用户看到它去哪了。
            moved = bool(old_cat) and old_cat != item.category
            if moved:
                self.current_cat = item.category
            self._populate_tree(keep_selection=True,
                                keep_categories={old_cat} if moved else None)
            self._sync_tree_states()
            self._update_stats()
            if moved or not refreshed:
                # 该行已不在当前视图中（换了分类或原本未在视图内），需要重建表格
                self._apply_filter()
            else:
                self._on_row_selected()
            QMessageBox.information(
                self, "AI 识别完成",
                f"「{item.name}」识别完成：\n软件：{item.software or '未知'}\n"
                f"分类：{item.category_label}\n风险：{item.risk.label}\n说明：{item.reason}")
        else:
            self.log(f"[AI] 识别未完成：{result['msg']}")
            if not result.get("no_popup"):
                QMessageBox.warning(self, "AI 识别", result["msg"])
        self._flush_ui_updates()   # v1.3.0：立即落地识别日志

    def open_selected_dir(self) -> None:
        it = self._current_item()
        if not it:
            return
        target = it.path if os.path.isdir(it.path) else os.path.dirname(it.path)
        if os.path.exists(target):
            win.open_in_explorer(target)

    def _delete_item_now(self, it: ScanItem) -> None:
        """右键「立即删除此项」：必须走与批量清理完全相同的安全校验。

        v1.3.0 修复：此前该分支直接调用 fs 删除，完全绕过 Cleaner 的校验 ——
        受保护项（判定为已安装的程序目录）、危险项、系统关键路径、允许范围外
        的路径都能被一键删掉，是本工具最危险的一处缺口。
        """
        if self.clean_worker and self.clean_worker.isRunning():
            QMessageBox.information(self, "提示", "清理进行中，请清理完成后再操作")
            return
        if it.kind == ItemKind.COMMAND:
            QMessageBox.information(
                self, "提示",
                "命令类项目（DISM / 休眠 / 还原点）没有可直接删除的文件，"
                "请通过【🧹 清理选中】执行。")
            return
        ok, why = Cleaner(self.cfg).check_item(it)
        if not ok:
            QMessageBox.warning(self, "不能删除", f"{it.name}\n\n{why}")
            return
        box = QMessageBox(self)
        box.setWindowTitle("确认删除")
        box.setIcon(QMessageBox.Warning)
        box.setText(
            f"确定要【永久删除】下面这个项目吗？\n\n"
            f"{it.name} · {human_size(it.size)} · {it.risk.label}\n{it.path}\n\n"
            "该操作不走回收站，删除后无法还原。")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.button(QMessageBox.Yes).setText("永久删除")
        box.button(QMessageBox.No).setText("取消")
        if box.exec() != QMessageBox.Yes:
            return
        ok, msg = fs.remove_dir_tree(it.path) if os.path.isdir(it.path) else (
            fs.force_remove_file(it.path), "")
        if ok:
            self.log(f"已永久删除：{it.path}")
            self.items = [x for x in self.items if x.id != it.id]
            self._populate_tree(keep_selection=True)
            self._apply_filter()
            self._update_space_overview()
        else:
            QMessageBox.warning(self, "删除失败", msg or "可能被占用或权限不足")

    def _ai_identify_supported(self, item: ScanItem):
        """判断某项目能否 AI 识别，返回 (可用, 菜单后缀文本, 禁用提示)。

        不可用时菜单项会被置灰（不可点击），而不是弹出提示框。
        """
        if not (self.ai and self.ai.enabled):
            return False, "（AI 未启用）", "需先在【⚙ 设置】中开启并配置 AI"
        if item.kind != ItemKind.DIR or not (
                item.category.startswith("pf_") or item.category.startswith("appdata_")):
            return False, "", "仅 Program Files / AppData 目录支持 AI 识别"
        # v1.2.0：AI 识别与清理互斥。并行执行时两边会同时读写同一批 ScanItem，
        # 且识别完成后的整表重建会把主线程占满，正是"删除时用 AI 就卡死"的成因。
        if self.ai_worker and self.ai_worker.isRunning():
            return False, "（识别中）", "已有 AI 识别正在进行，请稍候"
        if self.clean_worker and self.clean_worker.isRunning():
            return False, "（清理中）", "清理进行中，请清理完成后再识别"
        # v1.3.0：补上与扫描的互斥（v1.2.0 漏了这一条）。扫描线程仍在往结果里
        # 追加项目，此时识别完会重建整棵树，等扫描结束再覆盖一次 —— 刚识别的
        # 项目就凭空消失了。
        if self.scan_worker and self.scan_worker.isRunning():
            return False, "（扫描中）", "扫描进行中，请扫描完成后再识别"
        return True, "", ""

    def _table_menu(self, pos) -> None:
        it = self._current_item()
        if not it:
            return
        menu = QMenu(self)
        act_open = menu.addAction("打开所在目录")
        act_copy = menu.addAction("复制路径")
        # AI 识别项始终显示：不支持 / 未启用时标灰不可点击，不再弹窗提示
        menu.addSeparator()
        ai_ok, ai_suffix, ai_tip = self._ai_identify_supported(it)
        act_ai = menu.addAction("🤖 AI 识别此目录" + ai_suffix)
        act_ai.setEnabled(ai_ok)
        if not ai_ok:
            act_ai.setToolTip(ai_tip)
        menu.addSeparator()
        act_uninstall = None
        if isinstance(it.extra, dict) and it.extra.get("uninstall_string"):
            act_uninstall = menu.addAction("启动该软件的卸载程序")
        act_exclude = menu.addAction("加入排除列表（不扫描此项）")
        act_del = menu.addAction("立即删除此项（不走回收站）")
        act = menu.exec(self.table.viewport().mapToGlobal(pos))
        if act == act_open:
            self.open_selected_dir()
        elif act == act_copy:
            QApplication.clipboard().setText(it.path)
            self.log(f"已复制路径：{it.path}")
        elif act == act_ai:
            self.ai_identify(it)
        elif act_uninstall is not None and act == act_uninstall:
            if Cleaner.open_uninstall(it):
                self.log(f"已启动卸载程序：{it.name}")
            else:
                self.log("启动卸载程序失败")
        elif act == act_exclude:
            paths = list(self.cfg.get("exclude_paths", []) or [])
            paths.append(it.path)
            self.cfg.set("exclude_paths", paths)
            self.cfg.save()
            self.items = [x for x in self.items if x.id != it.id]
            self._populate_tree(keep_selection=True)
            self._apply_filter()
            self._update_space_overview()
            self.log(f"已加入排除列表：{it.path}")
        elif act == act_del:
            self._delete_item_now(it)

    def export_report(self) -> None:
        if not self.items:
            QMessageBox.information(self, "提示", "还没有扫描结果")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出扫描报告", os.path.join(os.path.expanduser("~"), "DiskCC报告.csv"),
            "CSV 文件 (*.csv);;JSON 文件 (*.json)")
        if not path:
            return
        try:
            if path.lower().endswith(".json"):
                import json

                data = [i.to_dict() for i in self.items]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            else:
                import csv

                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    wcsv = csv.writer(f)
                    wcsv.writerow(["名称", "大小(字节)", "风险", "分类", "归属软件",
                                   "来源", "说明", "路径", "是否勾选"])
                    for i in self.items:
                        wcsv.writerow([i.name, i.size, i.risk.label, i.category_label,
                                       i.software, i.source, i.reason, i.path,
                                       "是" if i.checked else "否"])
            self.log(f"报告已导出：{path}")
            QMessageBox.information(self, "导出完成", f"已导出到：\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def show_history(self) -> None:
        HistoryDialog(self.history, self).exec()

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec():
            self._apply_theme()
            self.update_ai_status()
            self.log("设置已保存")
            if self.ai:
                self.ai.cfg = self.cfg
                self.ai.client = self.ai.client.__class__(
                    base_url=self.cfg.get("ai_base_url"),
                    api_key=self.cfg.get("ai_api_key"),
                    model=self.cfg.get("ai_model"),
                    timeout=int(self.cfg.get("ai_timeout", 60)),
                )
                self.update_ai_status()

    def show_about(self) -> None:
        QMessageBox.information(
            self, "关于 DiskCC",
            f"DiskCC v{__version__}\n\n"
            "Windows C 盘智能清理工具\n"
            "· 内置数百条规则库，离线即可识别 Program Files 归属与 AppData 目录作用\n"
            "· 可选接入 AI（OpenAI 兼容接口）识别未知目录\n"
            "· 默认只勾选安全项，支持回收站删除、备份清单与演练模式\n"
            "· 空间占用构成条：一眼看清 C 盘被哪些类别占满，点击图例直达\n"
            "· 清理记录：每次清理留痕，可随时找回备份清单\n"
            "· 高风险项目二次确认：逐项列出路径，确认后才执行\n\n"
            "免责声明：清理前请确认已备份重要数据；命令类项目（DISM/休眠/还原点）"
            "会改变系统配置，请按需谨慎执行。")

    def relaunch_admin(self) -> None:
        if win.relaunch_as_admin():
            QApplication.quit()
        else:
            QMessageBox.information(self, "提示", "提权失败，请右键程序图标选择“以管理员身份运行”。")

    def closeEvent(self, event) -> None:  # noqa: N802
        self.cfg.set("window_width", self.width())
        self.cfg.set("window_height", self.height())
        try:
            self.cfg.save()
        except Exception:
            pass
        # v1.3.0：先断开信号、停掉刷新定时器，再停线程。删除大文件 / 执行 DISM
        # 时后台线程几秒内退不出来（这里只等 2s），等它真正结束再 emit，就是往
        # 已经销毁的控件上发消息 —— 那样程序会在关闭瞬间崩溃。
        self._ui_flush_timer.stop()
        for worker_name in ("scan_worker", "clean_worker", "ai_worker"):
            worker = getattr(self, worker_name, None)
            if worker is None:
                continue
            for sig_name in ("progress", "logged", "finished"):
                sig = getattr(worker, sig_name, None)
                if sig is None:
                    continue
                try:
                    sig.disconnect()
                except Exception:
                    pass
            if worker.isRunning():
                stop = getattr(worker, "stop", None)
                if callable(stop):
                    try:
                        stop()
                    except Exception:
                        pass
                worker.wait(2000)
        super().closeEvent(event)
