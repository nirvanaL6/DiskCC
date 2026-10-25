"""轻量自绘图表：空间占用构成条（不引入 QtCharts，避免打包体积与依赖问题）。"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

# 分类配色：按占比从大到小依次取用，保证相邻色块可区分
PALETTE = [
    "#4f8cff", "#2ecc71", "#f5b041", "#e8734a", "#9b6bdf",
    "#26c6da", "#ef5da8", "#8bc34a", "#ffca28", "#78909c",
    "#5c6bc0", "#66bb6a", "#ffa726", "#ec407a", "#26a69a",
]


class SpaceBar(QWidget):
    """横向堆叠条：按分类占比着色，悬停显示明细。"""

    segmentHovered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments: List[Tuple[str, int, str]] = []   # (key, size, color)
        self.labels: Dict[str, str] = {}                 # key -> 显示名
        self._total = 0
        self._hit: List[Tuple[float, float, str, int]] = []
        self.setFixedHeight(26)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip("")

    # ---------------------------------------------------------------- 数据
    def set_data(self, segments: Sequence[Tuple[str, int, str]], labels: Dict[str, str]) -> None:
        self.segments = [s for s in segments if s[1] > 0]
        self.labels = labels
        self._total = sum(s[1] for s in self.segments)
        self._hit = []
        self.update()

    def clear(self) -> None:
        self.segments = []
        self.labels = {}
        self._total = 0
        self._hit = []
        self.update()

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            rect = self.rect().adjusted(0, 2, 0, -2)
            radius = 6.0
            path = QPainterPath()
            path.addRoundedRect(QRectF(rect), radius, radius)
            p.setClipPath(path)
            p.fillRect(rect, QColor("#2a2f3a" if self._dark() else "#e6e9ef"))

            self._hit = []
            if self._total <= 0:
                p.setPen(QColor("#8b95a5"))
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "暂无数据")
                return

            x = float(rect.left())
            w = float(rect.width())
            for key, size, color in self.segments:
                seg_w = w * (size / self._total)
                if seg_w <= 0:
                    continue
                r = QRectF(x, rect.top(), seg_w, rect.height())
                p.fillRect(r, QColor(color))
                self._hit.append((r.left(), r.right(), key, size))
                # 占比够宽才画文字，避免糊成一片
                if seg_w > 56:
                    p.setPen(QColor("#ffffff"))
                    f = QFont(p.font())
                    f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
                    p.setFont(f)
                    pct = int(round(size / self._total * 100))
                    p.drawText(r, Qt.AlignmentFlag.AlignCenter, f"{pct}%")
                x += seg_w
        finally:
            p.end()

    def _dark(self) -> bool:
        return self.palette().window().color().lightness() < 128

    # ---------------------------------------------------------------- 交互
    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        x = event.position().x() if hasattr(event, "position") else event.x()
        for left, right, key, size in self._hit:
            if left <= x <= right:
                name = self.labels.get(key, key)
                pct = size / self._total * 100 if self._total else 0
                self.setToolTip(f"{name}：{pct:.1f}%")
                return
        self.setToolTip("")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        x = event.position().x() if hasattr(event, "position") else event.x()
        for left, right, key, _size in self._hit:
            if left <= x <= right:
                self.segmentHovered.emit(key)
                return
        super().mousePressEvent(event)


class SpaceOverview(QWidget):
    """空间占用概览 = 构成条 + 可点击图例（点击跳到对应分类）。"""

    categoryClicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bar = SpaceBar(self)
        self.bar.segmentHovered.connect(self.categoryClicked)
        self.legend = QWidget(self)
        self._legend_lay = QHBoxLayout(self.legend)
        self._legend_lay.setContentsMargins(0, 0, 0, 0)
        self._legend_lay.setSpacing(10)
        self._legend_lay.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        lay.addWidget(self.bar)
        lay.addWidget(self.legend)
        self.setFixedHeight(56)
        self.hide()

    def set_data(self, segments: Sequence[Tuple[str, int, str]], labels: Dict[str, str]) -> None:
        self.bar.set_data(segments, labels)
        # 清空旧图例（保留末尾 stretch）
        while self._legend_lay.count() > 1:
            item = self._legend_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.legend.setUpdatesEnabled(False)
        for key, _size, color in self.bar.segments:
            name = labels.get(key, key)
            chip = QLabel(f"<span style='color:{color}'>■</span> {name}")
            chip.setStyleSheet("font-size:12px;")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.mousePressEvent = (                      # type: ignore[assignment]
                lambda _e, k=key: self.categoryClicked.emit(k))
            self._legend_lay.insertWidget(self._legend_lay.count() - 1, chip)
        self.legend.setUpdatesEnabled(True)
        self.show()

    def clear(self) -> None:
        self.bar.clear()
        while self._legend_lay.count() > 1:
            item = self._legend_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.hide()
