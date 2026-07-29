# -*- coding: utf-8 -*-
"""PDF 渲染器：使用 PyMuPDF (fitz) 将 PDF 页面渲染为 QImage"""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage, QPixmap


class PdfRenderer:
    """PDF 页面渲染器，基于 PyMuPDF。

    将 PDF 指定页渲染为 QImage/QPixmap，供 PreviewView 显示。
    支持指定 DPI 和最大边长限制（防 OOM）。
    """

    # 渲染参数
    DEFAULT_DPI = 150
    MAX_EDGE = 2000  # 最大边长像素，超过则降采样

    @staticmethod
    def get_page_count(pdf_path: str) -> int:
        """获取 PDF 总页数。"""
        try:
            import fitz
            doc = fitz.open(pdf_path)
            count = len(doc)
            doc.close()
            return count
        except Exception:
            return 0

    @classmethod
    def render_page(cls, pdf_path: str, page_idx: int = 0,
                    dpi: int = None) -> Optional[QImage]:
        """渲染 PDF 指定页为 QImage。

        Args:
            pdf_path: PDF 文件路径
            page_idx: 页码索引（0-based）
            dpi: 渲染 DPI，默认 150

        Returns:
            QImage 或 None（失败时）
        """
        if dpi is None:
            dpi = cls.DEFAULT_DPI
        try:
            import fitz
            doc = fitz.open(pdf_path)
            if page_idx < 0 or page_idx >= len(doc):
                return None
            page = doc[page_idx]
            # 使用 Matrix 控制 DPI（默认 72 DPI，缩放因子 = dpi/72）
            zoom = dpi / 72.0
            matrix = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=matrix, alpha=False)

            # 限制最大边长，防 OOM
            max_dim = max(pix.width, pix.height)
            if max_dim > cls.MAX_EDGE:
                scale = cls.MAX_EDGE / max_dim
                new_w = int(pix.width * scale)
                new_h = int(pix.height * scale)
                pix = fitz.Pixmap(pix, 0, 0, pix.width, pix.height,
                                  new_w, new_h, False)

            # 转换为 QImage
            fmt = QImage.Format_RGB888 if pix.n >= 3 else QImage.Format_Grayscale8
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
            # 必须 copy，否则 samples 内存会被 fitz 释放
            img = img.copy()
            doc.close()
            return img
        except Exception as e:
            print(f"[ERROR] PDF 渲染失败 {pdf_path}: {e}")
            return None

    @classmethod
    def render_pixmap(cls, pdf_path: str, page_idx: int = 0,
                      dpi: int = None) -> Optional[QPixmap]:
        """渲染 PDF 指定页为 QPixmap。"""
        img = cls.render_page(pdf_path, page_idx, dpi)
        return QPixmap.fromImage(img) if img else None
