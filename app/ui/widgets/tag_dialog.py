# -*- coding: utf-8 -*-
"""设置标签对话框：勾选已有标签 + 新建标签，确定后替换所选对象标签。

- 已有标签来自 ``Store.get_all_tags()``；初始勾选状态为所选对象的标签并集。
- 「新建标签」支持逗号（中英文）/空格分隔多个，添加后并入勾选列表。
- 「确定」返回勾选集合（**替换**语义），「取消」不改动任何数据。
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QVBoxLayout,
)
from monkeyqt import MkButton, MkInput

_SPLIT_RE = re.compile(r"[,，、\s]+")


class TagDialog(QDialog):
    """标签编辑对话框。"""

    def __init__(self, store, initial_tags=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("设置标签")
        self.setMinimumWidth(380)
        self._build_ui()

        checked = {str(t).strip() for t in (initial_tags or []) if str(t).strip()}
        for tag in sorted(checked):
            if not self._has_item(tag):
                self._add_item(tag, checked=True)
        for i in range(self.list_tags.count()):
            item = self.list_tags.item(i)
            if item.text() in checked:
                item.setCheckState(Qt.CheckState.Checked)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel("勾选标签（确定后替换所选对象的标签）："))

        self.list_tags = QListWidget()
        self.list_tags.setMinimumHeight(180)
        for tag in (self.store.get_all_tags() if self.store else []):
            self._add_item(tag)
        layout.addWidget(self.list_tags, stretch=1)

        new_row = QHBoxLayout()
        self.input_new = MkInput(placeholder="新标签（逗号/空格分隔多个）")
        self.input_new.returnPressed.connect(self._on_add)
        new_row.addWidget(self.input_new, stretch=1)
        self.btn_add = MkButton("添加", type="default")
        self.btn_add.clicked.connect(self._on_add)
        new_row.addWidget(self.btn_add)
        layout.addLayout(new_row)

        quick_row = QHBoxLayout()
        self.btn_all = MkButton("全选", type="default")
        self.btn_all.clicked.connect(
            lambda: self._set_all(Qt.CheckState.Checked)
        )
        self.btn_clear = MkButton("清空", type="default")
        self.btn_clear.clicked.connect(
            lambda: self._set_all(Qt.CheckState.Unchecked)
        )
        quick_row.addWidget(self.btn_all)
        quick_row.addWidget(self.btn_clear)
        quick_row.addStretch(1)
        layout.addLayout(quick_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── 列表操作 ────────────────────────────────────────────

    def _has_item(self, tag: str) -> bool:
        return any(
            self.list_tags.item(i).text() == tag
            for i in range(self.list_tags.count())
        )

    def _add_item(self, tag: str, checked: bool = False) -> None:
        item = QListWidgetItem(tag)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        )
        self.list_tags.addItem(item)

    def _set_all(self, state) -> None:
        for i in range(self.list_tags.count()):
            self.list_tags.item(i).setCheckState(state)

    def _on_add(self) -> None:
        raw = self.input_new.text() or ""
        for tag in _SPLIT_RE.split(raw):
            tag = tag.strip()
            if tag and not self._has_item(tag):
                self._add_item(tag, checked=True)
        self.input_new.clear()

    # ── 结果 ────────────────────────────────────────────────

    def selected_tags(self) -> list:
        """返回当前勾选的标签（顺序为列表顺序）。"""
        result: list = []
        for i in range(self.list_tags.count()):
            item = self.list_tags.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(item.text())
        return result
