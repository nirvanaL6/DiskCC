"""界面主题（QSS）。"""

DARK_QSS = """
QWidget {
    background-color: #1b1e23;
    color: #dfe4ea;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 12px;
}
QMainWindow, QDialog { background-color: #1b1e23; }

QMenuBar { background-color: #22262d; border-bottom: 1px solid #2c313a; }
QMenuBar::item:selected { background-color: #2f3540; }
QMenu { background-color: #22262d; border: 1px solid #2c313a; }
QMenu::item:selected { background-color: #3a4150; }

QToolBar {
    background-color: #22262d;
    border-bottom: 1px solid #2c313a;
    spacing: 6px;
    padding: 6px;
}
QToolBar QToolButton {
    background-color: #2b313a;
    border: 1px solid #363d47;
    border-radius: 6px;
    padding: 6px 12px;
    color: #dfe4ea;
}
QToolBar QToolButton:hover { background-color: #35404e; }
QToolBar QToolButton:pressed { background-color: #3d4a5c; }
QToolBar QToolButton:disabled { color: #6b7280; background-color: #262a31; }

QPushButton {
    background-color: #2b313a;
    border: 1px solid #363d47;
    border-radius: 6px;
    padding: 6px 14px;
}
QPushButton:hover { background-color: #35404e; }
QPushButton:pressed { background-color: #3d4a5c; }
QPushButton:disabled { color: #6b7280; background-color: #262a31; }
QPushButton#primary {
    background-color: #2f81f7; border: 1px solid #2f81f7; color: #ffffff; font-weight: bold;
}
QPushButton#primary:hover { background-color: #3a8cff; }
QPushButton#danger {
    background-color: #c0392b; border: 1px solid #c0392b; color: #ffffff; font-weight: bold;
}
QPushButton#danger:hover { background-color: #d94a3a; }

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {
    background-color: #242830;
    border: 1px solid #363d47;
    border-radius: 5px;
    padding: 5px 8px;
    selection-background-color: #2f81f7;
}
QLineEdit:focus, QTextEdit:focus { border: 1px solid #2f81f7; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView { background-color: #242830; border: 1px solid #363d47; outline: none; }
QComboBox QAbstractItemView::item { color: #dfe4ea; padding: 4px 6px; }
QComboBox QAbstractItemView::item:selected { color: #ffffff; background-color: #2f81f7; }
QComboBox QAbstractItemView::item:hover { color: #ffffff; background-color: #3a4150; }

QTreeWidget, QTableWidget {
    background-color: #20242b;
    alternate-background-color: #232830;
    border: 1px solid #2c313a;
    border-radius: 6px;
    gridline-color: #2c313a;
    outline: none;
}
QHeaderView::section {
    background-color: #262b33;
    color: #aab2bf;
    border: none;
    border-right: 1px solid #2c313a;
    border-bottom: 1px solid #2c313a;
    padding: 6px 8px;
}
QTreeWidget::item, QTableWidget::item { padding: 4px; }
QTreeWidget::item:selected, QTableWidget::item:selected { background-color: #2f3d55; color: #ffffff; }
QTreeWidget::item:hover, QTableWidget::item:hover { background-color: #262b33; }

QCheckBox::indicator { width: 15px; height: 15px; border-radius: 3px; border: 1px solid #4a5260; background: #242830; }
QCheckBox::indicator:checked { background-color: #2f81f7; border: 1px solid #2f81f7; }

QProgressBar {
    background-color: #242830; border: 1px solid #363d47; border-radius: 6px; height: 18px; text-align: center;
}
QProgressBar::chunk { background-color: #2f81f7; border-radius: 5px; }

QSplitter::handle { background-color: #2c313a; }
QStatusBar { background-color: #22262d; color: #aab2bf; }

/* 分组框：标题与边框在深色下清晰可见 */
QGroupBox {
    background-color: transparent;
    border: 1px solid #2c313a;
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
    color: #c7ced8;
    background-color: #1b1e23;
}

/* 标签页（设置对话框顶部那一排）：未选中项用浅灰文字，选中项用蓝色高亮 */
QTabWidget::pane { background-color: #1b1e23; border: 1px solid #2c313a; border-radius: 6px; }
QTabBar::tab {
    background-color: #242830;
    color: #aab2bf;
    border: 1px solid #363d47;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 7px 16px;
    margin-right: 2px;
}
QTabBar::tab:selected { background-color: #2f81f7; color: #ffffff; border: 1px solid #2f81f7; }
QTabBar::tab:!selected:hover { background-color: #2b313a; color: #dfe4ea; }
QLabel#hint { color: #f5b041; }
QLabel#ok { color: #2ecc71; }
QLabel#title { font-size: 15px; font-weight: bold; color: #eef2f7; }
QScrollBar:vertical { background: #20242b; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #3a4150; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #4a5260; }
QScrollBar:horizontal { background: #20242b; height: 10px; }
QScrollBar::handle:horizontal { background: #3a4150; border-radius: 5px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
"""

LIGHT_QSS = """
QWidget {
    background-color: #f5f6f8;
    color: #23262b;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 12px;
}
QToolBar { background-color: #eceff3; border: none; padding: 6px; spacing: 6px; }
QToolBar QToolButton {
    background-color: #ffffff; border: 1px solid #d3d8e0; border-radius: 6px; padding: 6px 12px;
}
QPushButton { background-color: #ffffff; border: 1px solid #d3d8e0; border-radius: 6px; padding: 6px 14px; }
QPushButton:hover { background-color: #eef2f7; }
QPushButton#primary { background-color: #2f81f7; color: #fff; border: 1px solid #2f81f7; font-weight: bold; }
QPushButton#danger { background-color: #c0392b; color: #fff; border: 1px solid #c0392b; font-weight: bold; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {
    background-color: #ffffff; border: 1px solid #d3d8e0; border-radius: 5px; padding: 5px 8px;
}
QTreeWidget, QTableWidget {
    background-color: #ffffff; border: 1px solid #dfe3e8; border-radius: 6px; gridline-color: #eceff3;
    alternate-background-color: #f3f5f8;
}
QGroupBox { border: 1px solid #dfe3e8; border-radius: 6px; margin-top: 14px; padding-top: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #4a5260; background-color: #f5f6f8; }
QTabWidget::pane { border: 1px solid #dfe3e8; border-radius: 6px; }
QTabBar::tab { background-color: #ffffff; color: #4a5260; border: 1px solid #dfe3e8; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; padding: 7px 16px; margin-right: 2px; }
QTabBar::tab:selected { background-color: #2f81f7; color: #ffffff; border: 1px solid #2f81f7; }
QTabBar::tab:!selected:hover { background-color: #eef2f7; color: #23262b; }
QHeaderView::section {
    background-color: #f0f2f5; color: #4a5260; border: none;
    border-right: 1px solid #e3e7ec; border-bottom: 1px solid #e3e7ec; padding: 6px 8px;
}
QProgressBar { border: 1px solid #d3d8e0; border-radius: 6px; height: 18px; text-align: center; background: #fff; }
QProgressBar::chunk { background-color: #2f81f7; border-radius: 5px; }
QStatusBar { background-color: #eceff3; }
"""


def qss(theme: str) -> str:
    return DARK_QSS if theme == "dark" else LIGHT_QSS
