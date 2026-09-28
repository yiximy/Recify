# -*- coding: utf-8 -*-
"""日期编辑单元格：QDateEdit + 清除按钮 + 变更提交。"""
from __future__ import annotations

from PySide6.QtCore import QDate, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QHBoxLayout,
    QTableView,
    QToolButton,
    QWidget,
)


_EMPTY_DATE = QDate(1900, 1, 1)
_CELL_STYLE = """
QDateEdit {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    color: #303133;
    font-size: 13px;
    padding-left: 6px;
    padding-right: 0;
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
QDateEdit::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 26px;
    background: transparent;
    border-left: 1px solid transparent;
}
QDateEdit::down-arrow {
    width: 12px;
    height: 12px;
}
QToolButton {
    background: transparent;
    border: none;
    border-radius: 4px;
    color: #909399;
    font-size: 13px;
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
_CALENDAR_STYLE = """
QCalendarWidget QWidget#qt_calendar_navigationbar {
    min-height: 44px;
    background: #ffffff;
    border-bottom: 1px solid #dcdfe6;
}
QCalendarWidget QToolButton {
    min-height: 32px;
    padding: 0 8px;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: #303133;
    font-size: 13px;
    font-weight: 600;
}
QCalendarWidget QToolButton:hover {
    background: #ecf5ff;
    color: #409eff;
}
QCalendarWidget QToolButton:pressed {
    background: #d9ecff;
}
QCalendarWidget QSpinBox {
    min-height: 32px;
    font-size: 13px;
}
QCalendarWidget QAbstractItemView:enabled {
    min-width: 30px;
    min-height: 28px;
    background: #ffffff;
    color: #303133;
    font-size: 13px;
    outline: 0;
    selection-background-color: #409eff;
    selection-color: #ffffff;
}
QCalendarWidget QAbstractItemView:disabled {
    color: #c0c4cc;
}
QCalendarWidget QAbstractItemView::item {
    min-width: 30px;
    min-height: 28px;
    padding: 0;
}
QCalendarWidget QTableView {
    border: none;
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
        self.input.setFixedHeight(40)
        self.input.setMinimumWidth(130)
        self.input.dateChanged.connect(self._on_date_changed)
        self.input.editingFinished.connect(self._on_editing_finished)
        layout.addWidget(self.input, stretch=1)

        self.btn_clear = QToolButton()
        self.btn_clear.setText("清除")
        self.btn_clear.setToolTip("清除日期")
        self.btn_clear.setAutoRaise(True)
        self.btn_clear.setFixedHeight(40)
        self.btn_clear.setFixedWidth(48)
        self.btn_clear.clicked.connect(self.clear_date)
        layout.addWidget(self.btn_clear)

        self.setStyleSheet(_CELL_STYLE)
        self._configure_calendar_popup()

    def _configure_calendar_popup(self) -> None:
        """放大日历弹窗并保持 Elegant Light 蓝色高亮。"""
        calendar = self.input.calendarWidget()
        if calendar is None:
            return
        calendar.setMinimumSize(252, 286)
        calendar.setGridVisible(False)
        calendar.setStyleSheet(_CALENDAR_STYLE)
        today_format = QTextCharFormat()
        today_format.setForeground(QColor("#409eff"))
        today_format.setFontWeight(QFont.Weight.DemiBold)
        calendar.setDateTextFormat(QDate.currentDate(), today_format)

        view = calendar.findChild(QTableView, "qt_calendar_calendarview")
        if view is None:
            return
        view.setMinimumSize(224, 210)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        horizontal = view.horizontalHeader()
        horizontal.setMinimumSectionSize(30)
        horizontal.setDefaultSectionSize(32)
        vertical = view.verticalHeader()
        vertical.setMinimumSectionSize(28)
        vertical.setDefaultSectionSize(30)

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
