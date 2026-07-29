# -*- coding: utf-8 -*-
"""文件扫描器：遍历文件夹、按格式过滤、采集文件信息"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from .models import (
    FileInfo, InvoiceFile, PaymentFile, generate_file_id,
)

# 支持的文件格式
INVOICE_EXTS = {".pdf"}
PAYMENT_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _file_info(path: str) -> Optional[FileInfo]:
    """采集单个文件的基础信息。"""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    file_name = os.path.basename(path)
    ext = os.path.splitext(file_name)[1].lower()
    modified_iso = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    file_id = generate_file_id(os.path.abspath(path), modified_iso)
    return FileInfo(
        file_id=file_id,
        file_name=file_name,
        abs_path=os.path.abspath(path),
        size_bytes=stat.st_size,
        modified_iso=modified_iso,
        ext=ext,
    )


class FileScanner:
    """文件夹扫描器"""

    @staticmethod
    def scan_invoices(folder: str) -> list[InvoiceFile]:
        """扫描发票文件夹（仅 PDF）。"""
        if not folder or not os.path.isdir(folder):
            return []
        result = []
        for entry in os.scandir(folder):
            if not entry.is_file():
                continue
            ext = os.path.splitext(entry.name)[1].lower()
            if ext not in INVOICE_EXTS:
                continue
            info = _file_info(entry.path)
            if info is None:
                continue
            # 获取 PDF 页数（延迟导入，避免未装 PyMuPDF 时报错）
            page_count = 0
            try:
                from .pdf_renderer import PdfRenderer
                page_count = PdfRenderer.get_page_count(info.abs_path)
            except Exception:
                pass
            result.append(InvoiceFile(
                file_id=info.file_id,
                file_name=info.file_name,
                abs_path=info.abs_path,
                size_bytes=info.size_bytes,
                modified_iso=info.modified_iso,
                ext=info.ext,
                page_count=page_count,
            ))
        result.sort(key=lambda x: x.file_name)
        return result

    @staticmethod
    def scan_payments(folder: str) -> list[PaymentFile]:
        """扫描支付记录文件夹（仅图片）。"""
        if not folder or not os.path.isdir(folder):
            return []
        result = []
        for entry in os.scandir(folder):
            if not entry.is_file():
                continue
            ext = os.path.splitext(entry.name)[1].lower()
            if ext not in PAYMENT_EXTS:
                continue
            info = _file_info(entry.path)
            if info is None:
                continue
            result.append(PaymentFile(
                file_id=info.file_id,
                file_name=info.file_name,
                abs_path=info.abs_path,
                size_bytes=info.size_bytes,
                modified_iso=info.modified_iso,
                ext=info.ext,
            ))
        result.sort(key=lambda x: x.file_name)
        return result
