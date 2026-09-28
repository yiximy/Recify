# -*- coding: utf-8 -*-
"""日期编辑单元格：QDateEdit + 清除按钮 + 变更提交。"""
from __future__ import annotations

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import QDateEdit, QHBoxLayout, QToolButton, QWidget


_EMPTY_DATE = QDate(1900, 1, 1)
_CELL_STYLE = """
QDateEdit {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    color: #303133;
    padding: 0 2px;
    selection-background-color: #409eff;
    selection-color: #ffffff;
}
QDateEdit:hover {
    background: #f5f7fa;
}
QDateEdit:focus {
    background: #ffffff;
    border: 1px solid #409eff;
}
QDateEdit:disabled {
    background: #f5f7fa;
    color: #909399;
}
QToolButton {
    background: transparent;
    border: none;
    border-radius: 4px;
    color: #909399;
    font-size: 12px;
    padding: 0 4px;
}
QToolButton:hover {
    background: #ecf5ff;
    color: #409eff;
}
QToolButton:pressed {
    background: #d9ecff;
}
QToolButton:disabled {
    color: #c0c4cc;
}
"""


class DateEditCell(QWidget):
    """可编辑日期单元格。

    信号：
        committed(str, str): (file_id, YYYY-MM-DD 或空字符串)
    """

    committed = Signal(str, str)

    def __init__(
        self,
        file_id: str,
        initial_date: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._file_id = file_id
        self._building = True
        self._last_committed = ""
        self._build_ui()
        self.set_date(initial_date)
        self._building = False

    def _build_ui(self) -> None:
        """构建内嵌日期编辑器和清除按钮。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(2)

        self.input = QDateEdit()
        self.input.setCalendarPopup(True)
        self.input.setDisplayFormat("yyyy-MM-dd")
        self.input.setMinimumDate(_EMPTY_DATE)
        self.input.setSpecialValueText("未设置")
        self.input.setFixedHeight(36)
        self.input.setMinimumWidth(106)
        self.input.dateChanged.connect(self._on_date_changed)
        self.input.editingFinished.connect(self._on_editing_finished)
        layout.addWidget(self.input, stretch=1)

        self.btn_clear = QToolButton()
        self.btn_clear.setText("清除")
        self.btn_clear.setToolTip("清除日期")
        self.btn_clear.setAutoRaise(True)
        self.btn_clear.setFixedHeight(36)
        self.btn_clear.setFixedWidth(42)
        self.btn_clear.clicked.connect(self.clear_date)
        layout.addWidget(self.btn_clear)

        self.setStyleSheet(_CELL_STYLE)

    def _on_date_changed(self, _date: QDate) -> None:
        """日历选择或键盘确认后提交。"""
        self._commit()

    def _on_editing_finished(self) -> None:
        """编辑结束时兜底提交。"""
        self._commit()

    def _commit(self) -> None:
        """日期发生变化时发出提交信号。"""
        if self._building:
            return
        value = self.get_date()
        if value == self._last_committed:
            return
        self._last_committed = value
        self.committed.emit(self._file_id, value)

    def set_date(self, date_iso: str) -> None:
        """设置日期且不触发提交；空值显示“未设置”。"""
        self._building = True
        parsed = QDate.fromString(date_iso or "", "yyyy-MM-dd")
        if parsed.isValid() and parsed >= self.input.minimumDate():
            self.input.setDate(parsed)
        else:
            self.input.setDate(self.input.minimumDate())
        self._last_committed = self.get_date()
        self._building = False

    def clear_date(self) -> None:
        """清除日期并提交空值。"""
        self._building = True
        self.input.setDate(self.input.minimumDate())
        self._building = False
        self._commit()

    def set_readonly(self, readonly: bool) -> None:
        """设置只读状态。"""
        self.input.setReadOnly(readonly)
        self.btn_clear.setEnabled(not readonly)

    def get_date(self) -> str:
        """返回 YYYY-MM-DD，未设置时返回空字符串。"""
        if self.input.date() == self.input.minimumDate():
            return ""
        return self.input.date().toString("yyyy-MM-dd")