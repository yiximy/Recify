# -*- coding: utf-8 -*-
"""金额计算页：OCR识别 + 金额编辑 + 汇总计算 + 实时预览 + 金额筛选 + 类型选择"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QColor, QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QHeaderView,
    QSplitter,
    QButtonGroup,
    QRadioButton,
)
from monkeyqt import MkButton, MkTable, MkCard, MkProgressBar, MkMessage, MkInput

from app.ui.widgets.folder_picker import FolderPicker
from app.ui.widgets.amount_edit_cell import AmountEditCell
from app.ui.widgets.confirm_checkbox import ConfirmCheckBox
from app.ui.widgets.preview_view import PreviewView
from app.ui.widgets.table_utils import enable_smooth_scroll
from app.core.file_scanner import FileScanner
from app.workers.ocr_worker import OcrWorker


# 低置信度阈值：低于此值标橙色提示用户复核
LOW_CONFIDENCE = 0.8

# 表格行高下限：确保编辑输入框完整显示，不被截断（实际按输入框高度自适应）
ROW_HEIGHT = 46

# 编辑金额列宽：足以完整显示较大金额（含 "99999999.99" 级别）
EDIT_COL_WIDTH = 180
# 确认列宽：仅放一个居中复选框
CONFIRM_COL_WIDTH = 70
# 表格最小高度下限：仅作收缩地板，实际列表占左侧 80%
TABLE_MIN_HEIGHT = 120


class AmountPage(QWidget):
    """计算金额模式页面。

    支持两种文件类型：
    - 图片（支付记录截图）：OCR 识别支付金额
    - 发票（PDF）：渲染页面后 OCR 识别合计金额

    布局：
        ┌─────────────────────────────────────────────────┐
        │ ○ 发票  ○ 图片                                  │
        │ [文件夹] [开始OCR] [重新识别]                     │
        │ [金额范围: min~max] [筛选] [重置] [全选] [取消]   │
        ├──────────────────────────┬──────────────────────┤
        │ 文件列表（上，占 80%）    │                      │
        │ 文件名|识别金额|编辑金额|确认│  预览区（完整高度）  │
        ├──────────────────────────┤  截图实时预览         │
        │ 汇总区（下，占 20%）      │  缩放控制             │
        │ ¥总额  已确认N/M  [计算总额]│                      │
        └──────────────────────────┴──────────────────────┘
    """

    def __init__(self, store=None, parent=None):
        super().__init__(parent)
        self.store = store

        # 当前文件类型："image"（支付截图）| "pdf"（发票）
        self._file_type = "image"

        # 全部文件（从 Store 加载）
        self._files: list = []
        # 筛选后的文件（表格显示用）
        self._filtered_files: list = []
        # 筛选条件
        self._filter_min: Optional[float] = None
        self._filter_max: Optional[float] = None

        # file_id → 行索引（基于当前筛选视图）
        self._fid_to_row: dict = {}
        # abs_path → file_id（OCR 结果回填用，基于全部记录）
        self._path_to_fid: dict = {}
        # file_id → AmountEditCell
        self._edit_cells: dict = {}
        # file_id → MkCheckBox
        self._confirm_checks: dict = {}

        self._ocr_worker: Optional[OcrWorker] = None
        # 程序化刷新时屏蔽，避免回环
        self._suppress = False
        # 左侧上下分栏是否已在首次显示时均分
        self._left_balanced = False

        self._build_ui()
        self._connect_signals()
        self._restore_folder()

    # ── UI 构建 ────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ── 第0行：类型选择（发票 / 图片）──
        type_bar = QHBoxLayout()
        type_bar.setSpacing(16)

        lbl_type = QLabel("识别类型：")
        lbl_type.setStyleSheet("color: #606266; font-size: 13px; font-weight: 600;")
        type_bar.addWidget(lbl_type)

        self.type_group = QButtonGroup(self)
        self.radio_image = QRadioButton("图片")
        self.radio_invoice = QRadioButton("发票")
        self.radio_image.setChecked(True)

        radio_style = """
            QRadioButton {
                color: #303133;
                font-size: 13px;
                spacing: 4px;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
            }
            QRadioButton::indicator:unchecked {
                border: 2px solid #dcdfe6;
                border-radius: 10px;
                background: #ffffff;
            }
            QRadioButton::indicator:checked {
                border: 2px solid #409eff;
                border-radius: 10px;
                background: qradialgradient(
                    cx:0.5, cy:0.5, radius:0.35,
                    fx:0.5, fy:0.5,
                    stop:0 #409eff, stop:1 #ffffff
                );
            }
        """
        self.radio_image.setStyleSheet(radio_style)
        self.radio_invoice.setStyleSheet(radio_style)

        self.type_group.addButton(self.radio_image, 0)
        self.type_group.addButton(self.radio_invoice, 1)
        type_bar.addWidget(self.radio_image)
        type_bar.addWidget(self.radio_invoice)
        type_bar.addStretch()

        layout.addLayout(type_bar)

        # ── 第1行：文件夹 + OCR 按钮 ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.folder_picker = FolderPicker(label="支付记录文件夹")
        toolbar.addWidget(self.folder_picker, stretch=1)

        self.btn_ocr = MkButton("开始OCR识别", type="primary")
        self.btn_ocr.setEnabled(False)
        self.btn_ocr.clicked.connect(self._on_ocr_all)
        toolbar.addWidget(self.btn_ocr)

        self.btn_reocr = MkButton("重新识别未确认", type="default")
        self.btn_reocr.setEnabled(False)
        self.btn_reocr.clicked.connect(self._on_reocr_unconfirmed)
        toolbar.addWidget(self.btn_reocr)

        layout.addLayout(toolbar)

        # ── 第2行：金额筛选 + 批量选择 ──
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)

        lbl_filter = QLabel("金额范围：")
        lbl_filter.setStyleSheet("color: #606266; font-size: 13px;")
        filter_bar.addWidget(lbl_filter)

        self.input_min = MkInput(placeholder="最低")
        self.input_min.setFixedWidth(100)
        self.input_min.setAlignment(Qt.AlignCenter)
        filter_bar.addWidget(self.input_min)

        lbl_sep = QLabel("~")
        lbl_sep.setStyleSheet("color: #909399;")
        filter_bar.addWidget(lbl_sep)

        self.input_max = MkInput(placeholder="最高")
        self.input_max.setFixedWidth(100)
        self.input_max.setAlignment(Qt.AlignCenter)
        filter_bar.addWidget(self.input_max)

        self.btn_filter = MkButton("筛选", type="default")
        self.btn_filter.clicked.connect(self._on_apply_filter)
        filter_bar.addWidget(self.btn_filter)

        self.btn_reset_filter = MkButton("重置", type="default")
        self.btn_reset_filter.clicked.connect(self._on_reset_filter)
        filter_bar.addWidget(self.btn_reset_filter)

        filter_bar.addStretch()

        self.lbl_filter_status = QLabel("")
        self.lbl_filter_status.setStyleSheet("color: #909399; font-size: 12px;")
        filter_bar.addWidget(self.lbl_filter_status)

        self.btn_select_all = MkButton("全选", type="default")
        self.btn_select_all.clicked.connect(self._on_select_all)
        filter_bar.addWidget(self.btn_select_all)

        self.btn_deselect_all = MkButton("取消全选", type="default")
        self.btn_deselect_all.clicked.connect(self._on_deselect_all)
        filter_bar.addWidget(self.btn_deselect_all)

        layout.addLayout(filter_bar)

        # ── 进度区（默认隐藏）──
        self.progress_bar = MkProgressBar(percentage=0, status="normal")
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #909399; font-size: 12px;")
        self.lbl_status.setVisible(False)
        layout.addWidget(self.lbl_status)

        # ── 主体：左右分栏（QSplitter 可拖拽调整）──
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #ebeef5; }"
            "QSplitter::handle:hover { background: #409eff; }"
        )

        # 左侧：表格（上）+ 汇总（下），列表占 80%、汇总占 20%
        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.setHandleWidth(6)
        left_splitter.setStyleSheet(
            "QSplitter::handle { background: #ebeef5; }"
            "QSplitter::handle:hover { background: #409eff; }"
        )

        # 文件列表表格
        self.table = MkTable()
        self.table.set_headers(["文件名", "识别金额", "编辑金额", "确认"])
        enable_smooth_scroll(self.table)
        self.table.setMinimumHeight(TABLE_MIN_HEIGHT)
        self._configure_columns()
        self.table.setStyleSheet(
            self.table.styleSheet() + " QTableWidget::item { padding: 3px 6px; }"
        )
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.table.currentCellChanged.connect(self._on_row_changed)
        left_splitter.addWidget(self.table)

        # 汇总区（占左侧 20%，紧凑单行）
        self.summary_card = MkCard(title="汇总")
        self._build_summary(self.summary_card.content_layout)
        left_splitter.addWidget(self.summary_card)

        left_splitter.setChildrenCollapsible(False)
        left_splitter.setStretchFactor(0, 4)
        left_splitter.setStretchFactor(1, 1)
        left_splitter.setSizes([480, 120])
        self._left_splitter = left_splitter

        splitter.addWidget(left_splitter)

        # 右侧：预览区（占完整垂直高度）
        self.preview_view = PreviewView(title="预览")
        self._show_preview_empty_state()
        splitter.addWidget(self.preview_view)

        splitter.setStretchFactor(0, 55)
        splitter.setStretchFactor(1, 45)
        splitter.setSizes([560, 460])
        self._splitter = splitter
        layout.addWidget(splitter, stretch=1)

    def _build_summary(self, content_layout):
        """构建紧凑汇总条：已确认总额 + 已确认计数 + 计算总额。"""
        row = QHBoxLayout()
        row.setSpacing(12)

        lbl_total_title = QLabel("已确认总额：")
        lbl_total_title.setStyleSheet("font-size: 13px; color: #606266;")
        row.addWidget(lbl_total_title)

        self.lbl_total = QLabel("¥ 0.00")
        total_font = QFont("Microsoft YaHei UI", 16, QFont.Weight.Bold)
        self.lbl_total.setFont(total_font)
        self.lbl_total.setStyleSheet("color: #409eff;")
        row.addWidget(self.lbl_total)

        row.addSpacing(16)

        self.lbl_confirmed_count = QLabel("已确认 0 / 0 项")
        self.lbl_confirmed_count.setStyleSheet("color: #606266; font-size: 12px;")
        row.addWidget(self.lbl_confirmed_count)

        row.addStretch()

        self.btn_calculate = MkButton("计算总额", type="primary")
        self.btn_calculate.clicked.connect(self._on_calculate)
        row.addWidget(self.btn_calculate)

        content_layout.addLayout(row)

    def _configure_columns(self):
        """设定各列尺寸策略。"""
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(70)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.setColumnWidth(2, EDIT_COL_WIDTH)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, CONFIRM_COL_WIDTH)

    def showEvent(self, event):
        """首次显示时精确调整左侧分栏比例。"""
        super().showEvent(event)
        if not self._left_balanced:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._balance_left_split)

    def _balance_left_split(self):
        """将左侧竖直分栏按 80:20 分配。"""
        splitter = getattr(self, "_left_splitter", None)
        if splitter is None:
            return
        h = splitter.height()
        if h <= 0:
            return
        top = int(h * 0.8)
        splitter.setSizes([top, h - top])
        self._left_balanced = True

    def _connect_signals(self):
        """连接信号。"""
        self.folder_picker.folderChanged.connect(self._on_folder_changed)
        if self.store:
            self.store.on_changed(self._on_store_changed)
        self.type_group.buttonClicked.connect(self._on_type_changed)

    def _restore_folder(self):
        """恢复上次保存的文件夹。"""
        if self.store:
            kind = "payment" if self._file_type == "image" else "invoice"
            path = self.store.get_folder(kind)
            if path:
                self.folder_picker.set_path(path)
                self._scan_and_load(path)

    # ── 类型切换 ──────────────────────────────────────────

    def _on_type_changed(self, button):
        """文件类型切换（发票/图片）。"""
        new_type = "pdf" if button is self.radio_invoice else "image"
        if new_type == self._file_type:
            return
        self._file_type = new_type

        # 更新文件夹选择器标题
        kind = "payment" if new_type == "image" else "invoice"
        label = "支付记录文件夹" if new_type == "image" else "发票文件夹"
        self.folder_picker.set_label(label)

        # 切换预览标题
        preview_title = "支付记录预览" if new_type == "image" else "发票预览"
        self.preview_view.lbl_title.setText(preview_title)

        # 加载对应文件夹的文件
        self._restore_by_type()

    def _restore_by_type(self):
        """根据当前文件类型恢复文件夹和文件列表。"""
        kind = "payment" if self._file_type == "image" else "invoice"
        if self.store:
            path = self.store.get_folder(kind)
            if path:
                self.folder_picker.set_path(path)
                self._scan_and_load(path)
            else:
                # 清空当前显示
                self.folder_picker.clear()
                self._files = []
                self._filtered_files = []
                self._populate_table()
                self._update_summary()
                self.btn_ocr.setEnabled(False)
                self.btn_reocr.setEnabled(False)

    # ── 文件夹与扫描 ────────────────────────────────────────

    def _on_folder_changed(self, folder: str):
        """文件夹变化时扫描。"""
        kind = "payment" if self._file_type == "image" else "invoice"
        if self.store:
            self.store.set_folder(kind, folder)
        self._scan_and_load(folder)

    def _scan_and_load(self, folder: str):
        """扫描文件夹并加载文件列表。"""
        if self._file_type == "image":
            files = FileScanner.scan_payments(folder)
            if self.store:
                self.store.merge_payments(files)
                files = self.store.get_payments()
        else:
            files = FileScanner.scan_invoices(folder)
            if self.store:
                self.store.merge_invoices(files)
                files = self.store.get_invoices()

        self._files = files
        self._path_to_fid = {f.abs_path: f.file_id for f in self._files}
        self._apply_filter_and_populate()
        self._update_summary()

        has_files = len(files) > 0
        self.btn_ocr.setEnabled(has_files and self._ocr_worker is None)
        self.btn_reocr.setEnabled(has_files and self._ocr_worker is None)

    # ── 金额筛选 ──────────────────────────────────────────

    def _get_filtered_files(self) -> list:
        """根据当前筛选条件返回过滤后的文件。"""
        if self._filter_min is None and self._filter_max is None:
            return list(self._files)

        result = []
        for f in self._files:
            amt = self._get_file_amount(f)
            if amt is None:
                continue
            if self._filter_min is not None and amt < self._filter_min:
                continue
            if self._filter_max is not None and amt > self._filter_max:
                continue
            result.append(f)
        return result

    @staticmethod
    def _get_file_amount(f) -> Optional[float]:
        """获取文件的最终金额。"""
        return f.amount.final_amount if f.amount else None

    def _apply_filter_and_populate(self):
        """应用筛选条件并重建表格。"""
        self._filtered_files = self._get_filtered_files()
        self._populate_table()
        self._update_filter_status()

    def _update_filter_status(self):
        """更新筛选状态标签。"""
        if self._filter_min is not None or self._filter_max is not None:
            self.lbl_filter_status.setText(
                f"已筛选 {len(self._filtered_files)} / {len(self._files)} 项"
            )
        else:
            self.lbl_filter_status.setText("")

    def _on_apply_filter(self):
        """应用金额范围筛选。"""
        min_text = self.input_min.text().strip()
        max_text = self.input_max.text().strip()

        self._filter_min = None
        self._filter_max = None

        try:
            if min_text:
                self._filter_min = float(min_text.replace(",", "").replace("，", ""))
            if max_text:
                self._filter_max = float(max_text.replace(",", "").replace("，", ""))
        except ValueError:
            MkMessage.warning(self, "金额范围输入无效，请输入数字")
            return

        if (
            self._filter_min is not None
            and self._filter_max is not None
            and self._filter_min > self._filter_max
        ):
            MkMessage.warning(self, "最低金额不能大于最高金额")
            return

        self._apply_filter_and_populate()

    def _on_reset_filter(self):
        """重置筛选条件，显示全部记录。"""
        self._filter_min = None
        self._filter_max = None
        self.input_min.clear()
        self.input_max.clear()
        self._apply_filter_and_populate()

    def _on_select_all(self):
        """全选：仅勾选当前筛选结果中的记录。"""
        self._set_all_confirmed(True)

    def _on_deselect_all(self):
        """取消全选：仅取消当前筛选结果中的记录。"""
        self._set_all_confirmed(False)

    def _set_all_confirmed(self, checked: bool):
        """批量设置筛选结果的确认态。"""
        if not self._filtered_files:
            return
        self._suppress = True
        for f in self._filtered_files:
            check = self._confirm_checks.get(f.file_id)
            if check and check.isChecked() != checked:
                check.setChecked(checked)
            self._set_file_confirmed(f.file_id, checked)
        self._suppress = False
        self._reload_files_from_store()
        self._update_summary()

    def _set_file_confirmed(self, file_id: str, confirmed: bool):
        """根据文件类型调用对应的 Store 方法设置确认态。"""
        if not self.store:
            return
        if self._file_type == "image":
            self.store.set_amount(file_id, is_confirmed=confirmed)
        else:
            self.store.set_invoice_amount(file_id, is_confirmed=confirmed)

    def _reload_files_from_store(self):
        """Reload _files and _path_to_fid from Store."""
        if not self.store:
            return
        if self._file_type == "image":
            self._files = self.store.get_payments()
        else:
            self._files = self.store.get_invoices()
        self._path_to_fid = {f.abs_path: f.file_id for f in self._files}

    # ── 表格填充 ────────────────────────────────────────────

    def _populate_table(self):
        """填充表格数据。"""
        self._suppress = True
        self.table.setRowCount(0)
        self._fid_to_row.clear()
        self._edit_cells.clear()
        self._confirm_checks.clear()

        if not self._filtered_files:
            self._show_preview_empty_state()
            self._suppress = False
            return

        # 构造行数据
        rows = []
        for f in self._filtered_files:
            amount = self._get_file_amount(f)
            recognized_text = f"{amount:.2f}" if amount is not None else "—"
            rows.append([f.file_name, recognized_text, "", ""])

        self.table.set_data(rows)

        # 放置单元格组件
        for row_idx, f in enumerate(self._filtered_files):
            self._fid_to_row[f.file_id] = row_idx
            amount = self._get_file_amount(f)
            confidence = self._get_file_confidence(f)

            # 低置信度标橙
            if amount is not None and confidence < LOW_CONFIDENCE:
                item = self.table.item(row_idx, 1)
                if item:
                    item.setForeground(QColor("#e6a23c"))

            # 编辑金额单元格
            edit_cell = AmountEditCell(f.file_id, amount)
            edit_cell.committed.connect(self._on_amount_committed)
            self._edit_cells[f.file_id] = edit_cell
            self.table.setCellWidget(row_idx, 2, edit_cell)

            # 确认复选框
            is_confirmed = self._get_file_is_confirmed(f)
            check = ConfirmCheckBox()
            check.setChecked(is_confirmed)
            check.stateChanged.connect(
                lambda state, fid=f.file_id: self._on_confirm_toggled(fid, state)
            )
            self._confirm_checks[f.file_id] = check
            wrap = QWidget()
            wl = QHBoxLayout(wrap)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.addWidget(check)
            wl.setAlignment(Qt.AlignCenter)
            self.table.setCellWidget(row_idx, 3, wrap)

            row_h = max(ROW_HEIGHT, edit_cell.sizeHint().height() + 4)
            self.table.setRowHeight(row_idx, row_h)

        self._configure_columns()
        self._suppress = False

    @staticmethod
    def _get_file_confidence(f) -> float:
        """获取文件 OCR 置信度。"""
        return f.amount.confidence if f.amount else 0.0

    @staticmethod
    def _get_file_is_confirmed(f) -> bool:
        """获取文件确认态。"""
        return f.amount.is_confirmed if f.amount else False

    # ── 预览交互 ──────────────────────────────────────────

    def _show_preview_empty_state(self):
        """预览区空状态。"""
        self.preview_view.clear()
        default_title = "支付记录预览" if self._file_type == "image" else "发票预览"
        self.preview_view.lbl_title.setText(default_title)
        self.preview_view.graphics_view.setStyleSheet(
            """
            QGraphicsView {
                background: #f5f7fa;
                border: 1px dashed #dcdfe6;
                border-radius: 6px;
            }
            """
        )

    def _on_row_changed(self, current_row, _prev_row, _col, _prev_col):
        """表格行选择变化：实时更新预览区。"""
        if current_row < 0 or current_row >= len(self._filtered_files):
            self._show_preview_empty_state()
            return
        f = self._filtered_files[current_row]
        self._update_preview(f.abs_path, f.file_name)

    def _update_preview(self, abs_path: str, file_name: str):
        """更新预览区。"""
        if self._file_type == "pdf":
            # PDF 文件使用 PDF 预览
            self.preview_view.graphics_view.setStyleSheet(
                """
                QGraphicsView {
                    background: #f5f7fa;
                    border: 1px solid #e4e7ed;
                    border-radius: 6px;
                }
                """
            )
            self.preview_view.lbl_title.setText(f"预览：{file_name}")
            self.preview_view.set_pdf(abs_path)
        else:
            pix = QPixmap(abs_path)
            if pix.isNull():
                self.preview_view.clear()
                self.preview_view.lbl_title.setText(f"预览：{file_name}（加载失败）")
                return
            self.preview_view.graphics_view.setStyleSheet(
                """
                QGraphicsView {
                    background: #f5f7fa;
                    border: 1px solid #e4e7ed;
                    border-radius: 6px;
                }
                """
            )
            self.preview_view.lbl_title.setText(f"预览：{file_name}")
            self.preview_view.set_pixmap(pix)

    # ── OCR 操作 ───────────────────────────────────────────

    def _on_ocr_all(self):
        """对所有文件执行 OCR。"""
        self._start_ocr([f.abs_path for f in self._files])

    def _on_reocr_unconfirmed(self):
        """仅对未确认的文件重新 OCR。"""
        paths = [
            f.abs_path for f in self._files
            if not self._get_file_is_confirmed(f)
        ]
        if not paths:
            MkMessage.success(self, "没有需要重新识别的未确认项")
            return
        self._start_ocr(paths)

    def _start_ocr(self, paths: list[str]):
        """启动 OCR 工作线程。"""
        if self._ocr_worker is not None:
            MkMessage.warning(self, "OCR 正在进行中，请稍候")
            return
        if not paths:
            MkMessage.warning(self, "没有可识别的文件")
            return

        self.progress_bar.setVisible(True)
        self.lbl_status.setVisible(True)
        self.progress_bar.percentage = 0
        self.lbl_status.setText("准备中...")
        self.btn_ocr.setEnabled(False)
        self.btn_reocr.setEnabled(False)

        self._ocr_worker = OcrWorker(paths, file_type=self._file_type)
        self._ocr_worker.progress.connect(self._on_ocr_progress)
        self._ocr_worker.finished_ok.connect(self._on_ocr_finished)
        self._ocr_worker.failed.connect(self._on_ocr_failed)
        self._ocr_worker.start()

    def _on_ocr_progress(self, current: int, total: int, message: str):
        """OCR 进度回调。"""
        percent = int(current / total * 100) if total > 0 else 0
        self.progress_bar.percentage = percent
        self.lbl_status.setText(f"({current}/{total}) {message}")

    def _on_ocr_finished(self, result_map: dict):
        """OCR 完成回调：回填识别金额到 Store 与表格。"""
        self._suppress = True
        updated = 0
        for path, info in result_map.items():
            fid = self._path_to_fid.get(path)
            if not fid:
                continue
            candidate = info.get("candidate")
            raw_texts = info.get("raw_texts", [])
            row_idx = self._fid_to_row.get(fid)

            recognized = candidate.value if candidate else None
            confidence = candidate.confidence if candidate else 0.0

            # 写入 Store（根据文件类型使用不同的方法）
            if self._file_type == "image":
                self.store.set_amount(
                    fid,
                    recognized=recognized,
                    raw_texts=raw_texts,
                    confidence=confidence,
                )
            else:
                self.store.set_invoice_amount(
                    fid,
                    recognized=recognized,
                    raw_texts=raw_texts,
                    confidence=confidence,
                )

            # 更新可见行的表格显示
            if row_idx is not None:
                item = self.table.item(row_idx, 1)
                if item:
                    if recognized is not None:
                        item.setText(f"{recognized:.2f}")
                        if confidence < LOW_CONFIDENCE:
                            item.setForeground(QColor("#e6a23c"))
                        else:
                            item.setForeground(QColor("#303133"))
                    else:
                        item.setText("—")
                        item.setForeground(QColor("#c0c4cc"))

                edit_cell = self._edit_cells.get(fid)
                if (
                    edit_cell
                    and edit_cell.get_value() is None
                    and recognized is not None
                ):
                    edit_cell.set_value(recognized)
                    if self._file_type == "image":
                        self.store.set_amount(fid, edited=recognized)
                    else:
                        self.store.set_invoice_amount(fid, edited=recognized)

            updated += 1

        self._suppress = False
        self._reload_files_from_store()
        self._finish_ocr_ui()
        MkMessage.success(self, f"OCR 完成，共识别 {updated} 个文件")

    def _on_ocr_failed(self, message: str):
        """OCR 失败回调。"""
        self._finish_ocr_ui()
        MkMessage.error(self, f"OCR 失败：{message}")

    def _finish_ocr_ui(self):
        """恢复 OCR 按钮与进度区状态。"""
        self.progress_bar.setVisible(False)
        self.lbl_status.setVisible(False)
        self.btn_ocr.setEnabled(len(self._files) > 0)
        self.btn_reocr.setEnabled(len(self._files) > 0)
        self._ocr_worker = None
        self._update_summary()

    # ── 编辑与确认 ──────────────────────────────────────────

    def _on_amount_committed(self, file_id: str, value):
        """金额编辑提交。"""
        if self._suppress or not self.store:
            return
        if self._file_type == "image":
            self.store.set_amount(file_id, edited=value)
        else:
            self.store.set_invoice_amount(file_id, edited=value)
        if value is not None:
            check = self._confirm_checks.get(file_id)
            if check and not check.isChecked():
                check.setChecked(True)

    def _on_confirm_toggled(self, file_id: str, state: int):
        """确认复选框切换。"""
        if self._suppress or not self.store:
            return
        checked = state == 2
        self._set_file_confirmed(file_id, checked)
        self._update_summary()

    # ── 汇总计算 ────────────────────────────────────────────

    def _on_calculate(self):
        """计算已确认金额总额。"""
        self._update_summary()

    def _update_summary(self):
        """刷新汇总条。"""
        if not self.store:
            return
        confirmed = self._get_confirmed_amounts()
        total = round(sum(amt for _, _, amt in confirmed), 2)

        self.lbl_total.setText(f"¥ {total:.2f}")
        self.lbl_confirmed_count.setText(
            f"已确认 {len(confirmed)} / {len(self._files)} 项"
        )

    def _get_confirmed_amounts(self) -> list[tuple]:
        """获取已确认金额列表（兼容发票和支付记录）。"""
        if not self.store:
            return []
        if self._file_type == "image":
            return self.store.get_confirmed_amounts()
        else:
            # 从发票数据中提取已确认的金额
            result = []
            for f in self._files:
                if self._get_file_is_confirmed(f):
                    amt = self._get_file_amount(f)
                    if amt is not None:
                        result.append((f.file_id, f.file_name, amt))
            return result

    # ── Store 变更与页面激活 ────────────────────────────────

    def _on_store_changed(self):
        """Store 变更时刷新汇总与筛选视图。"""
        if self._suppress:
            return
        if self.store:
            if self._file_type == "image":
                self._files = self.store.get_payments()
            else:
                self._files = self.store.get_invoices()
            self._path_to_fid = {f.abs_path: f.file_id for f in self._files}
            # 重新应用筛选，保持 _filtered_files 与 _files 一致
            self._filtered_files = self._get_filtered_files()
        self._update_summary()

    def on_page_activated(self):
        """页面激活时刷新数据。"""
        if self.store:
            if self._file_type == "image":
                self._files = self.store.get_payments()
            else:
                self._files = self.store.get_invoices()
            self._path_to_fid = {f.abs_path: f.file_id for f in self._files}
            if self.table.rowCount() == 0 and self._files:
                self._apply_filter_and_populate()
            else:
                self._refresh_cell_states()
        self._update_summary()

    def _refresh_cell_states(self):
        """从 Store 同步单元格显示状态。"""
        self._suppress = True
        for f in self._filtered_files:
            row_idx = self._fid_to_row.get(f.file_id)
            if row_idx is None:
                continue
            amount = self._get_file_amount(f)
            is_confirmed = self._get_file_is_confirmed(f)

            check = self._confirm_checks.get(f.file_id)
            if check and check.isChecked() != is_confirmed:
                check.setChecked(is_confirmed)

            edit_cell = self._edit_cells.get(f.file_id)
            if edit_cell:
                current = edit_cell.get_value()
                if (current is None) != (amount is None) or (
                    current is not None
                    and amount is not None
                    and abs(current - amount) > 0.001
                ):
                    edit_cell.set_value(amount)
        self._suppress = False
