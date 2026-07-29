# -*- coding: utf-8 -*-
"""滑动开关组件：用于「是否审阅」等二元状态切换。

自绘圆角滑动开关，支持动画过渡、启用/禁用态，与 Elegant Light 主题协调。
"""
from __future__ import annotations

from PySide6.QtCore import (
    Qt, Signal, Property, QEasingCurve, QPropertyAnimation, QPointF, QRectF,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QFont, QFontMetrics
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel


# ── 视觉常量 ──
_TRACK_WIDTH = 48
_TRACK_HEIGHT = 26
_THUMB_DIAMETER = 20
_THUMB_MARGIN = 3
_RADIUS = _TRACK_HEIGHT / 2.0

_COLOR_OFF_TRACK = QColor("#c0c4cc")
_COLOR_ON_TRACK = QColor("#409eff")
_COLOR_OFF_TRACK_DISABLED = QColor("#e4e7ed")
_COLOR_ON_TRACK_DISABLED = QColor("#a0cfff")
_COLOR_THUMB = QColor("#ffffff")
_COLOR_THUMB_SHADOW = QColor(0, 0, 0, 30)
_COLOR_LABEL = QColor("#606266")


class _ToggleThumb(QWidget):
    """滑动开关核心：圆角轨道 + 圆形滑块，自带动画。

    使用 QPropertyAnimation 驱动滑块位置，实现平滑过渡。
    """

    toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checked = False
        self._enabled = True
        self._thumb_pos = _THUMB_MARGIN  # 滑块左边缘 X 坐标
        self._anim = None
        self.setFixedSize(_TRACK_WIDTH, _TRACK_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ── 属性 ──

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if self._checked == checked:
            return
        self._checked = checked
        self._animate_thumb()
        self.update()

    checked = Property(bool, isChecked, setChecked)

    def setEnabled(self, enabled: bool):
        self._enabled = enabled
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        )
        self.update()

    # ── 动画 ──

    def _animate_thumb(self):
        target = (
            _TRACK_WIDTH - _THUMB_MARGIN - _THUMB_DIAMETER
            if self._checked
            else _THUMB_MARGIN
        )
        if self._anim is not None:
            self._anim.stop()
        self._anim = QPropertyAnimation(self, b"_thumb_pos_prop")
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(self._thumb_pos)
        self._anim.setEndValue(target)
        self._anim.valueChanged.connect(self.update)
        self._anim.start()

    def _get_thumb_pos(self) -> float:
        return self._thumb_pos

    def _set_thumb_pos(self, pos: float):
        self._thumb_pos = pos
        self.update()

    _thumb_pos_prop = Property(float, _get_thumb_pos, _set_thumb_pos)

    # ── 交互 ──

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._enabled:
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)
        super().mousePressEvent(event)

    # ── 绘制 ──

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 轨道
        if self._checked:
            track_color = _COLOR_ON_TRACK if self._enabled else _COLOR_ON_TRACK_DISABLED
        else:
            track_color = _COLOR_OFF_TRACK if self._enabled else _COLOR_OFF_TRACK_DISABLED

        track = QRectF(0, 0, _TRACK_WIDTH, _TRACK_HEIGHT)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, _RADIUS, _RADIUS)

        # 滑块阴影
        thumb_x = self._thumb_pos
        thumb_y = _THUMB_MARGIN
        shadow_rect = QRectF(
            thumb_x + 1, thumb_y + 1, _THUMB_DIAMETER, _THUMB_DIAMETER
        )
        painter.setBrush(_COLOR_THUMB_SHADOW)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(shadow_rect)

        # 滑块主体
        thumb_rect = QRectF(thumb_x, thumb_y, _THUMB_DIAMETER, _THUMB_DIAMETER)
        painter.setBrush(_COLOR_THUMB)
        painter.drawEllipse(thumb_rect)

        painter.end()


class ToggleSwitch(QWidget):
    """滑动开关组件：标签 + 滑动开关。

    用法：
        switch = ToggleSwitch("是否审阅")
        switch.toggled.connect(self._on_toggle)
    """

    toggled = Signal(bool)

    def __init__(self, label: str = "", parent=None):
        super().__init__(parent)
        self._checked = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 标签
        if label:
            self._label = QLabel(label)
            self._label.setStyleSheet(
                f"color: {_COLOR_LABEL.name()}; font-size: 13px;"
            )
            layout.addWidget(self._label)

        # 滑动开关核心
        self._thumb = _ToggleThumb()
        self._thumb.toggled.connect(self._on_thumb_toggled)
        layout.addWidget(self._thumb)

        layout.addStretch()

    def _on_thumb_toggled(self, checked: bool):
        self._checked = checked
        self.toggled.emit(checked)

    # ── 公共接口 ──

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        self._checked = checked
        self._thumb.setChecked(checked)

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self._thumb.setEnabled(enabled)
        if hasattr(self, "_label"):
            self._label.setEnabled(enabled)

    checked = Property(bool, isChecked, setChecked)
