# -*- coding: utf-8 -*-
"""导出 Excel 对话框：选标签类别、未分类、报销单位、是否含明细表。

预览数据来自 ``Store.get_tag_stats()``（与导出生成共用同一份口径）；
「费用报销期间」为当前勾选类别涵盖数据的整体日期区间（只读）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QVBoxLayout,
)
from monkeyqt import MkButton, MkInput, MkMessage


class ExportDialog(QDialog):
    """导出参数对话框。"""

    def __init__(self, store, config=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.config = config
        self._stats = store.get_tag_stats() if store else {"tags": [], "untagged": None}
        self.setWindowTitle("导出 Excel")
        self.setMinimumWidth(460)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel("选择要导出的标签类别："))
        self.list_tags = QListWidget()
        self.list_tags.setMinimumHeight(170)
        for cat in self._stats["tags"]:
            item = QListWidgetItem(
                f'{cat["tag"]}  ——  {cat["count"]} 张 / ¥{cat["amount"]:,.2f}'
            )
            item.setData(Qt.ItemDataRole.UserRole, cat["tag"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)   # 默认全勾选
            self.list_tags.addItem(item)
        layout.addWidget(self.list_tags, stretch=1)

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

        self.chk_untagged = QCheckBox("包含未分类票据")
        layout.addWidget(self.chk_untagged)

        unit_row = QHBoxLayout()
        unit_row.addWidget(QLabel("报销单位："))
        default_unit = ""
        if self.config:
            default_unit = self.config.get("export_unit", "") or ""
        self.input_unit = MkInput(placeholder="报销单位（可选）")
        self.input_unit.setText(default_unit)
        unit_row.addWidget(self.input_unit, stretch=1)
        layout.addLayout(unit_row)

        self.chk_detail = QCheckBox("包含关联明细表")
        self.chk_detail.setChecked(True)
        layout.addWidget(self.chk_detail)

        self.lbl_period = QLabel("")
        self.lbl_period.setStyleSheet("color: #606266; font-size: 12px;")
        layout.addWidget(self.lbl_period)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("导出")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.list_tags.itemChanged.connect(lambda _item: self._update_period())
        self.chk_untagged.toggled.connect(lambda _state: self._update_period())
        self._update_period()

    # ── 交互 ────────────────────────────────────────────────

    def _set_all(self, state) -> None:
        for i in range(self.list_tags.count()):
            self.list_tags.item(i).setCheckState(state)
        self._update_period()

    def selected_tags(self) -> list:
        """返回勾选的标签类别名（列表顺序）。"""
        result: list = []
        for i in range(self.list_tags.count()):
            item = self.list_tags.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(item.data(Qt.ItemDataRole.UserRole))
        return result

    def _selected_categories(self) -> list:
        selected = set(self.selected_tags())
        cats = [c for c in self._stats["tags"] if c["tag"] in selected]
        if self.chk_untagged.isChecked() and self._stats.get("untagged"):
            cats.append(self._stats["untagged"])
        return cats

    def _update_period(self) -> None:
        cats = self._selected_categories()
        starts = [c["date_start"] for c in cats if c["date_start"]]
        ends = [c["date_end"] for c in cats if c["date_end"]]
        if self.store and (starts or ends):
            period = self.store.format_date_range(
                min(starts) if starts else "", max(ends) if ends else ""
            )
        else:
            period = ""
        self.lbl_period.setText(f"费用报销期间：{period or '—'}")

    def accept(self):
        if not self.selected_tags() and not self.chk_untagged.isChecked():
            MkMessage.warning(self, "请至少勾选一个标签类别或「包含未分类票据」")
            return
        if self.config:
            self.config.set("export_unit", self.input_unit.text().strip())
        super().accept()

    # ── 结果 ────────────────────────────────────────────────

    def result_params(self) -> dict:
        """返回导出参数（确定后调用）。"""
        return {
            "tags": self.selected_tags(),
            "include_untagged": self.chk_untagged.isChecked(),
            "unit": self.input_unit.text().strip(),
            "include_detail": self.chk_detail.isChecked(),
        }
