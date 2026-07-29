# -*- coding: utf-8 -*-
"""预览视图：QGraphicsView 实现，支持 PDF/图片显示与缩放控制"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QPainter, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QHBoxLayout, QWidget,
)
from monkeyqt import MkButton, MkSlider


class PreviewView(QWidget):
    """通用预览组件，包含 QGraphicsView + 缩放控制条。

    支持 PDF 渲染图和图片的自适应显示与缩放。
    """

    zoomChanged = Signal(float)

    def __init__(self, title: str = "预览", parent=None):
        super().__init__(parent)
        self._title = title
        self._pixmap: Optional[QPixmap] = None
        self._zoom = 1.0
        self._build_ui()

    def _build_ui(self):
        from PySide6.QtWidgets import QVBoxLayout, QLabel

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ── 标题栏 ──
        header = QHBoxLayout()
        header.setSpacing(8)
        self.lbl_title = QLabel(self._title)
        self.lbl_title.setStyleSheet("font-weight: 600; color: #303133; font-size: 13px;")
        header.addWidget(self.lbl_title)

        # 页码标签（PDF 用）
        self.lbl_page = QLabel("")
        self.lbl_page.setStyleSheet("color: #909399; font-size: 12px;")
        header.addWidget(self.lbl_page)

        header.addStretch()

        # 翻页按钮（PDF 用）
        self.btn_prev = MkButton("上一页", type="default")
        self.btn_prev.setEnabled(False)
        self.btn_prev.clicked.connect(self._prev_page)
        header.addWidget(self.btn_prev)

        self.btn_next = MkButton("下一页", type="default")
        self.btn_next.setEnabled(False)
        self.btn_next.clicked.connect(self._next_page)
        header.addWidget(self.btn_next)

        layout.addLayout(header)

        # ── QGraphicsView 预览区 ──
        self.graphics_view = _ZoomableGraphicsView()
        self.graphics_view.zoomChanged.connect(self._on_zoom_changed)
        layout.addWidget(self.graphics_view, stretch=1)

        # ── 底部缩放控制 ──
        footer = QHBoxLayout()
        footer.setSpacing(8)

        self.btn_fit = MkButton("适应窗口", type="default")
        self.btn_fit.clicked.connect(self.fit_in_view)
        footer.addWidget(self.btn_fit)

        self.slider = MkSlider()
        self.slider.setRange(10, 300)
        self.slider.setValue(100)
        self.slider.valueChanged.connect(self._on_slider_changed)
        footer.addWidget(self.slider, stretch=1)

        self.lbl_zoom = QLabel("100%")
        self.lbl_zoom.setStyleSheet("color: #909399; font-size: 12px; min-width: 50px;")
        footer.addWidget(self.lbl_zoom)

        layout.addLayout(footer)

        # PDF 翻页状态
        self._pdf_path: Optional[str] = None
        self._page_count: int = 0
        self._current_page: int = 0

    def set_pixmap(self, pixmap: QPixmap):
        """设置预览图片。"""
        self._pixmap = pixmap
        self.graphics_view.set_pixmap(pixmap)
        self.fit_in_view()

    def set_pdf(self, pdf_path: str, page_idx: int = 0):
        """设置 PDF 文件并渲染指定页。"""
        from app.core.pdf_renderer import PdfRenderer

        self._pdf_path = pdf_path
        self._page_count = PdfRenderer.get_page_count(pdf_path)
        self._current_page = min(page_idx, max(0, self._page_count - 1))

        self._render_pdf_page()
        self._update_page_controls()

    def _render_pdf_page(self):
        """渲染当前 PDF 页。"""
        if not self._pdf_path:
            return
        from app.core.pdf_renderer import PdfRenderer
        pixmap = PdfRenderer.render_pixmap(self._pdf_path, self._current_page)
        if pixmap:
            self.set_pixmap(pixmap)

    def _update_page_controls(self):
        """更新翻页控件状态。"""
        has_pages = self._page_count > 1
        self.btn_prev.setEnabled(has_pages and self._current_page > 0)
        self.btn_next.setEnabled(has_pages and self._current_page < self._page_count - 1)
        if self._page_count > 0:
            self.lbl_page.setText(f"第 {self._current_page + 1} / {self._page_count} 页")
        else:
            self.lbl_page.setText("")

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._render_pdf_page()
            self._update_page_controls()

    def _next_page(self):
        if self._current_page < self._page_count - 1:
            self._current_page += 1
            self._render_pdf_page()
            self._update_page_controls()

    def fit_in_view(self):
        """适应窗口大小。"""
        self.graphics_view.fit_in_view()
        self._zoom = 1.0
        self._update_zoom_label()

    def _on_slider_changed(self, value: int):
        """滑块控制缩放。"""
        self.graphics_view.set_zoom(value / 100.0)
        self._zoom = value / 100.0
        self._update_zoom_label()

    def _on_zoom_changed(self, zoom: float):
        """GraphicsView 内部缩放变化时同步滑块。"""
        self._zoom = zoom
        percent = int(zoom * 100)
        self.slider.blockSignals(True)
        self.slider.setValue(max(10, min(300, percent)))
        self.slider.blockSignals(False)
        self._update_zoom_label()

    def _update_zoom_label(self):
        self.lbl_zoom.setText(f"{int(self._zoom * 100)}%")

    def clear(self):
        """清空预览。"""
        self._pixmap = None
        self._pdf_path = None
        self._page_count = 0
        self._current_page = 0
        self.graphics_view.clear()
        self.lbl_page.setText("")
        self._update_page_controls()


class _ZoomableGraphicsView(QGraphicsView):
    """支持 Ctrl+滚轮缩放和拖拽平移的 QGraphicsView。"""

    zoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setStyleSheet("""
            QGraphicsView {
                background: #f5f7fa;
                border: 1px solid #e4e7ed;
                border-radius: 6px;
            }
        """)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = QGraphicsPixmapItem()
        self._scene.addItem(self._item)
        self._zoom = 1.0

    def set_pixmap(self, pixmap: QPixmap):
        """设置显示的图片。"""
        self._item.setPixmap(pixmap)
        self._scene.setSceneRect(self._item.boundingRect())
        self.fit_in_view()

    def fit_in_view(self):
        """适应窗口。"""
        if self._item.pixmap().isNull():
            return
        self.fitInView(self._item, Qt.KeepAspectRatio)
        # 获取当前缩放比例
        transform = self.transform()
        self._zoom = transform.m11()
        self.zoomChanged.emit(self._zoom)

    def set_zoom(self, factor: float):
        """设置缩放比例。"""
        if self._item.pixmap().isNull():
            return
        self.resetTransform()
        self.scale(factor, factor)
        self._zoom = factor
        self.zoomChanged.emit(factor)

    def wheelEvent(self, event: QWheelEvent):
        """Ctrl+滚轮缩放，普通滚轮平移。"""
        if event.modifiers() & Qt.ControlModifier:
            angle = event.angleDelta().y()
            factor = 1.15 if angle > 0 else 1 / 1.15
            new_zoom = self._zoom * factor
            # 限制缩放范围 10% ~ 300%
            new_zoom = max(0.1, min(3.0, new_zoom))
            self.set_zoom(new_zoom)
        else:
            super().wheelEvent(event)

    def clear(self):
        """清空。"""
        self._item.setPixmap(QPixmap())
        self._scene.setSceneRect(0, 0, 0, 0)
