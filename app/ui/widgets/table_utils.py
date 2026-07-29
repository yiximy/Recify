# -*- coding: utf-8 -*-
"""表格通用增强：像素级平滑滚动 + 统一横向滚动条外观。

QTableWidget 默认横向按「整列」滚动（ScrollPerItem），拖动或点击滚动条时
会整列跳动、观感生硬；纵向感觉更顺滑只是因为行高小、跳步不明显。改为
ScrollPerPixel 后横向与纵向一样按像素平滑滚动。同时补齐 MkTable 主题未
覆盖的横向滚动条样式，去掉两端会造成「硬跳」的箭头按钮。
"""
from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView

# 与 MkTable 主题内竖向滚动条外观一致的横向滚动条样式
_HSCROLLBAR_QSS = """
QScrollBar:horizontal {
    background: transparent;
    height: 9px;
    margin: 3px;
}
QScrollBar::handle:horizontal {
    background: #c0c4cc;
    border-radius: 4px;
    min-width: 26px;
}
QScrollBar::handle:horizontal:hover {
    background: #909399;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: transparent;
    border: none;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
    border: none;
}
"""


def enable_smooth_scroll(view: QAbstractItemView) -> None:
    """为表格/树视图启用像素级平滑滚动，并统一横向滚动条外观。

    - 横向/纵向均设为 ScrollPerPixel，消除整列/整行跳动的生硬观感。
    - 追加横向滚动条样式（MkTable 主题只定义了纵向）。

    适用于任意 QAbstractItemView（MkTable、QTreeWidget 等）。

    说明：追加的 QSS 会在样式表被整体重置时丢失，但真正决定顺滑度的
    ScrollMode 不受样式表影响，依然生效。
    """
    view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.setStyleSheet(view.styleSheet() + _HSCROLLBAR_QSS)
