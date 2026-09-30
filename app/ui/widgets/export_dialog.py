# -*- coding: utf-8 -*-
"""导出 Excel 对话框：选标签类别、未分类、报销单位、是否含明细表。

预览数据来自 ``Store.get_tag_stats()``（与导出生成共用同一份口径）；
「费用报销期间」为当前勾选类别涵盖数据的整体日期区间（只读）；
「对账行」实时展示 已确认支付总额 / 已勾选类别合计 / 未包含差额。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QVBoxLayout,
)
from monkeyqt import MkButton, MkInput, MkMessage

# 对账行文字颜色（沿用 Elegant Light 的次要文字色与警示色）
_RECONCILE_OK_COLOR = "#606266"
_RECONCILE_WARN_COLOR = "#E6A23C"


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

        self.lbl_reconcile = QLabel("")
        self.lbl_reconcile.setWordWrap(True)
        self.lbl_reconcile.setStyleSheet(
            f"color: {_RECONCILE_OK_COLOR}; font-size: 12px;"
        )
        layout.addWidget(self.lbl_reconcile)

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

        self.list_tags.itemChanged.connect(
            lambda _item: self._on_selection_changed()
        )
        self.chk_untagged.toggled.connect(
            lambda _state: self._on_selection_changed()
        )
        self._on_selection_changed()

    # ── 交互 ────────────────────────────────────────────────

    def _set_all(self, state) -> None:
        for i in range(self.list_tags.count()):
            self.list_tags.item(i).setCheckState(state)
        self._on_selection_changed()

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

    def _update_reconcile(self) -> None:
        """对账行：已确认总额 ｜ 已勾选合计 ｜ 未包含差额（实时随勾选变化）。

        已确认总额取 ``store.get_summary()["total_amount"]``（与计算金额模式
        同口径，不另算）；已勾选合计取 ``store.get_tag_stats()`` 中当前勾选类别
        （含勾选未分类时）的金额和。差额 > 0.005 显示警示色；未勾选未分类且
        存在未分类票据时，追加其张数与金额。
        """
        if not self.store:
            self.lbl_reconcile.setText("")
            return
        total = float(self.store.get_summary().get("total_amount") or 0.0)
        selected = sum(
            float(cat.get("amount") or 0.0)
            for cat in self._selected_categories()
        )
        diff = round(total - selected, 2)
        untagged = self._stats.get("untagged") or {}
        untagged_count = int(untagged.get("count") or 0)
        untagged_amount = float(untagged.get("amount") or 0.0)

        text = (f"已确认支付总额 ¥{total:.2f} ｜ "
                f"已勾选类别合计 ¥{selected:.2f} ｜ "
                f"未包含 ¥{diff:.2f}")
        if abs(diff) > 0.005:
            color = _RECONCILE_WARN_COLOR
            # 差额非零时才提示可能的来源（未分类票据未勾选）
            if not self.chk_untagged.isChecked() and untagged_count > 0:
                text += (f"（其中 未分类 {untagged_count} 张 "
                         f"¥{untagged_amount:.2f}）")
        else:
            color = _RECONCILE_OK_COLOR
            text += "，已与已确认总额一致"
        self.lbl_reconcile.setText(text)
        self.lbl_reconcile.setStyleSheet(f"color: {color}; font-size: 12px;")

    def _on_selection_changed(self) -> None:
        """勾选变化时同时刷新费用报销期间与对账行。"""
        self._update_period()
        self._update_reconcile()

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
