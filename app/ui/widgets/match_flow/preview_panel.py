# -*- coding: utf-8 -*-
"""画布右侧的模块文件预览面板。

只读 store：源模块展开直接文件与组合成员，匹配模块按入线/出线展开
发票侧/支付侧文件；文件缺失或路径不可用时置灰，预览复用 PreviewView。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)
from monkeyqt import MkButton

from ..preview_view import PreviewView
from .items import STYLE
from .model import (
    FlowModel,
    FlowNode,
    KIND_INVOICE,
    KIND_LABELS,
    KIND_MATCH,
    KIND_PAYMENT,
)

_PANEL_WIDTH = 420

_FILE_ROLE = Qt.ItemDataRole.UserRole
_FILE_KIND_ROLE = Qt.ItemDataRole.UserRole + 1
_FILE_PATH_ROLE = Qt.ItemDataRole.UserRole + 2
_FILE_MISSING_ROLE = Qt.ItemDataRole.UserRole + 3
_ENTRY_ROLE = Qt.ItemDataRole.UserRole + 4


@dataclass(frozen=True)
class PreviewFile:
    """面板中的一条可预览文件记录。"""

    file_id: str
    kind: str
    name: str
    abs_path: str
    missing: bool
    combo_name: str = ""


class MatchFlowPreviewPanel(QFrame):
    """模块文件列表与只读预览面板。"""

    collapseRequested = Signal()

    def __init__(self, store=None, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self._current_files: tuple[PreviewFile, ...] = ()
        self._current_preview_path: Optional[str] = None
        self._current_preview_kind: Optional[str] = None
        self._file_rows: dict[int, PreviewFile] = {}
        self.setObjectName("matchFlowPreviewPanel")
        self.setFixedWidth(_PANEL_WIDTH)
        self._build_ui()
        self.set_selection([], None)

    def _build_ui(self) -> None:
        self.setStyleSheet("""
            QFrame#matchFlowPreviewPanel {
                background: #ffffff;
                border-left: 1px solid #e4e7ed;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.lbl_title = QLabel("文件预览")
        self.lbl_title.setObjectName("previewTitleLabel")
        self.lbl_title.setStyleSheet(
            "font-size: 14px; font-weight: 700; color: #303133;")
        header.addWidget(self.lbl_title)

        self.lbl_type = QLabel("未选中")
        self.lbl_type.setObjectName("previewTypeLabel")
        header.addWidget(self.lbl_type)
        header.addStretch()

        self.btn_collapse = MkButton("折叠", type="default")
        self.btn_collapse.setAutoDefault(False)
        self.btn_collapse.setFixedWidth(62)
        self.btn_collapse.setToolTip("折叠预览面板")
        self.btn_collapse.clicked.connect(self.collapseRequested.emit)
        header.addWidget(self.btn_collapse)
        layout.addLayout(header)

        self.file_list = QListWidget()
        self.file_list.setObjectName("previewFileList")
        self.file_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.file_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.file_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.file_list.setMinimumHeight(126)
        self.file_list.setMaximumHeight(178)
        self.file_list.setStyleSheet("""
            QListWidget {
                background: #fafbfc;
                border: 1px solid #e4e7ed;
                border-radius: 6px;
                font-size: 12px;
                outline: none;
            }
            QListWidget::item { padding: 5px 7px; }
            QListWidget::item:selected {
                background: #ecf5ff;
                color: #409eff;
            }
        """)
        self.file_list.currentItemChanged.connect(self._on_current_item_changed)
        layout.addWidget(self.file_list, stretch=2)

        self.preview_view = PreviewView(title="文件预览")
        self.preview_view.setObjectName("matchFlowPreviewView")
        layout.addWidget(self.preview_view, stretch=5)

    @property
    def current_files(self) -> tuple[PreviewFile, ...]:
        """当前列表文件快照，供交互和验证读取。"""
        return self._current_files

    @property
    def current_preview_path(self) -> Optional[str]:
        return self._current_preview_path

    @property
    def current_preview_kind(self) -> Optional[str]:
        return self._current_preview_kind

    def set_store(self, store) -> None:
        self.store = store

    def set_selection(self, nodes: list[FlowNode],
                      model: Optional[FlowModel]) -> None:
        """按当前画布选中节点刷新标题、文件列表和默认预览。"""
        if not nodes:
            self._show_placeholder("点击发票 / 支付模块查看文件内容")
            return
        if len(nodes) != 1:
            self._show_placeholder(
                f"已选择 {len(nodes)} 个模块，请单选查看文件",
                type_text=f"多选 {len(nodes)}",
            )
            return

        node = nodes[0]
        self._set_header(node.name, node.kind)
        if node.kind in (KIND_INVOICE, KIND_PAYMENT):
            files = self._collect_node_files(node)
            if files:
                self._render_files(files)
            else:
                self._render_placeholder("未绑定文件")
            return
        if node.kind == KIND_MATCH and model is not None:
            self._render_match_files(node, model)
            return
        self._render_placeholder("未绑定文件")

    def _set_header(self, title: str, kind: Optional[str]) -> None:
        self.lbl_title.setText(title)
        if kind not in STYLE:
            self.lbl_type.setText("未选中")
            self.lbl_type.setStyleSheet(
                "color: #909399; background: #f4f4f5; border-radius: 9px;"
                "padding: 2px 7px; font-size: 11px;")
            return
        style = STYLE[kind]
        accent = style["accent"].name()
        background = style["bg"].name()
        self.lbl_type.setText(KIND_LABELS.get(kind, kind))
        self.lbl_type.setStyleSheet(
            f"color: {accent}; background: {background};"
            f"border: 1px solid {accent}; border-radius: 9px;"
            "padding: 1px 7px; font-size: 11px; font-weight: 600;")

    def _show_placeholder(self, text: str, type_text: str = "未选中") -> None:
        self._set_header("文件预览", None)
        self.lbl_type.setText(type_text)
        self._render_placeholder(text)

    def _reset_render(self) -> None:
        self.file_list.blockSignals(True)
        self.file_list.clear()
        self._file_rows = {}
        self._current_files = ()
        self._clear_preview()

    def _finish_render(self, files: list[PreviewFile]) -> None:
        self._current_files = tuple(files)
        self.file_list.blockSignals(False)
        first_row = next(
            (row for row, f in self._file_rows.items() if not f.missing),
            None,
        )
        if first_row is None:
            self._clear_preview()
        else:
            self.file_list.setCurrentRow(first_row)

    def _render_placeholder(self, text: str) -> None:
        self._reset_render()
        self._add_placeholder_item(text)
        self._finish_render([])

    def _render_files(self, files: list[PreviewFile]) -> None:
        self._reset_render()
        for file in files:
            self._add_file_item(file)
        self._finish_render(files)

    def _add_placeholder_item(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setData(_ENTRY_ROLE, "placeholder")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(QColor("#a8abb2"))
        self.file_list.addItem(item)

    def _add_group_item(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setData(_ENTRY_ROLE, "group")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = QFont(item.font())
        font.setBold(True)
        item.setFont(font)
        item.setForeground(QColor("#606266"))
        item.setBackground(QColor("#f5f7fa"))
        self.file_list.addItem(item)

    def _add_file_item(self, file: PreviewFile) -> None:
        label = file.name
        if file.combo_name:
            label += f"  ·  组合「{file.combo_name}」"
        if file.missing:
            label += "（文件缺失）"

        item = QListWidgetItem(label)
        item.setData(_ENTRY_ROLE, "file")
        item.setData(_FILE_ROLE, file.file_id)
        item.setData(_FILE_KIND_ROLE, file.kind)
        item.setData(_FILE_PATH_ROLE, file.abs_path)
        item.setData(_FILE_MISSING_ROLE, file.missing)
        item.setToolTip(file.abs_path or "文件路径不可用")
        if file.missing:
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(QColor("#c0c4cc"))
        else:
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self._file_rows[self.file_list.count()] = file
        self.file_list.addItem(item)

    def _clear_preview(self) -> None:
        self.preview_view.clear()
        self.preview_view.set_title("文件预览")
        self._current_preview_path = None
        self._current_preview_kind = None

    def _on_current_item_changed(self, current: Optional[QListWidgetItem],
                                 _previous: Optional[QListWidgetItem]) -> None:
        if current is None or current.data(_ENTRY_ROLE) != "file":
            self._clear_preview()
            return
        row = self.file_list.row(current)
        file = self._file_rows.get(row)
        if file is None or file.missing:
            self._clear_preview()
            return
        self._preview_file(file)

    def _preview_file(self, file: PreviewFile) -> bool:
        if file.missing or not file.abs_path or not os.path.isfile(file.abs_path):
            self._clear_preview()
            return False
        self.preview_view.clear()
        try:
            if file.kind == KIND_INVOICE:
                self.preview_view.set_pdf(file.abs_path)
            else:
                pixmap = QPixmap(file.abs_path)
                if pixmap.isNull():
                    self._clear_preview()
                    return False
                self.preview_view.set_pixmap(pixmap)
        except Exception:
            self._clear_preview()
            return False
        if not self.preview_view.has_content:
            self._clear_preview()
            return False
        self.preview_view.set_title(file.name)
        self._current_preview_path = file.abs_path
        self._current_preview_kind = file.kind
        return True

    def _render_match_files(self, node: FlowNode, model: FlowModel) -> None:
        invoice_nodes: list[FlowNode] = []
        for wire in model.wires_to(node.node_id):
            src = model.get_node(wire.src_id)
            if src is not None and src.kind == KIND_INVOICE \
                    and src not in invoice_nodes:
                invoice_nodes.append(src)

        payment_nodes: list[FlowNode] = []
        for wire in model.wires_from(node.node_id):
            dst = model.get_node(wire.dst_id)
            if dst is not None and dst.kind == KIND_PAYMENT \
                    and dst not in payment_nodes:
                payment_nodes.append(dst)

        sections = (("发票侧", invoice_nodes), ("支付侧", payment_nodes))
        if not invoice_nodes and not payment_nodes:
            self._render_placeholder("未绑定文件")
            return

        self._reset_render()
        files: list[PreviewFile] = []
        for label, side_nodes in sections:
            if not side_nodes:
                continue
            self._add_group_item(label)
            side_files = self._collect_nodes_files(side_nodes)
            if side_files:
                for file in side_files:
                    self._add_file_item(file)
                    files.append(file)
            else:
                self._add_placeholder_item("未绑定文件")
        self._finish_render(files)

    def _collect_nodes_files(self, nodes: list[FlowNode]) -> list[PreviewFile]:
        files: list[PreviewFile] = []
        seen: set[str] = set()
        for node in nodes:
            for file in self._collect_node_files(node):
                if file.file_id in seen:
                    continue
                seen.add(file.file_id)
                files.append(file)
        return files

    def _collect_node_files(self, node: FlowNode) -> list[PreviewFile]:
        if self.store is None or node.kind not in (KIND_INVOICE, KIND_PAYMENT):
            return []
        getter = self.store.get_invoice if node.kind == KIND_INVOICE \
            else self.store.get_payment
        files: list[PreviewFile] = []
        seen: set[str] = set()
        for file_id in node.file_ids:
            self._append_file(files, seen, getter, node.kind, file_id, "")
        for combo_id in node.combo_ids:
            combo = self.store.get_combo(combo_id)
            if not combo or combo.get("kind") != node.kind:
                continue
            combo_name = combo.get("name") or "未命名组合"
            for file_id in combo.get("file_ids", []):
                self._append_file(
                    files, seen, getter, node.kind, file_id, combo_name)
        return files

    @staticmethod
    def _append_file(files: list[PreviewFile], seen: set[str], getter,
                     kind: str, file_id: str, combo_name: str) -> None:
        if file_id in seen:
            return
        seen.add(file_id)
        file = getter(file_id)
        if file is None:
            files.append(PreviewFile(
                file_id, kind, f"未知文件 {file_id[:8]}", "", True, combo_name))
            return
        path = getattr(file, "abs_path", "") or ""
        missing = bool(getattr(file, "missing", False)) \
            or not path or not os.path.isfile(path)
        name = getattr(file, "file_name", "") or os.path.basename(path) \
            or f"未知文件 {file_id[:8]}"
        files.append(PreviewFile(
            file_id, kind, name, path, missing, combo_name))
