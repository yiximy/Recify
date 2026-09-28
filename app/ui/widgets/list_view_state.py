# -*- coding: utf-8 -*-
"""文件列表树的视图状态捕获与恢复。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget


@dataclass(frozen=True)
class TreeViewState:
    """按顶层行索引记录列表位置，重命名导致 ID 变化后仍可恢复。"""

    current_top_index: Optional[int]
    scroll_value: int
    expanded_top_indices: frozenset[int]


def capture_tree_view_state(tree: QTreeWidget) -> TreeViewState:
    """捕获当前顶层行、垂直滚动值和顶层展开状态。"""
    current = tree.currentItem()
    while current is not None and current.parent() is not None:
        current = current.parent()
    current_index = (
        tree.indexOfTopLevelItem(current) if current is not None else -1
    )
    expanded = frozenset(
        index
        for index in range(tree.topLevelItemCount())
        if tree.topLevelItem(index).isExpanded()
    )
    return TreeViewState(
        current_top_index=current_index if current_index >= 0 else None,
        scroll_value=tree.verticalScrollBar().value(),
        expanded_top_indices=expanded,
    )


def _is_visible_file_item(item) -> bool:
    """顶层行是否为可选中的可见文件行。

    判据 = 序号列带 file_id（即 file_list_panel 的 ROLE_FILE_ID，
    其值恰为 Qt.ItemDataRole.UserRole；组合父行存的是 ROLE_COMBO_ID，故被排除）。
    """
    return (
        item is not None
        and not item.isHidden()
        and bool(item.data(0, Qt.ItemDataRole.UserRole))
    )


def restore_tree_view_state(
    tree: QTreeWidget,
    state: Optional[TreeViewState],
    *,
    advance: bool = False,
) -> None:
    """重建列表后恢复展开项、目标和滚动位置。"""
    if state is None or tree.topLevelItemCount() == 0:
        return

    for index in range(tree.topLevelItemCount()):
        tree.topLevelItem(index).setExpanded(
            index in state.expanded_top_indices
        )

    if state.current_top_index is not None:
        count = tree.topLevelItemCount()
        captured_index = max(0, min(state.current_top_index, count - 1))
        if advance:
            # 顺延到下一个可见文件行；隐藏行和组合父行都不能成为下次操作目标。
            target = next(
                (
                    tree.topLevelItem(index)
                    for index in range(captured_index + 1, count)
                    if _is_visible_file_item(tree.topLevelItem(index))
                ),
                None,
            )
            if target is None:
                captured = tree.topLevelItem(captured_index)
                if _is_visible_file_item(captured):
                    target = captured
            if target is not None:
                tree.setCurrentItem(target)
        else:
            target = tree.topLevelItem(captured_index)
            if not target.isHidden():
                tree.setCurrentItem(target)

    # 最后恢复滚动值，避免 setCurrentItem 的自动滚动覆盖原位置。
    tree.doItemsLayout()
    tree.verticalScrollBar().setValue(state.scroll_value)
