# -*- coding: utf-8 -*-
"""文件列表面板：QTreeWidget + 工具栏。

在双栏比对场景下展示发票 / 支付记录文件，并支持：
- 序号列：为每个文件分配稳定唯一序号，便于定位与对照。
- 关联展开：已建立关联的文件显示展开箭头，展开后以缩进子行清晰列出
  全部关联对象文件名；未关联文件不显示箭头。
- 快速查找：按「序号」或「文件名」过滤并跳转定位。

之所以从 MkTable(QTableWidget) 改为 QTreeWidget：表格没有原生的层级展开，
用插入/删除子行模拟会导致行号漂移、破坏选中与单元格 widget 的映射；树控件
原生支持展开箭头（且仅对有子项者显示）、缩进与层级，天然契合本需求。
样式对齐 Elegant Light 主题，保持与其余界面一致。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal, Qt, QRect
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QApplication, QMenu,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView,
)

from monkeyqt import MkButton, MkInput, MkMessage
from .folder_picker import FolderPicker
from .status_badge import StatusBadge
from .table_utils import enable_smooth_scroll
from app.core.file_scanner import FileScanner
from app.core.models import InvoiceFile, PaymentFile

# ── 列索引 ──（已移除「关联对象」列；关联信息经展开子行呈现，状态列给出概览）
COL_SEQ = 0       # 序号
COL_NAME = 1      # 文件名
COL_AMOUNT = 2    # 金额
COL_DATE = 3      # 修改日期
COL_STATUS = 4    # 状态徽标

STATUS_COL_WIDTH = 84

# QTreeWidgetItem 自定义数据角色
ROLE_FILE_ID = Qt.ItemDataRole.UserRole            # 该行对应文件 id（子行存父文件 id）
ROLE_PARTNER_NAME = Qt.ItemDataRole.UserRole + 1   # 子行的纯文件名（不含 ↳ 前缀）

# 层级配色：父行白底、子行明显区分。为确保在真实主题/高 DPI 下都清晰可辨，
# 子行除了更明显的浅蓝底，还叠加一条左侧主色强调条（drawRow 中最后绘制，
# 不受主题重绘影响）。子行文字 #334155 于底色 #dce8fb 对比度 ≈ 9:1，满足
# WCAG AA/AAA。
_C_CHILD_BG = QColor("#dce8fb")
_C_CHILD_FG = QColor("#334155")
_C_CHILD_ACCENT = QColor("#409eff")
_CHILD_ACCENT_WIDTH = 3

# 树控件样式（镜像 MkTable 的 Elegant Light 观感，保证视觉统一）
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
QHeaderView::section {
    background: #f5f7fa;
    color: #909399;
    border: none;
    border-bottom: 1px solid #ebeef5;
    padding: 8px 6px;
    font-weight: 700;
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
"""

# 右键上下文菜单样式（对齐 Elegant Light）
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


class _HierarchyTree(QTreeWidget):
    """文件树：为「第二层」子行绘制区分底色 + 左侧强调条，形成清晰层级。

    QTreeWidget 一旦设置了控制 ::item 的样式表，逐项 setBackground 会被忽略，
    故改在 drawRow 中整行填充子行底色（含左侧缩进沟槽）。父行不填充，保持
    白底；配合 ::item{background:transparent} 让填充透出。

    另在 super().drawRow 之后补画一条左侧主色强调条：即便某些主题/DPI 下浅底
    色差被弱化，这条强调条也能保证层级一眼可辨（绘制在最上层，不被覆盖）。
    """

    def drawRow(self, painter, option, index):
        is_child = index.parent().isValid()
        if is_child:
            painter.fillRect(option.rect, _C_CHILD_BG)
        super().drawRow(painter, option, index)
        if is_child:
            bar = QRect(option.rect.left(), option.rect.top(),
                        _CHILD_ACCENT_WIDTH, option.rect.height())
            painter.fillRect(bar, _C_CHILD_ACCENT)


def _format_date(iso_str: str) -> str:
    """格式化 ISO 日期为简短显示。"""
    if not iso_str:
        return ""
    # ISO 格式: 2026-07-09T10:00:00
    parts = iso_str.split("T")
    date_part = parts[0]
    time_part = parts[1][:5] if len(parts) > 1 else ""
    return f"{date_part} {time_part}"


