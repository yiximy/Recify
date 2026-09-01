# -*- coding: utf-8 -*-
"""自动比对审阅对话框：左右「关联组」容器，按行对齐、可拖动换组、同步滚动。

每一行是一个「关联组N」：左侧组放发票（可多个），右侧组放支付记录（可多个）。
- 即使只有一个关联文件也用组容器包裹；组默认展开。
- 文件可在同侧组间拖拽换组；空组在确定前保留。
- 右键组内文件：「取消关联」（移出本组）/「添加关联」（从当前候选池选同类型文件加入）。
- 两侧列表纵向滚动同步。
- 「确定」按组（行）对齐两两关联，空组视为无关联；「取消」无任何关联变更。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QCursor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from monkeyqt import MkButton, MkMessage

# QTreeWidgetItem 自定义数据角色
ROLE_FILE_ID = Qt.ItemDataRole.UserRole         # 组内文件行：文件 file_id
ROLE_GROUP_NAME = Qt.ItemDataRole.UserRole + 1    # 组标题（含序号徽章，如「① 关联组1」）
ROLE_GROUP_COLOR = Qt.ItemDataRole.UserRole + 2   # 组合父行：同色分组背景色
ROLE_GROUP_ACCENT = Qt.ItemDataRole.UserRole + 3  # 组合父行：同色分组强调色

# 同色分组调色板（Elegant Light 语义色）：背景 / 强调色，按组索引循环。
# 左右两树同索引组使用同一组颜色，配合同步滚动形成明确的「左右对齐连接」。
_GROUP_PALETTE_BG = [
    QColor("#ecf5ff"),  # 蓝
    QColor("#f0f9eb"),  # 绿
    QColor("#fdf6ec"),  # 橙
    QColor("#fef0f0"),  # 红
    QColor("#f4f4f5"),  # 灰
]
_GROUP_PALETTE_ACCENT = [
    QColor("#409eff"),
    QColor("#67c23a"),
    QColor("#e6a23c"),
    QColor("#f56c6c"),
    QColor("#909399"),
]
_GROUP_ACCENT_WIDTH = 4          # 组合父行左侧强调条宽度
_GROUP_BADGES = "①②③④⑤⑥⑦⑧⑨⑩"  # 序号徽章（1~10）

_TREE_QSS = """
QTreeWidget {
    background: #ffffff;
    color: #303133;
    border: 1px solid #e4e7ed;
    border-radius: 6px;
    outline: none;
    font-family: "Segoe UI", "Microsoft YaHei";
    font-size: 13px;
}
QTreeWidget::item {
    background: transparent;
    border-bottom: 1px solid #ebeef5;
    padding: 6px 4px;
}
QTreeWidget::item:hover {
    background: #f5f7fa;
}
QTreeWidget::item:selected {
    background: #409eff;
    color: #ffffff;
}
QScrollBar:vertical {
    background: transparent;
    width: 9px;
    margin: 3px;
}
QScrollBar::handle:vertical {
    background: #c0c4cc;
    border-radius: 4px;
    min-height: 26px;
}
QScrollBar::handle:vertical:hover {
    background: #909399;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
    border: none;
    height: 0px;
}
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

_MENU_QSS = """
QMenu {
    background: #ffffff;
    border: 1px solid #e4e7ed;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 18px;
    border-radius: 4px;
    color: #303133;
    font-size: 13px;
}
QMenu::item:selected {
    background: #ecf5ff;
    color: #409eff;
}
"""

_DIALOG_QSS = """
QDialog {
    background: #ffffff;
    font-family: "Segoe UI", "Microsoft YaHei";
}
QLabel {
    color: #606266;
}
"""


