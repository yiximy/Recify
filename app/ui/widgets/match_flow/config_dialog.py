# -*- coding: utf-8 -*-
"""模块配置对话框：双击节点打开。

- 发票/支付模块（源）：名称 + 绑定编辑（同类型候选多选：单文件 + 组合整组，
  显示金额/已关联标记；已被其它模块绑定的文件禁用；组合与其成员互斥、重叠组合互斥）
- 匹配模块：名称 + 金额容差（±元，默认 0.01）+ 两侧接入摘要
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from monkeyqt import MkButton, MkInput

from .model import (
    FlowNode,
    KIND_INVOICE,
    KIND_LABELS,
    KIND_PAYMENT,
)

_DIALOG_QSS = """
QDialog { background: #ffffff; font-family: "Segoe UI", "Microsoft YaHei"; }
QLabel { color: #606266; font-size: 13px; }
QDoubleSpinBox, QLineEdit {
    border: 1px solid #dcdfe6; border-radius: 6px;
    padding: 4px 8px; background: #ffffff; color: #303133;
}
QTreeWidget {
    background: #fafbfc; border: 1px solid #e4e7ed; border-radius: 6px;
    font-size: 12px; color: #303133; outline: none;
}
QTreeWidget::item { padding: 3px 2px; }
"""

_GRAY = "#909399"
_RED = "#f56c6c"


def _fmt_amount(amount: Optional[float]) -> str:
    if amount is None:
        return "—"
    return f"¥{amount:,.2f}"


class NodeConfigDialog(QDialog):
    """节点配置弹窗（模态，parent 为流程画布对话框，保证层级正确）。"""

    def __init__(self, node: FlowNode, store, parent: Optional[QWidget] = None,
                 match_summary: str = "", usage: Optional[dict] = None):
        """Args:
            node: 被配置的 FlowNode
            store: 候选数据源（get_invoices/get_payments/get_combos/get_combo_total）
            match_summary: 匹配模块的接入摘要文本（由画布对话框计算）
            usage: {file_id: 占有者描述} —— 已被其它源模块绑定的文件（含组合成员）
        """
        super().__init__(parent)
        self._node = node
        self._store = store
        self._kind = node.kind
        self._kind_label = KIND_LABELS.get(self._kind, self._kind)
        self._match_summary = match_summary
        self._usage = dict(usage or {})
        self._combo_members: dict[str, set[str]] = {}

        self.setWindowTitle(f"配置 · {self._kind_label}模块")
        self.setModal(True)
        self.setStyleSheet(_DIALOG_QSS)
        self._build_ui()
        self._load_values()

    # ── UI ──

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        title = QLabel(f"「{self._node.name}」配置")
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #303133;")
        layout.addWidget(title)

        # 名称
        layout.addWidget(QLabel("模块名称"))
        self.input_name = MkInput(placeholder="请输入模块名称")
        self.input_name.setMinimumHeight(34)
        layout.addWidget(self.input_name)

        if self._kind in (KIND_INVOICE, KIND_PAYMENT):
            self._build_source_fields(layout)
        else:
            self._build_match_fields(layout)

        # 底部提示（冲突校验说明 / 冲突提示行）
        self.lbl_hint = QLabel("")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet(f"color: {_RED}; font-size: 12px;")
        layout.addWidget(self.lbl_hint)

        # 按钮
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()
        self.btn_cancel = MkButton("取消", type="default")
        self.btn_cancel.setAutoDefault(False)
        self.btn_cancel.clicked.connect(self.reject)
        btn_bar.addWidget(self.btn_cancel)
        self.btn_ok = MkButton("确定", type="primary")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        btn_bar.addWidget(self.btn_ok)
        layout.addLayout(btn_bar)

    def _build_source_fields(self, layout: QVBoxLayout):
        layout.addWidget(QLabel(
            "绑定文件 / 组合（可多选，双击模块可再次修改）"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.header().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree, stretch=1)

        note = QLabel("提示：组合与其成员互斥、重叠组合互斥；已被其它模块绑定的项不可选；"
                      "「已关联」仅为标记，执行时只会跳过完全相同的既有配对")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {_GRAY}; font-size: 12px;")
        layout.addWidget(note)

    def _build_match_fields(self, layout: QVBoxLayout):
        layout.addWidget(QLabel("金额误差阈值（± 元）"))
        self.spin_tolerance = QDoubleSpinBox()
        self.spin_tolerance.setRange(0.0, 10.0)
        self.spin_tolerance.setSingleStep(0.01)
        self.spin_tolerance.setDecimals(2)
        self.spin_tolerance.setValue(0.01)
        layout.addWidget(self.spin_tolerance)

        summary = QLabel(self._match_summary or "当前未接入任何发票/支付模块")
        summary.setWordWrap(True)
        summary.setStyleSheet("color: #409eff; font-size: 12px;")
        layout.addWidget(summary)

        note = QLabel("执行时：发票侧金额与支付侧金额差 ≤ 容差 的链才会批量关联；"
                      "差超容差的链会进入跳过汇总（引擎不参与重算）")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {_GRAY}; font-size: 12px;")
        layout.addWidget(note)

    # ── 填充候选（源模块）──

    def _populate_source_tree(self):
        kind = self._kind
        file_ids = set(self._node.file_ids)
        combo_ids = set(self._node.combo_ids)
        files = self._store.get_invoices() if kind == KIND_INVOICE \
            else self._store.get_payments()
        file_by_id = {f.file_id: f for f in files}

        # 只列「至少含 1 个非 missing 成员」的有效组合：空壳组合（成员文件全部
        # 缺失/已删除）不再进入候选列表——展示层过滤，与 merge 后 store 清理双保险
        combos = [
            c for c in self._store.get_combos(kind)
            if any(fid in file_by_id for fid in c.get("file_ids", []))
        ]

        # 组合成员的 file_id（单文件区排除，组合内只作子行展示）
        member_ids: set[str] = set()
        for c in combos:
            member_ids.update(c.get("file_ids", []))
            self._combo_members[c["combo_id"]] = set(c.get("file_ids", []))

        def linked(f) -> bool:
            return bool(getattr(f, "linked_payment_ids", [])
                        or getattr(f, "linked_invoice_ids", []))

        # ── 组合组 ──
        group_combo = QTreeWidgetItem(["组合（整组绑定）"])
        group_combo.setFlags(Qt.ItemFlag.ItemIsEnabled)
        group_combo.setForeground(0, QColor("#606266"))
        font = group_combo.font(0)
        font.setBold(True)
        group_combo.setFont(0, font)

        def combo_member_count(c: dict) -> int:
            return sum(1 for fid in c.get("file_ids", [])
                       if fid in file_by_id)

        combo_display = []
        for c in combos:
            members = [fid for fid in c.get("file_ids", [])
                       if fid in file_by_id]
            total = self._store.get_combo_total(c["combo_id"])
            member_linked = any(
                linked(file_by_id[fid]) for fid in members)
            blocked = bool(self._usage) and any(
                fid in self._usage for fid in c.get("file_ids", []))
            missing_n = len(c.get("file_ids", [])) - len(members)
            text = f"{c.get('name', '未命名组合')}（{combo_member_count(c)} 文件 · "
            text += f"{_fmt_amount(total)}）"
            if missing_n > 0:
                text += f" · 缺失 {missing_n} 文件"
            if member_linked:
                text += " · 已关联"
            if blocked:
                text += " · 已被其它模块绑定"
            item = QTreeWidgetItem([text])
            item.setData(0, Qt.ItemDataRole.UserRole, "combo")
            item.setData(0, Qt.ItemDataRole.UserRole + 1, c["combo_id"])
            if blocked:
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setForeground(0, QColor(_GRAY))
                item.setToolTip(0, "该组合与其它模块绑定的文件重叠，不可选")
            else:
                item.setFlags(Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    0, Qt.CheckState.Checked if c["combo_id"] in combo_ids
                    else Qt.CheckState.Unchecked)
                item.setForeground(0, QColor("#303133"))
            # 成员子行（只读说明，不可勾选）
            for fid in members:
                f = file_by_id[fid]
                amt = getattr(f.amount, "final_amount", None)
                sub = QTreeWidgetItem(
                    [f"  {getattr(f, 'file_name', '')}  {_fmt_amount(amt)}"
                     + ("  · 已关联" if linked(f) else "")])
                sub.setFlags(Qt.ItemFlag.ItemIsEnabled)
                sub.setForeground(0, QColor(_GRAY))
                item.addChild(sub)
            combo_display.append(item)
        if not combo_display:
            empty = QTreeWidgetItem(["（无组合）"])
            empty.setFlags(Qt.ItemFlag.ItemIsEnabled)
            empty.setForeground(0, QColor(_GRAY))
            group_combo.addChild(empty)
        else:
            for it in combo_display:
                group_combo.addChild(it)

        # ── 单文件组（排除组合成员）──
        group_file = QTreeWidgetItem(["单文件"])
        group_file.setFlags(Qt.ItemFlag.ItemIsEnabled)
        group_file.setForeground(0, QColor("#606266"))
        group_file.setFont(0, font)

        file_display = []
        for f in files:
            if f.file_id in member_ids:
                continue
            amt = getattr(f.amount, "final_amount", None)
            text = f"{getattr(f, 'file_name', '')}  {_fmt_amount(amt)}"
            if linked(f):
                text += "  · 已关联"
            blocked = f.file_id in self._usage
            if blocked:
                text += "  · 已被其它模块绑定"
            item = QTreeWidgetItem([text])
            item.setData(0, Qt.ItemDataRole.UserRole, "file")
            item.setData(0, Qt.ItemDataRole.UserRole + 1, f.file_id)
            if blocked:
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setForeground(0, QColor(_GRAY))
                owner = self._usage.get(f.file_id, "其它模块")
                item.setToolTip(0, f"已被模块「{owner}」绑定，不可重复选择")
            else:
                item.setFlags(Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    0, Qt.CheckState.Checked if f.file_id in file_ids
                    else Qt.CheckState.Unchecked)
                item.setForeground(0, QColor("#303133"))
            file_display.append(item)
        if not file_display:
            empty = QTreeWidgetItem(["（无可选单文件）"])
            empty.setFlags(Qt.ItemFlag.ItemIsEnabled)
            empty.setForeground(0, QColor(_GRAY))
            group_file.addChild(empty)
        else:
            for it in file_display:
                group_file.addChild(it)

        self.tree.addTopLevelItem(group_combo)
        self.tree.addTopLevelItem(group_file)
        group_combo.setExpanded(True)
        group_file.setExpanded(True)

    # ── 组合互斥校验 ──

    def _selected_combo_member_ids(self, exclude_cid: Optional[str] = None) -> set:
        """当前勾选组合的成员并集（可排除某组合，用于新勾选组合的冲突判断）。"""
        union: set[str] = set()
        root = self.tree.invisibleRootItem()
        group = root.child(0) if root.childCount() else None
        if group is None:
            return union
        for i in range(group.childCount()):
            it = group.child(i)
            if it.data(0, Qt.ItemDataRole.UserRole) != "combo":
                continue
            cid = it.data(0, Qt.ItemDataRole.UserRole + 1)
            if cid == exclude_cid:
                continue
            if it.checkState(0) == Qt.CheckState.Checked:
                union.update(self._combo_members.get(cid, set()))
        return union

    def _on_item_changed(self, item: QTreeWidgetItem, _col: int):
        if item.data(0, Qt.ItemDataRole.UserRole) != "combo":
            return
        if item.checkState(0) != Qt.CheckState.Checked:
            self.lbl_hint.setText("")
            return
        cid = item.data(0, Qt.ItemDataRole.UserRole + 1)
        members = self._combo_members.get(cid, set())
        conflict = members & self._selected_combo_member_ids(exclude_cid=cid)
        if conflict:
            item.blockSignals(True)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.blockSignals(False)
            self.lbl_hint.setText(
                "不能同时选择成员重叠的组合（组合与其成员/组合间互斥）")
        else:
            self.lbl_hint.setText("")

    # ── 取值 / 回写 ──

    def _load_values(self):
        self.input_name.setText(self._node.name)
        if self._kind in (KIND_INVOICE, KIND_PAYMENT):
            self._populate_source_tree()
        else:
            self.spin_tolerance.setValue(
                float(self._node.params.get("tolerance", 0.01)))

    def accept(self):
        name = self.input_name.text().strip()
        self._node.name = name or f"{self._kind_label}模块"
        if self._kind in (KIND_INVOICE, KIND_PAYMENT):
            file_ids: list[str] = []
            combo_ids: list[str] = []
            root = self.tree.invisibleRootItem()
            for g in range(root.childCount()):
                group = root.child(g)
                for i in range(group.childCount()):
                    it = group.child(i)
                    role = it.data(0, Qt.ItemDataRole.UserRole)
                    if role not in ("file", "combo"):
                        continue
                    if it.checkState(0) == Qt.CheckState.Checked:
                        fid = it.data(0, Qt.ItemDataRole.UserRole + 1)
                        if role == "file":
                            file_ids.append(fid)
                        else:
                            combo_ids.append(fid)
            self._node.file_ids = file_ids
            self._node.combo_ids = combo_ids
        else:
            self._node.params["tolerance"] = round(
                self.spin_tolerance.value(), 2)
        super().accept()
