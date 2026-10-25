"""设置对话框：AI 配置 / 扫描选项 / 清理策略 / 界面。"""

from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..ai.client import ChatClient
from ..config import DEFAULT_AI_PRESETS


class _AITestThread(QThread):
    """后台线程执行 AI 连接测试，避免阻塞 GUI 线程（v1.3.1 修复）。"""
    done = Signal(bool, str)

    def __init__(self, client: ChatClient, parent=None):
        super().__init__(parent)
        self._client = client

    def run(self) -> None:
        ok, msg = self._client.test_connection()
        self.done.emit(ok, msg)


class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("设置")
        self.resize(620, 560)
        self._fields: Dict[str, QWidget] = {}
        self._build()

    # ---------------------------------------------------------------- 构建
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._ai_tab(), "AI 识别")
        tabs.addTab(self._scan_tab(), "扫描选项")
        tabs.addTab(self._clean_tab(), "清理策略")
        tabs.addTab(self._ui_tab(), "界面")
        layout.addWidget(tabs)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Save).setText("保存")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ---------------------------------------------------------------- AI
    def _ai_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        box = QGroupBox("AI 接口（OpenAI 兼容格式）")
        form = QFormLayout(box)

        enable = QCheckBox("启用 AI 增强识别（未启用时仅使用内置规则库）")
        enable.setChecked(bool(self.cfg.get("ai_enabled")))
        form.addRow(enable)
        self._fields["ai_enabled"] = enable

        preset = QComboBox()
        preset.addItem("自定义 / 手动填写", "")
        for p in DEFAULT_AI_PRESETS:
            preset.addItem(p["name"], p)
        current_url = str(self.cfg.get("ai_base_url"))
        for i in range(preset.count()):
            data = preset.itemData(i)
            if data and data.get("base_url") == current_url:
                preset.setCurrentIndex(i)
                break
        form.addRow("服务商预设", preset)

        def apply_preset(_idx: int) -> None:
            data = preset.currentData()
            if not data:
                return
            self._fields["ai_base_url"].setText(data["base_url"])
            self._fields["ai_model"].setText(data["model"])

        preset.currentIndexChanged.connect(apply_preset)

        base_url = QLineEdit(current_url)
        base_url.setPlaceholderText("https://api.deepseek.com/v1")
        form.addRow("Base URL", base_url)
        self._fields["ai_base_url"] = base_url

        key = QLineEdit(str(self.cfg.get("ai_api_key", "")))
        key.setEchoMode(QLineEdit.Password)
        key.setPlaceholderText("sk-...（本地 Ollama 可留空）")
        form.addRow("API Key", key)
        self._fields["ai_api_key"] = key

        model = QLineEdit(str(self.cfg.get("ai_model", "")))
        form.addRow("模型", model)
        self._fields["ai_model"] = model

        timeout = QSpinBox()
        timeout.setRange(5, 300)
        timeout.setValue(int(self.cfg.get("ai_timeout", 60)))
        form.addRow("超时（秒）", timeout)
        self._fields["ai_timeout"] = timeout

        batch = QSpinBox()
        batch.setRange(1, 60)
        batch.setValue(int(self.cfg.get("ai_batch_size", 15)))
        form.addRow("每批条数", batch)
        self._fields["ai_batch_size"] = batch

        conc = QSpinBox()
        conc.setRange(1, 8)
        conc.setValue(int(self.cfg.get("ai_concurrency", 3)))
        form.addRow("并发请求数", conc)
        self._fields["ai_concurrency"] = conc

        cache_days = QSpinBox()
        cache_days.setRange(0, 365)
        cache_days.setValue(int(self.cfg.get("ai_cache_days", 30)))
        form.addRow("结果缓存天数（0=不缓存）", cache_days)
        self._fields["ai_cache_days"] = cache_days

        only_unknown = QCheckBox("只对规则库无法识别的目录调用 AI（省钱、更快）")
        only_unknown.setChecked(bool(self.cfg.get("ai_only_unknown")))
        form.addRow(only_unknown)
        self._fields["ai_only_unknown"] = only_unknown

        test_btn = QPushButton("测试连接")
        self._fields["ai_test_btn"] = test_btn
        self._test_label = QLabel("")
        self._test_label.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(test_btn)
        row.addWidget(self._test_label, 1)
        form.addRow("", self._wrap(row))
        test_btn.clicked.connect(self._test_ai)

        lay.addWidget(box)

        tip = QLabel(
            "说明：AI 仅用于识别 Program Files 目录归属与 AppData 目录作用，"
            "上传的内容只有目录名、大小、子目录名与可执行文件名等元信息，不包含任何文件内容。\n"
            "未配置 AI 时，程序会使用内置规则库（数百条软件映射与缓存目录规则）完成识别，功能依然完整。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8b95a5;")
        lay.addWidget(tip)
        lay.addStretch(1)
        return w

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def _test_ai(self) -> None:
        client = ChatClient(
            base_url=self._fields["ai_base_url"].text().strip(),
            api_key=self._fields["ai_api_key"].text().strip(),
            model=self._fields["ai_model"].text().strip(),
            timeout=int(self._fields["ai_timeout"].value()),
        )
        # v1.3.1 修复：改为后台线程测试，测试期间禁用按钮，界面不再卡死
        if getattr(self, "_test_thread", None) and self._test_thread.isRunning():
            return
        btn = self._fields.get("ai_test_btn")
        if btn is not None:
            btn.setEnabled(False)
        self._test_label.setText("正在测试...")
        self._test_thread = _AITestThread(client, self)
        self._test_thread.done.connect(self._on_ai_test_done)
        self._test_thread.start()

    def _on_ai_test_done(self, ok: bool, msg: str) -> None:
        btn = self._fields.get("ai_test_btn")
        if btn is not None:
            btn.setEnabled(True)
        self._test_label.setText(("✅ " if ok else "❌ ") + msg)
        self._test_label.setStyleSheet("color:#2ecc71;" if ok else "color:#e74c3c;")
        self._test_thread.deleteLater()
        self._test_thread = None

    def closeEvent(self, event) -> None:  # noqa: N802
        # 关闭时若测试仍在进行，短暂等待后台线程结束，避免销毁后回调崩溃
        th = getattr(self, "_test_thread", None)
        if th is not None and th.isRunning():
            th.wait(5000)
        super().closeEvent(event)

    # ---------------------------------------------------------------- 扫描
    def _scan_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        box = QGroupBox("扫描范围")
        form = QFormLayout(box)

        flags: List[tuple] = [
            ("scan_system_junk", "系统垃圾与临时文件"),
            ("scan_windows_update", "Windows 更新与系统组件"),
            ("scan_browsers", "浏览器缓存"),
            ("scan_devtools", "开发工具缓存"),
            ("scan_app_cache", "常用软件缓存"),
            ("scan_program_files", "Program Files 软件识别"),
            ("scan_appdata", "AppData 目录分析"),
            ("scan_empty_dirs", "空目录"),
            ("scan_bad_shortcuts", "失效快捷方式"),
            ("scan_large_files", "大文件（较慢）"),
            ("scan_duplicates", "重复文件（很慢）"),
        ]
        for key, label in flags:
            cb = QCheckBox(label)
            cb.setChecked(bool(self.cfg.get(key)))
            form.addRow(cb)
            self._fields[key] = cb

        parallel = QCheckBox("并行扫描（同时扫描各类目录，明显提速）")
        parallel.setChecked(bool(self.cfg.get("scan_parallel", True)))
        parallel.setToolTip("扫描以等待磁盘 I/O 为主，并行可显著缩短总耗时；"
                            "机械硬盘上收益最大。若遇到异常可关闭，将退回逐个扫描。")
        form.addRow(parallel)
        self._fields["scan_parallel"] = parallel

        min_size = QDoubleSpinBox()
        min_size.setRange(0.0, 1024.0)
        min_size.setDecimals(1)
        min_size.setValue(float(self.cfg.get("min_size_mb", 1.0)))
        form.addRow("忽略小于（MB）的项目", min_size)
        self._fields["min_size_mb"] = min_size

        idle = QSpinBox()
        idle.setRange(7, 3650)
        idle.setValue(int(self.cfg.get("idle_days", 90)))
        form.addRow("超过（天）未修改视为长期未使用", idle)
        self._fields["idle_days"] = idle

        depth = QSpinBox()
        depth.setRange(1, 6)
        depth.setValue(int(self.cfg.get("max_depth_appdata", 3)))
        form.addRow("AppData 分析深度", depth)
        self._fields["max_depth_appdata"] = depth

        large = QSpinBox()
        large.setRange(50, 100000)
        large.setValue(int(self.cfg.get("large_file_mb", 500)))
        form.addRow("大文件阈值（MB）", large)
        self._fields["large_file_mb"] = large

        lay.addWidget(box)

        box2 = QGroupBox("重复文件扫描（性能保护）")
        form2 = QFormLayout(box2)
        dup_min = QSpinBox()
        dup_min.setRange(1, 1024)
        dup_min.setValue(int(self.cfg.get("dup_min_size_mb", 1)))
        form2.addRow("小于（MB）的文件不参与判定", dup_min)
        self._fields["dup_min_size_mb"] = dup_min

        dup_max = QSpinBox()
        dup_max.setRange(64, 102400)
        dup_max.setValue(int(self.cfg.get("dup_max_file_mb", 512)))
        form2.addRow("单文件超过（MB）直接跳过", dup_max)
        self._fields["dup_max_file_mb"] = dup_max

        dup_budget = QSpinBox()
        dup_budget.setRange(128, 102400)
        dup_budget.setValue(int(self.cfg.get("dup_budget_mb", 2048)))
        form2.addRow("单次扫描哈希总预算（MB）", dup_budget)
        self._fields["dup_budget_mb"] = dup_budget

        tip = QLabel("全文哈希对大文件很慢，默认只校验 ≤512MB 的文件且总哈希量不超过 2GB；"
                     "想要更彻底可以适当调大，扫描时间会相应变长。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8b95a5;")
        form2.addRow("", tip)
        lay.addWidget(box2)

        lay.addStretch(1)
        return w

    # ---------------------------------------------------------------- 清理
    def _clean_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        box = QGroupBox("清理方式")
        form = QFormLayout(box)

        recycle = QCheckBox("优先移入回收站（可还原，推荐）")
        recycle.setChecked(bool(self.cfg.get("use_recycle_bin")))
        form.addRow(recycle)
        self._fields["use_recycle_bin"] = recycle

        backup = QCheckBox("清理前生成备份清单（写入程序数据目录）")
        backup.setChecked(bool(self.cfg.get("create_backup_list")))
        form.addRow(backup)
        self._fields["create_backup_list"] = backup

        dry = QCheckBox("演练模式（只报告不删除）")
        dry.setChecked(bool(self.cfg.get("dry_run")))
        form.addRow(dry)
        self._fields["dry_run"] = dry

        lay.addWidget(box)

        box2 = QGroupBox("排除路径（每行一个，扫描时将跳过）")
        lay2 = QVBoxLayout(box2)
        excludes = QPlainTextEdit()
        excludes.setPlainText("\n".join(self.cfg.get("exclude_paths", []) or []))
        excludes.setPlaceholderText("C:\\Users\\你的用户名\\AppData\\Local\\某个不想动的目录")
        lay2.addWidget(excludes)
        self._fields["exclude_paths"] = excludes

        row = QHBoxLayout()
        btn_clear_ex = QPushButton("清空排除列表")
        btn_dedup = QPushButton("去重并排序")
        row.addWidget(btn_clear_ex)
        row.addWidget(btn_dedup)
        row.addStretch(1)
        lay2.addLayout(row)
        btn_clear_ex.clicked.connect(lambda: excludes.setPlainText(""))
        btn_dedup.clicked.connect(
            lambda: excludes.setPlainText("\n".join(
                sorted({x.strip() for x in excludes.toPlainText().splitlines() if x.strip()}))))

        tip2 = QLabel("也可以在主表右键某项目 →【加入排除列表（不扫描此项）】快速添加。")
        tip2.setWordWrap(True)
        tip2.setStyleSheet("color:#8b95a5;")
        lay2.addWidget(tip2)
        lay.addWidget(box2, 1)
        return w

    # ---------------------------------------------------------------- 界面
    def _ui_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        box = QGroupBox("外观")
        form = QFormLayout(box)
        theme = QComboBox()
        theme.addItem("深色", "dark")
        theme.addItem("浅色", "light")
        idx = theme.findData(self.cfg.get("theme", "dark"))
        theme.setCurrentIndex(max(0, idx))
        form.addRow("主题（重启后生效）", theme)
        self._fields["theme"] = theme
        lay.addWidget(box)
        lay.addStretch(1)
        return w

    # ---------------------------------------------------------------- 保存
    def _save(self) -> None:
        for key, widget in self._fields.items():
            if isinstance(widget, QCheckBox):
                self.cfg.set(key, widget.isChecked())
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                self.cfg.set(key, widget.value())
            elif isinstance(widget, QLineEdit):
                self.cfg.set(key, widget.text().strip())
            elif isinstance(widget, QPlainTextEdit):
                self.cfg.set(key, [x.strip() for x in widget.toPlainText().splitlines() if x.strip()])
            elif isinstance(widget, QComboBox):
                self.cfg.set(key, widget.currentData())
        try:
            self.cfg.save()
        except Exception:
            pass
        self.accept()