class _GroupTree(QTreeWidget):
    """关联组树：顶层=「关联组N」（默认展开、不可拖动、可接收 drop），子项=组内文件。

    文件子项可拖拽到同侧其他组（换组）；拖放后通过 on_groups_changed 回调
    刷新组标题（空组标记「（空）」）。拖拽时靠近顶部/底部边缘自动滚动；
    拖放后归一化结构，保证始终为「组合父行 → 组内文件」两层。
    """

    _SCROLL_MARGIN = 28       # 触发自动滚动的边缘像素距离
    _SCROLL_INTERVAL = 60     # 自动滚动定时器间隔（毫秒）

    def __init__(self, on_groups_changed=None, parent=None):
        super().__init__(parent)
        self.on_groups_changed = on_groups_changed
        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setIndentation(16)
        self.setExpandsOnDoubleClick(True)
        self.setUniformRowHeights(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setStyleSheet(_TREE_QSS)
        # 拖拽自动滚动：进入拖拽时启动，离开/落点停止
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(self._SCROLL_INTERVAL)
        self._scroll_timer.timeout.connect(self._auto_scroll_step)

    def drawRow(self, painter, option, index):
        """组合父行整行填充同色分组背景 + 左侧同色强调条（左右两树同索引同色）。"""
        item = self.itemFromIndex(index)
        if item is not None and item.parent() is None:
            color = item.data(0, ROLE_GROUP_COLOR)
            accent = item.data(0, ROLE_GROUP_ACCENT)
            if color is not None:
                painter.fillRect(option.rect, color)
            super().drawRow(painter, option, index)
            if accent is not None:
                bar = QRect(option.rect.left(), option.rect.top(),
                            _GROUP_ACCENT_WIDTH, option.rect.height())
                painter.fillRect(bar, accent)
            return
        super().drawRow(painter, option, index)

    def dragEnterEvent(self, event):
        super().dragEnterEvent(event)
        if event.isAccepted():
            self._scroll_timer.start()

    def dragMoveEvent(self, event):
        super().dragMoveEvent(event)
        if not event.isAccepted():
            return
        indicator = self.dropIndicatorPosition()
        target = self.itemAt(event.position().toPoint())
        if indicator == QAbstractItemView.DropIndicatorPosition.OnViewport:
            # 空白区不放行：避免产生顶层文件行，破坏「组 → 文件」两层结构
            event.ignore()
        elif indicator == QAbstractItemView.DropIndicatorPosition.OnItem:
            # 仅允许落入组合父行；落点是文件行会形成嵌套，拒绝
            if target is None or target.parent() is not None:
                event.ignore()
        else:
            # Above/Below：仅允许组内文件之间的重排；落在组合父行会变成顶层文件行
            if target is None or target.parent() is None:
                event.ignore()
        if event.isAccepted():
            self._auto_scroll_step()

    def dragLeaveEvent(self, event):
        self._scroll_timer.stop()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._scroll_timer.stop()
        super().dropEvent(event)
        self._normalize_tree()
        if self.on_groups_changed:
            self.on_groups_changed()

    # ── 拖拽自动滚动 ────────────────────────────────────

    def _auto_scroll_step(self):
        """按鼠标距顶部/底部边缘的距离成比例滚动（越靠近边缘越快）。"""
        if not self.viewport().underMouse():
            return
        pos = self.viewport().mapFromGlobal(QCursor.pos())
        rect = self.viewport().rect()
        if not rect.contains(pos):
            return
        margin = self._SCROLL_MARGIN
        speed = 0
        if pos.y() < rect.top() + margin:
            speed = -((margin - (pos.y() - rect.top())) // 2) - 1
        elif pos.y() > rect.bottom() - margin:
            speed = ((pos.y() - (rect.bottom() - margin)) // 2) + 1
        if speed:
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() + speed
            )

    # ── 结构归一化 ──────────────────────────────────────

    def _normalize_tree(self):
        """保证「组合父行 → 组内文件」两层：所有后代文件上提为组直接子行。"""
        for i in range(self.topLevelItemCount()):
            group = self.topLevelItem(i)
            if group.data(0, ROLE_GROUP_NAME) is None:
                continue
            files: list[QTreeWidgetItem] = []

            def collect(item):
                for j in range(item.childCount()):
                    child = item.child(j)
                    if child.data(0, ROLE_FILE_ID):
                        files.append(child)
                    collect(child)

            collect(group)
            group.takeChildren()
            for child in files:
                # 拍平自身子节点：确保每个文件行都是叶节点（两层结构）
                child.takeChildren()
                group.addChild(child)


class AutoMatchDialog(QDialog):
    """自动比对审阅二级界面（「关联组」容器模型）。"""

    def __init__(self, matches: list[dict], store=None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._matches = matches
        self._store = store
        self._syncing_scroll = False
        self._rows = self._build_rows(matches)

        self.setWindowTitle("自动比对审阅")
        self.setModal(True)
        self.resize(1040, 620)
        self.setMinimumSize(860, 500)
        self.setStyleSheet(_DIALOG_QSS)
        self._build_ui()
        self._populate()

    # ── 数据准备 ──────────────────────────────────────────

    def _build_rows(self, matches: list[dict]) -> list[dict]:
        """每个匹配 → 一个关联组行（左右各一组 id）。"""
        return [
            {
                "invoice_ids": list(m.get("invoice_ids", [])),
                "payment_ids": list(m.get("payment_ids", [])),
            }
            for m in matches
        ]

    def _resolve_file(self, kind: str, file_id: str) -> tuple[str, Optional[float]]:
        """返回 (文件名, 金额)，解析失败时回退占位。"""
        if self._store:
            f = (self._store.get_invoice(file_id) if kind == "invoice"
                 else self._store.get_payment(file_id))
            if f:
                amt = f.amount.final_amount if f.amount else None
                return f.file_name, amt
        return "未知文件", None

    # ── UI 构建 ──────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("自动比对审阅")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #303133;")
        layout.addWidget(title)

        hint = QLabel("拖动文件可调整关联组；右键组内文件可增删成员；确定按组建立关联，空组不关联。")
        hint.setStyleSheet("font-size: 12px; color: #909399;")
        layout.addWidget(hint)

        lists_layout = QHBoxLayout()
        lists_layout.setSpacing(12)

        invoice_box = QVBoxLayout()
        invoice_box.setSpacing(6)
        invoice_label = QLabel("发票文件")
        invoice_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        invoice_box.addWidget(invoice_label)
        self._left_tree = _GroupTree(on_groups_changed=self._refresh_all_group_titles)
        self._left_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._left_tree.customContextMenuRequested.connect(
            lambda pos: self._on_group_context(self._left_tree, "invoice", pos)
        )
        invoice_box.addWidget(self._left_tree, stretch=1)
        lists_layout.addLayout(invoice_box, stretch=1)

        payment_box = QVBoxLayout()
        payment_box.setSpacing(6)
        payment_label = QLabel("支付记录")
        payment_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        payment_box.addWidget(payment_label)
        self._right_tree = _GroupTree(on_groups_changed=self._refresh_all_group_titles)
        self._right_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._right_tree.customContextMenuRequested.connect(
            lambda pos: self._on_group_context(self._right_tree, "payment", pos)
        )
        payment_box.addWidget(self._right_tree, stretch=1)
        lists_layout.addLayout(payment_box, stretch=1)

        layout.addLayout(lists_layout, stretch=1)

        # 两侧纵向滚动同步
        self._left_tree.verticalScrollBar().valueChanged.connect(
            lambda v: self._sync_scroll("right", v)
        )
        self._right_tree.verticalScrollBar().valueChanged.connect(
            lambda v: self._sync_scroll("left", v)
        )

        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)
        btn_bar.addStretch()

        self.btn_cancel = MkButton("取消", type="default")
        self.btn_cancel.clicked.connect(self.reject)
        btn_bar.addWidget(self.btn_cancel)

        self.btn_ok = MkButton("确定", type="primary")
        self.btn_ok.clicked.connect(self.accept)
        btn_bar.addWidget(self.btn_ok)

        layout.addLayout(btn_bar)

    # ── 填充 ────────────────────────────────────────────

    def _populate(self):
        """按候选行填充左右组树：一行 = 一个关联组（即使单文件也包组）。"""
        for idx, row in enumerate(self._rows, start=1):
            self._add_group(self._left_tree, idx, row["invoice_ids"], "invoice")
            self._add_group(self._right_tree, idx, row["payment_ids"], "payment")

    def _add_group(self, tree: _GroupTree, idx: int, file_ids: list[str],
                   kind: str):
        """向指定树添加一个「关联组N」及组内文件。"""
        base_name = f"关联组{idx}"
        badge = _GROUP_BADGES[idx - 1] if idx <= len(_GROUP_BADGES) else str(idx)
        display = f"{badge} {base_name}"
        group = QTreeWidgetItem([display])
        group.setData(0, ROLE_GROUP_NAME, display)
        color_idx = (idx - 1) % len(_GROUP_PALETTE_BG)
        group.setData(0, ROLE_GROUP_COLOR, _GROUP_PALETTE_BG[color_idx])
        group.setData(0, ROLE_GROUP_ACCENT, _GROUP_PALETTE_ACCENT[color_idx])
        group.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        bold = QFont()
        bold.setBold(True)
        group.setFont(0, bold)
        group.setForeground(0, QBrush(_GROUP_PALETTE_ACCENT[color_idx]))
        tree.addTopLevelItem(group)
        for fid in file_ids:
            name, amt = self._resolve_file(kind, fid)
            group.addChild(self._make_file_item(fid, name, amt))
        group.setExpanded(True)
        self._refresh_group_title(group)

    @staticmethod
    def _make_file_item(file_id: str, name: str,
                        amount: Optional[float]) -> QTreeWidgetItem:
        """构造组内文件行：🔗 文件名 ｜ ¥ 金额。"""
        text = f"🔗 {name}"
        if amount is not None:
            text += f" ｜ ¥ {amount:,.2f}"
        item = QTreeWidgetItem([text])
        item.setData(0, ROLE_FILE_ID, file_id)
        item.setToolTip(0, text)
        return item

    def _refresh_group_title(self, group: QTreeWidgetItem):
        """空组标记「（空）」，非空恢复基名。"""
        base = group.data(0, ROLE_GROUP_NAME) or "关联组"
        group.setText(0, base if group.childCount() > 0 else f"{base}（空）")

    def _refresh_all_group_titles(self):
        for tree in (self._left_tree, self._right_tree):
            for i in range(tree.topLevelItemCount()):
                self._refresh_group_title(tree.topLevelItem(i))

    # ── 右键增删组内文件 ─────────────────────────────────

    def _on_group_context(self, tree: _GroupTree, kind: str, pos):
        item = tree.itemAt(pos)
        if item is None:
            return
        if item.parent() is None:
            # 组合父行（顶层项）：提供「添加关联」（将文件加入该组合）
            menu = QMenu(tree)
            menu.setStyleSheet(_MENU_QSS)
            act_add = menu.addAction("添加关联")
            selected = menu.exec(tree.viewport().mapToGlobal(pos))
            if selected is act_add:
                self._add_file_to_group(tree, kind, item)
            return
        fid = item.data(0, ROLE_FILE_ID)
        if not fid:
            return
        menu = QMenu(tree)
        menu.setStyleSheet(_MENU_QSS)
        act_remove = menu.addAction("取消关联")
        act_add = menu.addAction("添加关联")
        selected = menu.exec(tree.viewport().mapToGlobal(pos))
        if selected is act_remove:
            self._remove_file_from_group(item)
        elif selected is act_add:
            self._add_file_to_group(tree, kind, item.parent())

    def _remove_file_from_group(self, item: QTreeWidgetItem):
        """「取消关联」：将文件移出所在组（组可留空）。"""
        group = item.parent()
        if group is None:
            return
        group.removeChild(item)
        self._refresh_group_title(group)

    def _add_file_to_group(self, tree: _GroupTree, kind: str,
                           group: QTreeWidgetItem):
        """「添加关联」：从当前候选池选择同类型文件加入本组。"""
        candidates = self._candidates(kind, group)
        if not candidates:
            MkMessage.info(self, "没有可添加的同类型文件")
            return
        names = [
            f"{name}（¥ {amt:,.2f}）" if amt is not None else name
            for _, name, amt in candidates
        ]
        name, ok = QInputDialog.getItem(
            self, "添加关联", f"选择要加入「{group.text(0)}」的文件：",
            names, 0, False,
        )
        if not ok:
            return
        fid, fname, amt = candidates[names.index(name)]
        group.addChild(self._make_file_item(fid, fname, amt))
        group.setExpanded(True)
        self._refresh_group_title(group)

    def _candidates(self, kind: str,
                    group: QTreeWidgetItem) -> list[tuple[str, str, Optional[float]]]:
        """候选 = Store 中所有同类型文件（排除缺失、本侧各组合已占用成员）。

        相比旧实现（仅当前匹配列表内文件），改为全量同类型文件，便于把任意
        同类型文件补进组合；文件添加后成为所属组合的子行。
        """
        if not self._store:
            return []
        files = (
            self._store.get_invoices()
            if kind == "invoice"
            else self._store.get_payments()
        )
        tree = self._left_tree if kind == "invoice" else self._right_tree
        used: set[str] = set()
        for i in range(tree.topLevelItemCount()):
            g = tree.topLevelItem(i)
            for j in range(g.childCount()):
                fid = g.child(j).data(0, ROLE_FILE_ID)
                if fid:
                    used.add(fid)
        candidates: list[tuple[str, str, Optional[float]]] = []
        for f in files:
            if f.file_id in used:
                continue
            amt = f.amount.final_amount if f.amount else None
            candidates.append((f.file_id, f.file_name, amt))
        return candidates

    # ── 同步滚动 ─────────────────────────────────────────

    def _sync_scroll(self, other: str, value: int):
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        try:
            target = self._right_tree if other == "left" else self._left_tree
            target.verticalScrollBar().setValue(value)
        finally:
            self._syncing_scroll = False

    # ── 结果输出 ─────────────────────────────────────────

    def accepted_pairs(self) -> list[dict]:
        """按组（行）对齐配对：左组发票 × 右组支付 两两组合。

        任一侧为空组视为无关联，跳过该行。
        """
        pairs: list[dict] = []
        n = min(self._left_tree.topLevelItemCount(),
                self._right_tree.topLevelItemCount())
        for i in range(n):
            lg = self._left_tree.topLevelItem(i)
            rg = self._right_tree.topLevelItem(i)
            inv_ids = [
                lg.child(j).data(0, ROLE_FILE_ID)
                for j in range(lg.childCount())
            ]
            pay_ids = [
                rg.child(j).data(0, ROLE_FILE_ID)
                for j in range(rg.childCount())
            ]
            if inv_ids and pay_ids:
                pairs.append({"invoice_ids": inv_ids, "payment_ids": pay_ids})
        return pairs
