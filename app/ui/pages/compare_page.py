# -*- coding: utf-8 -*-
"""比对关联页：左右双栏文件列表 + 双预览区 + 关联操作 + 自动比对"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QLabel, QInputDialog,
    QDialog,
)
from monkeyqt import MkButton, MkMessage

from app.ui.widgets.auto_match_dialog import AutoMatchDialog
from app.ui.widgets.file_list_panel import FileListPanel
from app.ui.widgets.preview_view import PreviewView
from app.ui.widgets.toggle_switch import ToggleSwitch


class ComparePage(QWidget):
    """比对关联模式页面。

    布局：
        ┌─────────────────────────────────────────┐
        │ [自动比对]  [是否审阅 ⬜]                 │
        ├─────────────┬───────────────────────────┤
        │ 发票列表(PDF)│ 支付记录列表               │
        ├─────────────┴───────────────────────────┤
        │ [发票预览]   [支付截图预览]               │
        ├─────────────────────────────────────────┤
        │   [关联选中项]    [取消关联]              │
        └─────────────────────────────────────────┘
    """

    def __init__(self, store=None, parent=None):
        super().__init__(parent)
        self.store = store
        self._build_ui()
        self._connect_signals()
        self._restore_state()

        # 自动比对状态
        self._match_pairs: list[dict] = []     # 待处理的匹配对列表
        self._review_mode: bool = True         # 是否审阅模式（默认开启）

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ── 自动比对工具栏 ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(16)

        self.btn_auto_match = MkButton("自动比对", type="primary")
        self.btn_auto_match.setToolTip("基于金额自动匹配发票与支付记录")
        self.btn_auto_match.clicked.connect(self._on_auto_match)
        toolbar.addWidget(self.btn_auto_match)

        self.toggle_review = ToggleSwitch("是否审阅")
        self.toggle_review.setChecked(True)
        self.toggle_review.toggled.connect(self._on_review_toggled)
        toolbar.addWidget(self.toggle_review)

        toolbar.addStretch()

        # 自动比对进度标签
        self.lbl_match_progress = QLabel("")
        self.lbl_match_progress.setStyleSheet(
            "color: #409eff; font-size: 12px; font-weight: 600;"
        )
        toolbar.addWidget(self.lbl_match_progress)

        layout.addLayout(toolbar)

        # ── 上半部分：左右双栏文件列表 ──
        lists_splitter = QSplitter(Qt.Horizontal)

        self.invoice_panel = FileListPanel(kind="invoice", store=self.store)
        lists_splitter.addWidget(self.invoice_panel)

        self.payment_panel = FileListPanel(kind="payment", store=self.store)
        lists_splitter.addWidget(self.payment_panel)

        lists_splitter.setSizes([500, 500])
        layout.addWidget(lists_splitter, stretch=2)

        # ── 下半部分：双预览区 ──
        preview_splitter = QSplitter(Qt.Horizontal)

        self.invoice_preview = PreviewView(title="发票预览")
        preview_splitter.addWidget(self.invoice_preview)

        self.payment_preview = PreviewView(title="支付记录预览")
        preview_splitter.addWidget(self.payment_preview)

        preview_splitter.setSizes([500, 500])
        layout.addWidget(preview_splitter, stretch=3)

        # ── 底部关联操作按钮 ──
        btn_bar = QHBoxLayout()
        btn_bar.setAlignment(Qt.AlignCenter)
        btn_bar.setSpacing(16)

        self.btn_link = MkButton("关联选中项", type="primary")
        self.btn_link.setEnabled(False)
        self.btn_link.clicked.connect(self._on_link)
        btn_bar.addWidget(self.btn_link)

        self.btn_unlink = MkButton("取消关联", type="default")
        self.btn_unlink.setEnabled(False)
        self.btn_unlink.clicked.connect(self._on_unlink)
        btn_bar.addWidget(self.btn_unlink)

        self.btn_rename = MkButton("重命名关联", type="default")
        self.btn_rename.setEnabled(False)
        self.btn_rename.setToolTip("将关联的发票与支付记录重命名为统一名称")
        self.btn_rename.clicked.connect(self._on_rename)
        btn_bar.addWidget(self.btn_rename)

        layout.addLayout(btn_bar)

    def _connect_signals(self):
        """连接信号。"""
        self.invoice_panel.fileSelected.connect(self._on_invoice_selected)
        self.payment_panel.fileSelected.connect(self._on_payment_selected)
        self.invoice_panel.locateAllRequested.connect(
            self._on_locate_all_from_invoice
        )
        self.payment_panel.locateAllRequested.connect(
            self._on_locate_all_from_payment
        )
        self.invoice_panel.locateFileRequested.connect(
            self._on_locate_file_from_invoice
        )
        self.payment_panel.locateFileRequested.connect(
            self._on_locate_file_from_payment
        )

        self.invoice_panel.selectionChanged.connect(self._update_link_buttons)
        self.payment_panel.selectionChanged.connect(self._update_link_buttons)
        self.invoice_panel.combosChanged.connect(self._on_combos_changed)
        self.payment_panel.combosChanged.connect(self._on_combos_changed)

        if self.store:
            self.store.on_changed(self._on_store_changed)

    def _restore_state(self):
        """恢复上次保存的文件夹。"""
        self.invoice_panel.restore_folder()
        self.payment_panel.restore_folder()

    # ── 文件选择回调 ──────────────────────────────────────

    def _on_invoice_selected(self, file_id: str):
        """发票选中：渲染 PDF 预览。"""
        invoice = self.invoice_panel.get_selected_file()
        if invoice:
            self.invoice_preview.set_pdf(invoice.abs_path)
        self._update_link_buttons()

    def _on_payment_selected(self, file_id: str):
        """支付记录选中：显示图片预览。"""
        payment = self.payment_panel.get_selected_file()
        if payment:
            pixmap = QPixmap(payment.abs_path)
            if not pixmap.isNull():
                self.payment_preview.set_pixmap(pixmap)
        self._update_link_buttons()

    # ── 关联文件定位 ──────────────────────────────────────

    def _on_locate_all_from_invoice(self, _source_file_id: str,
                                    payment_ids: list):
        """发票侧定位所有：支付侧仅显示关联支付记录。"""
        self.payment_panel.set_located_files(payment_ids)

    def _on_locate_all_from_payment(self, _source_file_id: str,
                                    invoice_ids: list):
        """支付侧定位所有：发票侧仅显示关联发票。"""
        self.invoice_panel.set_located_files(invoice_ids)

    def _on_locate_file_from_invoice(self, payment_id: str):
        """发票子行定位文件：支付侧选中并滚动到目标记录。"""
        self.payment_panel.locate_file(payment_id)

    def _on_locate_file_from_payment(self, invoice_id: str):
        """支付子行定位文件：发票侧选中并滚动到目标发票。"""
        self.invoice_panel.locate_file(invoice_id)

    def _update_link_buttons(self):
        """更新关联按钮状态（支持 组合↔文件 / 组合↔组合）。"""
        inv = self.invoice_panel.get_selected_file()
        pay = self.payment_panel.get_selected_file()
        inv_combo = self.invoice_panel.get_selected_combo()
        pay_combo = self.payment_panel.get_selected_combo()

        both_selected = (inv or inv_combo) is not None and (pay or pay_combo) is not None
        self.btn_link.setEnabled(both_selected)

        # 取消关联/重命名仅对「单文件↔单文件」生效
        single_pair = inv is not None and pay is not None
        if single_pair and self.store:
            linked = self.store.is_linked(inv.file_id, pay.file_id)
            self.btn_unlink.setEnabled(linked)
            self.btn_rename.setEnabled(linked)
        else:
            self.btn_unlink.setEnabled(False)
            self.btn_rename.setEnabled(False)

    def _on_review_toggled(self, checked: bool):
        """审阅模式开关切换。"""
        self._review_mode = checked
        if checked:
            self.btn_auto_match.setText("自动比对")
            self.btn_auto_match.setToolTip("弹出关联组审阅界面：自动识别金额匹配项，人工调整后批量确认")
        else:
            self.btn_auto_match.setText("一键自动关联")
            self.btn_auto_match.setToolTip("自动关联所有金额相同的发票与支付记录")

    # ── 自动比对 ──────────────────────────────────────────

    def _on_auto_match(self):
        """自动比对入口：根据审阅模式分派不同逻辑。"""
        if not self.store:
            MkMessage.warning(self, "数据未初始化")
            return

        # 获取金额匹配的对
        self._match_pairs = self.store.get_amount_matches()

        if not self._match_pairs:
            MkMessage.success(self, "未找到金额匹配的未关联配对。\n请先在「计算金额模式」中为发票和支付记录完成 OCR 识别。")
            self.lbl_match_progress.setText("")
            return

        if self._review_mode:
            self._open_auto_match_dialog()
        else:
            self._start_auto_link_mode()

    def _open_auto_match_dialog(self):
        """审阅模式：弹出模态二级界面，确认后批量自动关联。"""
        dialog = AutoMatchDialog(self._match_pairs, store=self.store, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._match_pairs = []
            self.lbl_match_progress.setText("")
            return

        pairs = dialog.accepted_pairs()
        total = len(pairs)
        count = self.store.batch_link(pairs, auto_linked=True)
        self._match_pairs = []
        self.btn_link.setText("关联选中项")
        self.btn_link.setEnabled(False)
        self.lbl_match_progress.setText(
            f"自动比对已保存：{count} / {total} 对"
        )

        if count > 0:
            MkMessage.success(
                self,
                f"自动比对已保存，成功关联 {count} / {total} 对。",
            )
        else:
            MkMessage.warning(self, "没有新增关联，可能这些配对已被关联。")

        self._update_link_buttons()

    def _on_link(self):
        """手动关联选中的发票与支付记录（支持组合↔文件 / 组合↔组合批量关联）。"""
        inv_combo = self.invoice_panel.get_selected_combo()
        pay_combo = self.payment_panel.get_selected_combo()
        inv = self.invoice_panel.get_selected_file()
        pay = self.payment_panel.get_selected_file()

        inv_ids = list(inv_combo["file_ids"]) if inv_combo else (
            [inv.file_id] if inv else []
        )
        pay_ids = list(pay_combo["file_ids"]) if pay_combo else (
            [pay.file_id] if pay else []
        )
        if not inv_ids or not pay_ids:
            return

        total = len(inv_ids) * len(pay_ids)
        count = self.store.batch_link(
            [{"invoice_ids": inv_ids, "payment_ids": pay_ids}],
            auto_linked=False,
        )
        if count > 0:
            if not inv_combo and not pay_combo:
                MkMessage.success(self, f"已关联：{inv.file_name} ↔ {pay.file_name}")
            else:
                label = "组合" if (inv_combo or pay_combo) else "文件"
                MkMessage.success(
                    self, f"已关联：{label} ↔ {label}，成功 {count} / {total} 对",
                )
        else:
            MkMessage.warning(
                self, "没有新增关联，可能这些文件已经关联过了。",
            )
        self._update_link_buttons()

    def _start_auto_link_mode(self):
        """一键自动关联模式：批量关联所有金额匹配对，并添加标记。"""
        if not self._match_pairs:
            return

        total = len(self._match_pairs)
        count = self.store.batch_link(self._match_pairs, auto_linked=True)

        self.lbl_match_progress.setText(
            f"自动关联完成：{count} / {total} 对"
        )

        if count > 0:
            MkMessage.success(
                self,
                f"一键自动关联完成！\n"
                f"成功关联 {count} 对（共 {total} 对候选）。\n"
                f"自动关联的文件已在列表中标记。",
            )
        else:
            MkMessage.warning(self, "未能关联任何配对，可能已被关联。")

        self._match_pairs = []
        self._update_link_buttons()

    # ── 关联操作（手动）────────────────────────────────────

    def _on_unlink(self):
        """取消关联。"""
        inv = self.invoice_panel.get_selected_file()
        pay = self.payment_panel.get_selected_file()
        if not inv or not pay:
            return

        if self.store.remove_association(inv.file_id, pay.file_id):
            MkMessage.success(self, f"已取消关联：{inv.file_name} ↔ {pay.file_name}")
            self._update_link_buttons()
        else:
            MkMessage.error(self, "取消关联失败")

    def _on_rename(self):
        """重命名关联文件：将发票与支付记录统一命名。"""
        inv = self.invoice_panel.get_selected_file()
        pay = self.payment_panel.get_selected_file()
        if not inv or not pay or not self.store:
            return

        # 默认名：发票文件名去扩展名
        default_name = inv.file_name
        if "." in default_name:
            default_name = default_name.rsplit(".", 1)[0]

        new_name, ok = QInputDialog.getText(
            self, "重命名关联文件",
            "请输入统一名称（不含扩展名）：",
            text=default_name,
        )
        if not ok or not new_name or not new_name.strip():
            return

        new_name = new_name.strip()
        # 过滤非法文件名字符
        for ch in r'<>:"/\|?*':
            new_name = new_name.replace(ch, "_")

        if not new_name:
            return

        result = self.store.rename_linked_files(
            inv.file_id, pay.file_id, new_name,
        )

        if result:
            inv_name, pay_name = result
            MkMessage.success(
                self,
                f"重命名成功！\n发票：{inv_name}\n支付记录：{pay_name}",
            )
            # 刷新两个面板
            self.invoice_panel.restore_folder()
            self.payment_panel.restore_folder()
        else:
            MkMessage.error(
                self, "重命名失败，可能目标文件已存在或文件被占用。"
            )

    def _on_combos_changed(self):
        """组合增删后：两侧面板重建树（保持层级与金额最新）。"""
        self.invoice_panel.reload_from_store()
        self.payment_panel.reload_from_store()
        self._update_link_buttons()

    def _on_store_changed(self):
        """Store 数据变更时刷新两个列表面板的状态徽标。"""
        self.invoice_panel.refresh_status()
        self.payment_panel.refresh_status()
        self._update_link_buttons()

    def on_page_activated(self):
        """页面激活时刷新状态。"""
        self._on_store_changed()