class FileListPanel(QWidget):
    """文件列表面板，支持发票或支付记录。

    信号：
        fileSelected(str): 选中文件时发出（file_id）
        folderChanged(str): 文件夹变化时发出
    """

    fileSelected = Signal(str)       # file_id
    folderChanged = Signal(str)

    def __init__(self, kind: str = "invoice", store=None, parent=None):
        """
        Args:
            kind: "invoice" 或 "payment"，决定文件过滤格式
            store: Store 实例
        """
        super().__init__(parent)
        self.kind = kind
        self.store = store
        self._files: list = []                       # 当前文件列表（顺序即序号顺序）
        self._current_file_id: Optional[str] = None
        self._seq_by_fid: dict[str, int] = {}        # file_id → 序号（稳定）
        self._item_by_fid: dict[str, QTreeWidgetItem] = {}  # file_id → 顶层树项

        label = "发票文件夹" if kind == "invoice" else "支付记录文件夹"
        self._build_ui(label)

    # ── UI 构建 ────────────────────────────────────────────

    def _build_ui(self, label: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ── 顶部工具栏：文件夹选择 + 刷新 ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.folder_picker = FolderPicker(label=label)
        self.folder_picker.folderChanged.connect(self._on_folder_changed)
        toolbar.addWidget(self.folder_picker, stretch=1)

        self.btn_refresh = MkButton("刷新", type="default")
        self.btn_refresh.clicked.connect(self._refresh)
        toolbar.addWidget(self.btn_refresh)

        layout.addLayout(toolbar)

        # ── 查找栏：按序号或文件名快速定位 ──
        find_bar = QHBoxLayout()
        find_bar.setSpacing(8)

        self.input_find = MkInput(placeholder="按序号或文件名查找")
        self.input_find.textChanged.connect(self._on_find)
        find_bar.addWidget(self.input_find, stretch=1)

        self.lbl_count = QLabel("共 0 个文件")
        self.lbl_count.setStyleSheet("color: #909399; font-size: 12px; padding: 2px 0;")
        find_bar.addWidget(self.lbl_count)

        layout.addLayout(find_bar)

        # ── 文件树 ──
        self.tree = _HierarchyTree()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["序号", "文件名", "金额", "修改日期", "状态"])
        self.tree.setRootIsDecorated(True)          # 显示展开箭头（仅对有子项者）
        self.tree.setIndentation(18)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.setUniformRowHeights(False)       # 状态列放置 widget，行高不均一
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setStyleSheet(_TREE_QSS)
        enable_smooth_scroll(self.tree)             # 像素级平滑滚动 + 横向滚动条外观

        # 右键复制文件名（仅在展开子行的文件名列上生效，见 _on_tree_context_menu）
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)

        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_SEQ, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_AMOUNT, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_DATE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(COL_STATUS, STATUS_COL_WIDTH)

        self.tree.currentItemChanged.connect(self._on_current_item_changed)
        layout.addWidget(self.tree, stretch=1)

    # ── 文件夹与扫描 ────────────────────────────────────────

    def _on_folder_changed(self, folder: str):
        """文件夹变化时扫描文件。"""
        if self.store:
            self.store.set_folder(self.kind, folder)
        self.folderChanged.emit(folder)
        self._scan_and_load(folder)

    def _refresh(self):
        """刷新当前文件夹。"""
        folder = self.folder_picker.get_path()
        if folder:
            self._scan_and_load(folder)

    def _scan_and_load(self, folder: str):
        """扫描文件夹并加载文件列表。"""
        if self.kind == "invoice":
            files = FileScanner.scan_invoices(folder)
        else:
            files = FileScanner.scan_payments(folder)

        # 合并到 Store
        if self.store:
            if self.kind == "invoice":
                self.store.merge_invoices(files)
                files = self.store.get_invoices()
            else:
                self.store.merge_payments(files)
                files = self.store.get_payments()

        self._files = files
        self._populate_tree(files)

    # ── 树填充 ──────────────────────────────────────────────

    def _populate_tree(self, files: list):
        """按文件列表重建树，序号按顺序分配（1..N，稳定唯一）。"""
        self.tree.clear()
        self._seq_by_fid.clear()
        self._item_by_fid.clear()

        if not files:
            self.lbl_count.setText("共 0 个文件")
            return

        for idx, f in enumerate(files, start=1):
            self._seq_by_fid[f.file_id] = idx
            item = self._make_file_item(idx, f)
            self.tree.addTopLevelItem(item)
            self._item_by_fid[f.file_id] = item
            # 状态徽标须在入树后再放置
            self._attach_badge(item, f)

        self.lbl_count.setText(f"共 {len(files)} 个文件")
        # 重新应用当前查找过滤（若有）
        self._on_find(self.input_find.text())

    @staticmethod
    def _format_amount(f) -> str:
        """格式化文件金额为显示字符串，无金额时返回 '—'。"""
        amt = f.amount.final_amount if f.amount else None
        return f"¥ {amt:,.2f}" if amt is not None else "—"

    def _make_file_item(self, seq: int, f) -> QTreeWidgetItem:
        """构造一个文件顶层树项，并按关联情况挂接子项。"""
        item = QTreeWidgetItem()
        item.setData(COL_SEQ, ROLE_FILE_ID, f.file_id)
        item.setText(COL_SEQ, str(seq))
        item.setText(COL_NAME, f.file_name)
        item.setToolTip(COL_NAME, f.file_name)
        item.setText(COL_AMOUNT, self._format_amount(f))
        item.setText(COL_DATE, _format_date(f.modified_iso))
        self._rebuild_children(item, f)
        return item

    def _rebuild_children(self, item: QTreeWidgetItem, f):
        """（重建）子行：展开后列出全部关联文件名；未关联则无子项（无展开箭头）。

        关联概览由「状态」列徽标呈现；此处仅负责展开的第二层明细。
        """
        item.takeChildren()  # 刷新时复用同一 item，先清空旧子项
        for nm in self._partner_names(f):
            item.addChild(self._make_partner_child(nm))

    @staticmethod
    def _make_partner_child(name: str) -> QTreeWidgetItem:
        """构造一个关联对象子行（缩进 + 斜体灰字 + ↳ 前缀，形成清晰层级）。

        子行底色由 _HierarchyTree.drawRow 统一绘制（逐项 setBackground 在样式表
        下会被忽略）；此处仅设文字样式，并存纯文件名供右键复制。
        """
        child = QTreeWidgetItem()
        child.setText(COL_NAME, f"↳ {name}")
        child.setToolTip(COL_NAME, name)
        child.setData(COL_NAME, ROLE_PARTNER_NAME, name)   # 纯文件名（供复制）
        # 仅可用、不可选：子行为纯展示，点击不改变主选中/预览
        child.setFlags(Qt.ItemFlag.ItemIsEnabled)
        italic = QFont()
        italic.setItalic(True)
        child.setFont(COL_NAME, italic)
        child.setForeground(COL_NAME, QBrush(_C_CHILD_FG))
        return child

    def _attach_badge(self, item: QTreeWidgetItem, f):
        """在状态列放置关联徽标 widget。"""
        badge = StatusBadge()
        linked, count, auto = self._link_state(f)
        badge.set_linked(linked, count, auto=auto)
        self.tree.setItemWidget(item, COL_STATUS, badge)

    def _link_state(self, f) -> tuple[bool, int, bool]:
        """返回 (是否已关联, 关联数量, 是否全部为自动关联)。

        若任一关联非自动，则视为手动关联（手动关联优先级高于自动关联）。
        """
        if self.kind == "invoice":
            partner_ids = getattr(f, "linked_payment_ids", [])
        else:
            partner_ids = getattr(f, "linked_invoice_ids", [])

        if not partner_ids:
            return False, 0, False

        # 检查是否全部为自动关联
        all_auto = True
        if self.store:
            for pid in partner_ids:
                if self.kind == "invoice":
                    auto = self.store.is_auto_linked(f.file_id, pid)
                else:
                    auto = self.store.is_auto_linked(pid, f.file_id)
                if not auto:
                    all_auto = False
                    break

        return True, len(partner_ids), all_auto

    def _partner_names(self, f) -> list[str]:
        """解析该文件已关联对象的文件名（跳过磁盘已删除的对象）。"""
        if not self.store:
            return []
        names: list[str] = []
        if self.kind == "invoice":
            for pid in getattr(f, "linked_payment_ids", []):
                partner = self.store.get_payment(pid)
                if partner and not partner.missing:
                    names.append(partner.file_name)
        else:
            for iid in getattr(f, "linked_invoice_ids", []):
                partner = self.store.get_invoice(iid)
                if partner and not partner.missing:
                    names.append(partner.file_name)
        return names

    # ── 查找定位 ────────────────────────────────────────────

    def _on_find(self, text: str):
        """按序号或文件名过滤并跳转到首个匹配项。"""
        query = (text or "").strip().lower()
        first_match: Optional[QTreeWidgetItem] = None
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            name = item.text(COL_NAME).lower()
            seq = item.text(COL_SEQ)
            matched = (not query) or (query in name) or (seq == query)
            item.setHidden(not matched)
            if matched and first_match is None:
                first_match = item

        if query and first_match is not None:
            self.tree.setCurrentItem(first_match)
            self.tree.scrollToItem(first_match)

    # ── 选择与查询 ──────────────────────────────────────────

    def _on_current_item_changed(self, current, _previous):
        """当前项变化：仅顶层文件项触发选中（子项不可选）。"""
        if current is None:
            self._current_file_id = None
            return
        fid = current.data(COL_SEQ, ROLE_FILE_ID)
        if not fid:
            self._current_file_id = None
            return
        self._current_file_id = fid
        self.fileSelected.emit(fid)

    def get_selected_file(self):
        """获取当前选中的文件对象。"""
        if self._current_file_id is None:
            return None
        for f in self._files:
            if f.file_id == self._current_file_id:
                return f
        return None

    def select_by_id(self, file_id: str):
        """程序化选中指定 ID 的文件（用于自动比对审阅模式）。"""
        item = self._item_by_fid.get(file_id)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        self._current_file_id = file_id
        self.fileSelected.emit(file_id)

    # ── 右键复制文件名 ──────────────────────────────────────

    def _partner_name_at(self, pos) -> Optional[str]:
        """返回该位置可复制的关联文件名。

        防误触门控：仅「展开子行（第二层）的文件名列」返回文件名；父行、
        非文件名列、空白区域一律返回 None。
        """
        item = self.tree.itemAt(pos)
        if item is None or item.parent() is None:
            return None  # 空白或父行
        if self.tree.columnAt(pos.x()) != COL_NAME:
            return None  # 仅文件名列
        name = item.data(COL_NAME, ROLE_PARTNER_NAME)
        return name or None

    def _on_tree_context_menu(self, pos):
        """右键上下文菜单：在展开子行的文件名上提供「复制文件名」。"""
        name = self._partner_name_at(pos)
        if not name:
            return
        menu = QMenu(self.tree)
        menu.setStyleSheet(_MENU_QSS)
        act_copy = menu.addAction("复制文件名")
        if menu.exec(self.tree.viewport().mapToGlobal(pos)) is act_copy:
            QApplication.clipboard().setText(name)
            MkMessage.success(self, f"已复制文件名：{name}")

    # ── 关联状态刷新 ────────────────────────────────────────

    def refresh_status(self):
        """刷新关联概要/子行/徽标（关联变化后调用），并保留展开状态。"""
        if not self.store or not self._files:
            return
        if self.kind == "invoice":
            files = self.store.get_invoices()
        else:
            files = self.store.get_payments()
        file_map = {f.file_id: f for f in files}

        # 记录当前展开的文件，刷新后尽量恢复（提升连贯感）
        expanded_fids = {
            fid for fid, item in self._item_by_fid.items() if item.isExpanded()
        }

        for f in self._files:
            latest = file_map.get(f.file_id)
            item = self._item_by_fid.get(f.file_id)
            if latest is None or item is None:
                continue
            f.linked_payment_ids = getattr(latest, "linked_payment_ids", [])
            f.linked_invoice_ids = getattr(latest, "linked_invoice_ids", [])

            self._rebuild_children(item, f)           # 展开子行明细
            badge = self.tree.itemWidget(item, COL_STATUS)
            if badge:
                linked, count, auto = self._link_state(f)
                badge.set_linked(linked, count, auto=auto)

            if f.file_id in expanded_fids and item.childCount() > 0:
                item.setExpanded(True)

    def restore_folder(self):
        """从 Store 恢复上次保存的文件夹路径。"""
        if self.store:
            path = self.store.get_folder(self.kind)
            if path:
                self.folder_picker.set_path(path)
                self._scan_and_load(path)
