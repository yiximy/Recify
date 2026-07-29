# -*- coding: utf-8 -*-
"""金额编辑单元格：MkInput + 失焦/回车提交"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout
from monkeyqt import MkInput


def _normalize_amount_text(raw: str) -> str:
    """清洗金额输入：全角转半角、去千分位逗号、去货币符号、去空白。"""
    if not raw:
        return ""
    result = []
    for ch in raw.strip():
        code = ord(ch)
        # 全角空格
        if code == 0x3000:
            continue
        # 全角字符转半角
        if 0xFF01 <= code <= 0xFF5E:
            ch = chr(code - 0xFEE0)
        # 跳过货币符号与千分位逗号
        if ch in "¥￥,， ":
            continue
        result.append(ch)
    return "".join(result)


def _parse_amount(raw: str) -> Optional[float]:
    """解析金额字符串，失败返回 None。"""
    cleaned = _normalize_amount_text(raw)
    if not cleaned:
        return None
    try:
        value = float(cleaned)
        if value < 0:
            return None
        return value
    except ValueError:
        return None


class AmountEditCell(QWidget):
    """可编辑金额单元格。

    信号：
        committed(str, object): (payment_id, float|None) 提交时发出
    """

    committed = Signal(str, object)  # payment_id, value_or_None

    def __init__(self, payment_id: str, initial_value: Optional[float] = None,
                 parent=None):
        super().__init__(parent)
        self._payment_id = payment_id
        self._building = True  # 构建期间屏蔽提交信号
        self._build_ui()

        if initial_value is not None:
            self.set_value(initial_value)
        self._building = False

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(0)

        self.input = MkInput(placeholder="输入金额")
        self.input.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # 固定行内高度：避免被表格行高挤压导致金额上下被裁切（配合页面自适应行高）
        self.input.setFixedHeight(36)
        # 收紧左右文本内边距（MkInput 默认 12+12），为较大金额腾出显示宽度
        self.input.setTextMargins(6, 0, 6, 0)
        # 足够宽度完整显示较大金额（如 999999.99）
        self.input.setMinimumWidth(120)
        self.input.editingFinished.connect(self._on_commit)
        self.input.returnPressed.connect(self._on_commit)
        layout.addWidget(self.input)

    def _on_commit(self):
        """失焦或回车时提交。"""
        if self._building:
            return
        value = _parse_amount(self.input.text())
        # 同步显示为规范格式
        if value is not None:
            self.input.setText(f"{value:.2f}")
        self.committed.emit(self._payment_id, value)

    def set_value(self, value: Optional[float]):
        """设置金额（不触发提交）。"""
        self._building = True
        if value is not None:
            self.input.setText(f"{value:.2f}")
        else:
            self.input.clear()
        self._building = False

    def set_readonly(self, readonly: bool):
        """设置只读。"""
        self.input.setReadOnly(readonly)
        if readonly:
            self.input.setStyleSheet("background-color: #f5f7fa; color: #909399;")

    def get_value(self) -> Optional[float]:
        """获取当前金额。"""
        return _parse_amount(self.input.text())
