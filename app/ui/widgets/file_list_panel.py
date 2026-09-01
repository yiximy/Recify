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
    QInputDialog, QMessageBox,
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
ROLE_PARTNER_ID = Qt.ItemDataRole.UserRole + 2     # 子行对应的关联对象 file_id
ROLE_COMBO_ID = Qt.ItemDataRole.UserRole + 3       # 组合父行存 combo_id；成员文件存所属 combo_id

# 层级配色（四层对比，肉眼可辨）：
#   独立文件行     白底 #ffffff
#   组合父行       浅蓝底 #cfe4ff + 加粗 #409eff 文字 + 主色强调条
#   组合成员文件行 浅灰底 #dde3ea
#   关联对象子行   浅红底 #ffdddd + #334155 文字 + 主色强调条
# 强调条在 drawRow 中最后绘制（最上层，不受主题重绘影响），保证层级一眼可辨。
_C_COMBO_BG = QColor("#cfe4ff")           # 组合父行底色（浅蓝，比 #ecf5ff 加深）
_C_COMBO_FG = QColor("#409eff")           # 组合父行标题色
_C_CHILD_BG = QColor("#ffdddd")           # 关联子行底色（浅红，红色系验证并保留）
_C_CHILD_FG = QColor("#334155")
_C_CHILD_ACCENT = QColor("#409eff")
_C_MEMBER_BG = QColor("#dde3ea")          # 组合成员文件行底色（浅灰，比 #f5f7fa 加深）
_ACCENT_WIDTH = 5                          # 强调条宽度（组合父行/关联子行）

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
        """按行角色着色：关联子行浅蓝底+主色强调条，成员文件行浅灰蓝底。

        组合成员文件行（第二层）用极浅底色与白底父行/顶层独立文件区分；
        关联对象子行（第三层或独立文件子行）保留原有浅蓝底 + 左侧强调条。
        """
        item = self.itemFromIndex(index)
        is_partner = False
        is_member = False
        is_combo_root = False
        if item is not None:
            is_partner = item.data(COL_SEQ, ROLE_PARTNER_ID) is not None
            is_member = (
                not is_partner
                and item.parent() is not None
                and item.data(COL_SEQ, ROLE_COMBO_ID) is not None
            )
            is_combo_root = (
                not is_partner
                and item.parent() is None
                and item.data(COL_SEQ, ROLE_COMBO_ID) is not None
            )
        if is_partner:
            painter.fillRect(option.rect, _C_CHILD_BG)
        elif is_member:
            painter.fillRect(option.rect, _C_MEMBER_BG)
        elif is_combo_root:
            painter.fillRect(option.rect, _C_COMBO_BG)
        super().drawRow(painter, option, index)
        if is_partner or is_combo_root:
            bar = QRect(option.rect.left(), option.rect.top(),
                        _ACCENT_WIDTH, option.rect.height())
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
    locateAllRequested = Signal(str, list)  # 源文件 file_id + 关联对象列表
    locateFileRequested = Signal(str)       # 目标关联文件 file_id
    combosChanged = Signal()               # 组合增删后由 ComparePage 重建两侧树
    selectionChanged = Signal()            # 当前选中项变化（文件/组合均触发），用于刷新关联按钮

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
        self._located_file_ids: Optional[set[str]] = None  # 定位过滤状态
        self._combo_item_by_id: dict[str, QTreeWidgetItem] = {}  # combo_id → 组合父行

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

        # ── 定位状态栏：另一侧「定位所有」时显示并可清除 ──
        locate_bar = QHBoxLayout()
        locate_bar.setSpacing(8)

        self.lbl_locate_status = QLabel("")
        self.lbl_locate_status.setStyleSheet(
            "color: #409eff; font-size: 12px; font-weight: 600;"
        )
        locate_bar.addWidget(self.lbl_locate_status)

        self.btn_clear_locate = MkButton("清除", type="default")
        self.btn_clear_locate.clicked.connect(self.clear_located_files)
        self.btn_clear_locate.setVisible(False)
        locate_bar.addWidget(self.btn_clear_locate)

        locate_bar.addStretch()
        layout.addLayout(locate_bar)

        # ── 文件树 ──
        self.tree = _HierarchyTree()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["序号", "文件名", "金额", "修改日期", "状态"])
        self.tree.setRootIsDecorated(True)          # 显示展开箭头（仅对有子项者）
        self.tree.setIndentation(18)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.setUniformRowHeights(False)       # 状态列放置 widget，行高不均一
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
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
        """按文件列表重建树（三层：独立文件/组合父行 → 成员文件 → 关联对象）。

        顶层项两类：独立文件（不在任何组合中）与组合父行（默认展开，金额=总和）；
        组合成员文件作为组合父行的子项，可再展开显示关联对象。序号列对独立文件
        与组合父行统一编号（组合按首个成员在原顺序中的位置插入）。
        """
        self.tree.clear()
        self._seq_by_fid.clear()
        self._item_by_fid.clear()
        self._combo_item_by_id.clear()

        combos = self.store.get_combos(self.kind) if self.store else []
        combo_by_id = {c["combo_id"]: c for c in combos}
        member_to_combo: dict[str, str] = {
            fid: c["combo_id"] for c in combos for fid in c["file_ids"]
        }

        if not files and not combos:
            self.lbl_count.setText("共 0 个文件")
            self._update_locate_status()
            return

        rendered: set[str] = set()
        seq = 0
        for f in files:
            combo_id = member_to_combo.get(f.file_id)
            if combo_id and combo_id not in rendered:
                combo = combo_by_id.get(combo_id)
                if combo is None:
                    continue
                # 成员按 combo.file_ids 的有序顺序展示
                by_fid = {ff.file_id: ff for ff in files}
                members = [
                    by_fid[fid] for fid in combo["file_ids"] if fid in by_fid
                ]
                if not members:
                    continue
                seq += 1
                item = self._make_combo_item(seq, combo, members)
                self.tree.addTopLevelItem(item)
                self._combo_item_by_id[combo_id] = item
                item.setExpanded(True)          # 组合父行默认展开
                rendered.add(combo_id)
                # 状态徽标须在入树后再放置
                for j, mf in enumerate(members):
                    self._attach_badge(item.child(j), mf)
            elif not combo_id:
                seq += 1
                self._seq_by_fid[f.file_id] = seq
                item = self._make_file_item(seq, f)
                self.tree.addTopLevelItem(item)
                self._item_by_fid[f.file_id] = item
                # 状态徽标须在入树后再放置
                self._attach_badge(item, f)

        self.lbl_count.setText(f"共 {len(files)} 个文件")
        # 重新应用当前查找过滤（若有）
        self._on_find(self.input_find.text())
        self._update_locate_status()

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
        for name, partner_id in self._partner_entries(f):
            item.addChild(self._make_partner_child(name, partner_id))

    def _make_combo_item(self, seq: int, combo: dict,
                         members: list) -> QTreeWidgetItem:
        """构造组合父行：名称列显示组合名，金额列显示成员总和，默认展开。"""
        item = QTreeWidgetItem()
        item.setData(COL_SEQ, ROLE_COMBO_ID, combo["combo_id"])
        item.setText(COL_SEQ, str(seq))
        item.setText(COL_NAME, combo["name"])
        item.setToolTip(COL_NAME, combo["name"])
        item.setText(COL_AMOUNT, self._format_combo_total(combo["combo_id"]))
        item.setText(COL_DATE, f"{len(combo['file_ids'])} 个成员")
        item.setExpanded(True)
        bold = QFont()
        bold.setBold(True)
        item.setFont(COL_NAME, bold)
        item.setForeground(COL_NAME, QBrush(_C_COMBO_FG))
        for mf in members:
            child = self._make_member_item(mf, combo["combo_id"])
            item.addChild(child)
            self._item_by_fid[mf.file_id] = child
        return item

    def _make_member_item(self, mf, combo_id: str) -> QTreeWidgetItem:
        """构造组合成员文件行（可再展开显示其关联对象子行）。"""
        child = QTreeWidgetItem()
        child.setData(COL_SEQ, ROLE_FILE_ID, mf.file_id)
        child.setData(COL_SEQ, ROLE_COMBO_ID, combo_id)
        child.setText(COL_NAME, mf.file_name)
        child.setToolTip(COL_NAME, mf.file_name)
        child.setText(COL_AMOUNT, self._format_amount(mf))
        child.setText(COL_DATE, _format_date(mf.modified_iso))
        self._rebuild_children(child, mf)
        return child

    def _format_combo_total(self, combo_id: str) -> str:
        """格式化组合成员金额总和（round 2）。"""
        total = self.store.get_combo_total(combo_id) if self.store else 0.0
        return f"¥ {total:,.2f}"

    def _file_by_id(self, file_id: str):
        """按 file_id 返回面板缓存的文件对象。"""
        return next((f for f in self._files if f.file_id == file_id), None)

    def _combo_partner_ids(self, combo: dict) -> list[str]:
        """收集组合内全部成员已关联对象的 file_id（去重、跳过缺失）。"""
        partner_ids: list[str] = []
        for fid in combo.get("file_ids", []):
            f = self._file_by_id(fid)
            if f is None:
                continue
            for pid, _ in self._partner_entries(f):
                if pid not in partner_ids:
                    partner_ids.append(pid)
        return partner_ids

    @staticmethod
    def _make_partner_child(name: str, partner_id: str) -> QTreeWidgetItem:
        """构造一个关联对象子行（缩进 + 斜体灰字 + ↳ 前缀，形成清晰层级）。"""
        child = QTreeWidgetItem()
        child.setText(COL_NAME, f"↳ {name}")
        child.setToolTip(COL_NAME, name)
        child.setData(COL_NAME, ROLE_PARTNER_NAME, name)   # 纯文件名（供复制）
        child.setData(COL_SEQ, ROLE_PARTNER_ID, partner_id)  # 供「定位文件」
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

    def _partner_entries(self, f) -> list[tuple[str, str]]:
        """返回该文件已关联对象的 (文件名, file_id)，跳过磁盘已删除对象。"""
        if not self.store:
            return []
        entries: list[tuple[str, str]] = []
        if self.kind == "invoice":
            for pid in getattr(f, "linked_payment_ids", []):
                partner = self.store.get_payment(pid)
                if partner and not partner.missing:
                    entries.append((partner.file_name, pid))
        else:
            for iid in getattr(f, "linked_invoice_ids", []):
                partner = self.store.get_invoice(iid)
                if partner and not partner.missing:
                    entries.append((partner.file_name, iid))
        return entries

    # ── 查找定位 ────────────────────────────────────────────

    def _on_find(self, _text: str):
        """查找文本变化时重新应用可见性。"""
        self._apply_visibility()

    def _apply_visibility(self):
        """按查找文本与定位过滤叠加控制顶层项可见性（组合按成员/名称匹配）。"""
        query = (self.input_find.text() or "").strip().lower()
        first_match: Optional[QTreeWidgetItem] = None
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            combo_id = item.data(COL_SEQ, ROLE_COMBO_ID)
            if combo_id:
                matched = False
                if query and query in item.text(COL_NAME).lower():
                    matched = True
                if query and item.text(COL_SEQ) == query:
                    matched = True
                for j in range(item.childCount()):
                    child = item.child(j)
                    fid = child.data(COL_SEQ, ROLE_FILE_ID)
                    cname = child.text(COL_NAME).lower()
                    cmatched = (not query) or (query in cname)
                    if self._located_file_ids is not None and fid not in self._located_file_ids:
                        cmatched = False
                    if cmatched:
                        matched = True
                        break
                if not query and self._located_file_ids is None:
                    matched = True
                item.setHidden(not matched)
                if matched:
                    if query or self._located_file_ids is not None:
                        item.setExpanded(True)
                    if first_match is None:
                        first_match = item
            else:
                fid = item.data(COL_SEQ, ROLE_FILE_ID)
                name = item.text(COL_NAME).lower()
                seq = item.text(COL_SEQ)
                matched = (not query) or (query in name) or (seq == query)
                if self._located_file_ids is not None and fid not in self._located_file_ids:
                    matched = False
                item.setHidden(not matched)
                if matched and first_match is None:
                    first_match = item

        if query and first_match is not None:
            self.tree.setCurrentItem(first_match)
            self.tree.scrollToItem(first_match)

    def set_located_files(self, file_ids: Optional[list[str]]):
        """在另一侧定位关联文件：仅显示给定 file_id 列表。"""
        self._located_file_ids = set(file_ids) if file_ids else None
        self.input_find.clear()
        self._update_locate_status()
        self._apply_visibility()

    def clear_located_files(self):
        """清除定位过滤，恢复完整列表。"""
        self.set_located_files(None)

    def locate_file(self, file_id: str):
        """定位单个文件：清除搜索与定位过滤后选中并滚动到目标。"""
        self.clear_located_files()
        self.input_find.clear()
        self.select_by_id(file_id)

    def _update_locate_status(self):
        """更新定位状态提示与清除按钮。"""
        if self._located_file_ids:
            count = sum(
                1 for fid in self._located_file_ids if fid in self._item_by_fid
            )
            self.lbl_locate_status.setText(f"已定位 {count} 个关联文件")
            self.btn_clear_locate.setVisible(True)
        else:
            self.lbl_locate_status.setText("")
            self.btn_clear_locate.setVisible(False)

    # ── 选择与查询 ──────────────────────────────────────────

    def _on_current_item_changed(self, current, _previous):
        """当前项变化：文件项触发选中，组合项清空文件选中；均发出 selectionChanged。"""
        if current is None:
            self._current_file_id = None
            self.selectionChanged.emit()
            return
        fid = current.data(COL_SEQ, ROLE_FILE_ID)
        if not fid:
            self._current_file_id = None
            self.selectionChanged.emit()
            return
        self._current_file_id = fid
        self.fileSelected.emit(fid)
        self.selectionChanged.emit()

    def get_selected_file(self):
        """获取当前选中的文件对象。"""
        if self._current_file_id is None:
            return None
        return self._file_by_id(self._current_file_id)

    def get_selected_combo(self) -> Optional[dict]:
        """获取当前选中的组合父行对应组合；非组合选中返回 None。"""
        item = self.tree.currentItem()
        if item is None or item.parent() is not None:
            return None
        combo_id = item.data(COL_SEQ, ROLE_COMBO_ID)
        if not combo_id or not self.store:
            return None
        return self.store.get_combo(combo_id)

    def reload_from_store(self):
        """从 Store 重新拉取文件并重建树（组合增删后调用）。"""
        if not self.store:
            return
        if self.kind == "invoice":
            files = self.store.get_invoices()
        else:
            files = self.store.get_payments()
        self._files = files
        self._populate_tree(files)

    def select_by_id(self, file_id: str):
        """程序化选中指定 ID 的文件（用于自动比对审阅模式）。"""
        item = self._item_by_fid.get(file_id)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        self._current_file_id = file_id
        self.fileSelected.emit(file_id)

    def _collect_unlink_files(self, top_files, top_combos) -> list:
        """把选中的顶层项展开为待取消关联的文件对象列表。

        顶层独立文件直接纳入；组合父行展开为其全部成员文件；按 file_id 去重。
        """
        files: list = []
        seen: set[str] = set()
        for i in top_files:
            f = self._file_by_id(i.data(COL_SEQ, ROLE_FILE_ID))
            if f is not None and f.file_id not in seen:
                files.append(f)
                seen.add(f.file_id)
        if self.store:
            for i in top_combos:
                combo = self.store.get_combo(i.data(COL_SEQ, ROLE_COMBO_ID))
                if not combo:
                    continue
                for fid in combo.get("file_ids", []):
                    f = self._file_by_id(fid)
                    if f is not None and f.file_id not in seen:
                        files.append(f)
                        seen.add(f.file_id)
        return files

    def _on_tree_context_menu(self, pos):
        """右键菜单：关联子行复制/定位；文件行定位所有/取消所有关联/组合；组合父行取消组合。"""
        item = self.tree.itemAt(pos)
        if item is None:
            return

        # 关联对象子行（第三层或独立文件子行）
        partner_id = item.data(COL_SEQ, ROLE_PARTNER_ID)
        if partner_id:
            name = item.data(COL_NAME, ROLE_PARTNER_NAME)
            menu = QMenu(self.tree)
            menu.setStyleSheet(_MENU_QSS)
            act_copy = menu.addAction("复制文件名")
            act_locate = menu.addAction("定位文件")
            selected = menu.exec(self.tree.viewport().mapToGlobal(pos))
            if selected is act_copy:
                QApplication.clipboard().setText(name)
                MkMessage.success(self, f"已复制文件名：{name}")
            elif selected is act_locate:
                self.locateFileRequested.emit(partner_id)
            return

        # 组合父行（顶层）
        if item.parent() is None:
            combo_id = item.data(COL_SEQ, ROLE_COMBO_ID)
            if combo_id:
                self._show_combo_menu(item, combo_id, pos)
                return

        # 文件行：顶层独立文件 或 组合成员文件
        fid = item.data(COL_SEQ, ROLE_FILE_ID)
        if not fid:
            return
        file_obj = self._file_by_id(fid)
        if file_obj is None:
            return

        is_top_level = item.parent() is None
        selected = self.tree.selectedItems()
        top_files = [
            i for i in selected
            if i.parent() is None and i.data(COL_SEQ, ROLE_FILE_ID)
        ]
        top_combos = [
            i for i in selected
            if i.parent() is None and i.data(COL_SEQ, ROLE_COMBO_ID)
        ]
        # 多选判定：选中的顶层项 = 顶层独立文件 + 组合父行（按 ROLE_COMBO_ID 识别），
        # 组合父行也计入，避免含组合父行时误走单文件分支
        all_selected_top = (
            len(selected) > 0
            and len(top_files) + len(top_combos) == len(selected)
        )
        multi = (
            is_top_level
            and all_selected_top
            and len(top_files) + len(top_combos) >= 2
        )
        # 「组合」仍仅对顶层独立文件多选生效（组合父行不参与创建组合）
        multi_files = (
            is_top_level
            and len(top_files) >= 2
            and len(top_files) == len(selected)
        )

        # 「取消所有关联」作用对象：多选时为全部选中顶层独立文件 + 组合父行的成员文件；
        # 否则为右键文件
        if multi:
            unlink_files = self._collect_unlink_files(top_files, top_combos)
        else:
            unlink_files = [file_obj]
        has_partner = any(self._partner_entries(f) for f in unlink_files)

        partner_ids = [pid for _, pid in self._partner_entries(file_obj)]

        menu = QMenu(self.tree)
        menu.setStyleSheet(_MENU_QSS)
        act_combo = menu.addAction("组合") if multi_files else None
        act_locate_all = None
        act_unlink_all = None
        if partner_ids:
            act_locate_all = menu.addAction("定位所有")
        if has_partner:
            act_unlink_all = menu.addAction("取消所有关联")
        if not menu.actions():
            return
        selected_action = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if selected_action is act_combo:
            self._on_create_combo(
                [i.data(COL_SEQ, ROLE_FILE_ID) for i in top_files]
            )
        elif selected_action is act_locate_all:
            self.locateAllRequested.emit(fid, partner_ids)
        elif selected_action is act_unlink_all:
            if multi:
                self._on_unlink_all_files(unlink_files)
            else:
                self._on_unlink_all(file_obj, partner_ids)

    # ── 组合/取消关联 操作 ────────────────────────────────

    def _show_combo_menu(self, item: QTreeWidgetItem, combo_id: str, pos):
        """组合父行右键菜单：取消组合；任一成员已关联时提供定位所有/取消所有关联。"""
        combo = self.store.get_combo(combo_id) if self.store else None
        if combo is None:
            return
        partner_ids = self._combo_partner_ids(combo)
        menu = QMenu(self.tree)
        menu.setStyleSheet(_MENU_QSS)
        act_dissolve = menu.addAction("取消组合")
        act_locate_all = None
        act_unlink_all = None
        if partner_ids:
            act_locate_all = menu.addAction("定位所有")
            act_unlink_all = menu.addAction("取消所有关联")
        selected = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if selected is act_dissolve:
            self._on_dissolve_combo(combo)
        elif selected is act_locate_all:
            self.locateAllRequested.emit(combo_id, partner_ids)
        elif selected is act_unlink_all:
            self._on_unlink_all_combo(combo)

    def _on_create_combo(self, file_ids: list[str]):
        """多选文件 → 输入组合名 → 创建组合。"""
        if not self.store or len(file_ids) < 2:
            return
        name, ok = QInputDialog.getText(
            self, "创建组合", "请输入组合名称：", text="",
        )
        if not ok or not name.strip():
            return
        self.store.create_combo(self.kind, name.strip(), file_ids)
        self.combosChanged.emit()

    def _on_dissolve_combo(self, combo: dict):
        """取消组合：确认后解散，成员恢复独立顶层项。"""
        ret = QMessageBox.question(
            self, "取消组合",
            f"确定要解散组合「{combo['name']}」吗？\n成员文件将恢复为独立文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_combo(combo["combo_id"])
        self.combosChanged.emit()

    def _on_unlink_all(self, file_obj, partner_ids: list[str]):
        """取消单个文件全部关联（带确认）。"""
        if not self.store:
            return
        ret = QMessageBox.question(
            self, "取消所有关联",
            f"确定要取消「{file_obj.file_name}」的全部关联吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        for pid in partner_ids:
            if self.kind == "invoice":
                self.store.remove_association(file_obj.file_id, pid)
            else:
                self.store.remove_association(pid, file_obj.file_id)
        MkMessage.success(self, f"已取消「{file_obj.file_name}」的全部关联")

    def _on_unlink_all_files(self, files):
        """多选文件：确认后逐个取消全部关联，完成后提示取消条数。"""
        if not self.store or not files:
            return
        ret = QMessageBox.question(
            self, "取消所有关联",
            f"确定要取消 {len(files)} 个文件的全部关联吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        removed = 0
        for f in files:
            for _, pid in self._partner_entries(f):
                if self.kind == "invoice":
                    ok = self.store.remove_association(f.file_id, pid)
                else:
                    ok = self.store.remove_association(pid, f.file_id)
                if ok:
                    removed += 1
        MkMessage.success(
            self, f"已取消 {len(files)} 个文件的全部关联，共 {removed} 条",
        )

    def _on_unlink_all_combo(self, combo: dict):
        """取消组合内全部成员的所有关联（带确认）。"""
        partner_ids = self._combo_partner_ids(combo)
        if not partner_ids:
            return
        ret = QMessageBox.question(
            self, "取消所有关联",
            f"确定要取消组合「{combo['name']}」内全部成员的所有关联吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        for fid in combo.get("file_ids", []):
            f = self._file_by_id(fid)
            if f is None:
                continue
            for _, pid in self._partner_entries(f):
                if self.kind == "invoice":
                    self.store.remove_association(fid, pid)
                else:
                    self.store.remove_association(pid, fid)
        MkMessage.success(self, f"已取消组合「{combo['name']}」内全部关联")

    def refresh_status(self):
        """刷新关联概要/子行/徽标/金额（关联或金额变化后调用），并保留展开状态。"""
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
            f.amount = latest.amount

            self._rebuild_children(item, f)           # 展开子行明细
            item.setText(COL_AMOUNT, self._format_amount(f))
            badge = self.tree.itemWidget(item, COL_STATUS)
            if badge:
                linked, count, auto = self._link_state(f)
                badge.set_linked(linked, count, auto=auto)

            if f.file_id in expanded_fids and item.childCount() > 0:
                item.setExpanded(True)

        # 组合父行金额实时重算（成员金额变化 / 成员变动后自动更新）
        for combo_id, item in self._combo_item_by_id.items():
            combo = self.store.get_combo(combo_id)
            if combo:
                item.setText(COL_AMOUNT, self._format_combo_total(combo_id))
                item.setText(COL_DATE, f"{len(combo['file_ids'])} 个成员")

        self._apply_visibility()
        self._update_locate_status()

    def restore_folder(self):
        """从 Store 恢复上次保存的文件夹路径。"""
        if self.store:
            path = self.store.get_folder(self.kind)
            if path:
                self.folder_picker.set_path(path)
                self._scan_and_load(path)
