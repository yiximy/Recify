# -*- coding: utf-8 -*-
"""关联状态徽标组件：支持未关联 / 已关联 / 自动关联 三种状态"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from PySide6.QtWidgets import QWidget


class StatusBadge(QWidget):
    """圆角徽标，显示关联状态。

    三种状态视觉区分：
    - 未关联：灰色背景
    - 已关联（手动）：绿色背景
    - 自动关联：蓝色背景 + 虚线边框（区别于手动关联的实线绿色）

    用法：
        badge = StatusBadge()
        badge.set_linked(True, count=3)           # 手动关联
        badge.set_linked(True, count=2, auto=True) # 自动关联
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._linked = False
        self._auto = False
        self._text = "未关联"
        self.setFixedSize(78, 24)

    def set_linked(self, linked: bool, count: int = 0, auto: bool = False):
        """设置关联状态。

        Args:
            linked: 是否已关联
            count: 关联数量（>0 时显示数量）
            auto: 是否为自动关联（与手动关联视觉区分）
        """
        self._linked = linked
        self._auto = auto
        if linked:
            prefix = "自动" if auto else "已关联"
            self._text = f"{prefix} {count}" if count > 1 else prefix
        else:
            self._text = "未关联"
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)

        if self._linked and self._auto:
            # 自动关联：蓝色调，虚线边框区分于手动关联
            bg = QColor("#e8f4fd")
            fg = QColor("#1565c0")
            border = QColor("#90caf9")
        elif self._linked:
            bg = QColor("#e8f5e9")
            fg = QColor("#2e7d32")
            border = QColor("#c8e6c9")
        else:
            bg = QColor("#f5f5f5")
            fg = QColor("#909399")
            border = QColor("#e0e0e0")

        painter.setBrush(bg)

        if self._linked and self._auto:
            # 自动关联使用虚线描边
            pen = QPen(border)
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setWidthF(1.5)
            painter.setPen(pen)
        else:
            painter.setPen(border)

        painter.drawRoundedRect(rect, 10, 10)

        painter.setPen(fg)
        font = QFont("Microsoft YaHei UI", 8, QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self._text)
