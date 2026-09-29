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

    # 有效关联数与失效提示同时出现时需要的宽度（如「已关联 2 ⚠1」）
    _WIDTH = 96
    _HEIGHT = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self._linked = False
        self._auto = False
        self._dangling = 0
        self._text = "未关联"
        self.setFixedSize(self._WIDTH, self._HEIGHT)

    def set_linked(self, linked: bool, count: int = 0, auto: bool = False,
                   dangling: int = 0):
        """设置关联状态。

        Args:
            linked: 是否存在**有效**关联（对象记录存在且非 missing）
            count: 有效关联数量（只要已关联就显示具体条数）
            auto: 是否为自动关联（与手动关联视觉区分）
            dangling: 失效关联条数（对象已删除/已 missing）；>0 时以警示色
                追加「⚠N」，让用户一眼看到仍有失效关联需要清理
        """
        self._linked = linked
        self._auto = auto
        self._dangling = max(0, int(dangling or 0))
        if linked:
            prefix = "自动" if auto else "已关联"
            self._text = f"{prefix} {count}"
            if self._dangling:
                self._text += f" ⚠{self._dangling}"
        elif self._dangling:
            # 全部关联都已失效：明确标出失效条数（不再是「未关联」）
            self._text = f"失效 {self._dangling}"
        else:
            self._text = "未关联"
        self.update()

    @property
    def text(self) -> str:
        """当前徽标文本（只读，供单测/调试断言）。"""
        return self._text

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)

        if self._dangling:
            # 存在失效关联：警示黄（优先级最高，提示需要清理）
            bg = QColor("#fff8e1")
            fg = QColor("#b45309")
            border = QColor("#ffe082")
        elif self._linked and self._auto:
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

        if self._linked and self._auto and not self._dangling:
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
