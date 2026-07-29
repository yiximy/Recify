# -*- coding: utf-8 -*-
"""确认复选框：基于 MonkeyQt 的 MkCheckBox，自绘现代化勾选样式。

MkCheckBox 选中态因 Qt QSS 无法绘制矢量对号，只能显示一个蓝色方块（源码
里 `image: url(none)`），观感未完成。本组件在其之上完全接管 paintEvent，
绘制圆角描边框 + 白色对号，带悬浮高亮，符合现代 UI 规范。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from monkeyqt import MkCheckBox


# 视觉常量（现代扁平风：略大命中区 + 圆角 + 白色对号）
_BOX = 20          # 勾选框边长
_PAD = 6           # 四周留白（扩大点击命中区，也给悬浮描边留呼吸空间）
_RADIUS = 6.0      # 圆角半径

_COLOR_PRIMARY = QColor("#409eff")
_COLOR_PRIMARY_DISABLED = QColor("#a0cfff")
_COLOR_BORDER = QColor("#dcdfe6")
_COLOR_BORDER_HOVER = QColor("#409eff")
_COLOR_FILL = QColor("#ffffff")
_COLOR_FILL_DISABLED = QColor("#f5f7fa")
_COLOR_CHECK = QColor("#ffffff")


class ConfirmCheckBox(MkCheckBox):
    """自绘现代化复选框，接口与 MkCheckBox / QCheckBox 完全一致。"""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self._hover = False
        side = _BOX + _PAD * 2
        self.setFixedSize(side, side)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: D401 - 覆盖父类尺寸建议
        side = _BOX + _PAD * 2
        return QSize(side, side)

    # 整个控件区域均可点击切换（默认 QCheckBox 仅指示器区域可点）
    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        x = (self.width() - _BOX) / 2.0
        y = (self.height() - _BOX) / 2.0
        box = QRectF(x, y, _BOX, _BOX)

        checked = self.isChecked()
        enabled = self.isEnabled()

        if checked:
            fill = _COLOR_PRIMARY if enabled else _COLOR_PRIMARY_DISABLED
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(box, _RADIUS, _RADIUS)
            self._draw_check(painter, x, y)
        else:
            if not enabled:
                border = _COLOR_BORDER
                fill = _COLOR_FILL_DISABLED
            elif self._hover:
                border = _COLOR_BORDER_HOVER
                fill = _COLOR_FILL
            else:
                border = _COLOR_BORDER
                fill = _COLOR_FILL
            pen = QPen(border)
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.setBrush(fill)
            # 内缩半个线宽，避免圆角描边被裁切
            painter.drawRoundedRect(box.adjusted(0.75, 0.75, -0.75, -0.75),
                                    _RADIUS, _RADIUS)
        painter.end()

    @staticmethod
    def _draw_check(painter: QPainter, x: float, y: float):
        """绘制白色对号（两段折线，圆角笔帽，居中于勾选框）。"""
        pen = QPen(_COLOR_CHECK)
        pen.setWidthF(2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        path = QPainterPath()
        path.moveTo(x + _BOX * 0.26, y + _BOX * 0.52)
        path.lineTo(x + _BOX * 0.43, y + _BOX * 0.69)
        path.lineTo(x + _BOX * 0.74, y + _BOX * 0.33)
        painter.drawPath(path)
