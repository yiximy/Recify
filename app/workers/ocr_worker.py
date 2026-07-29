# -*- coding: utf-8 -*-
"""OCR 工作线程：批量识别支付截图/发票PDF金额，桥接 OcrEngine 与 UI"""
from __future__ import annotations

import os
import tempfile
from typing import Optional

from .base_worker import BaseWorker
from app.core.ocr_engine import OcrEngine
from app.core.amount_parser import AmountParser


class OcrWorker(BaseWorker):
    """批量 OCR 识别线程。

    支持两种文件类型：
    - "image": 支付记录截图（默认），直接 OCR
    - "pdf": 发票 PDF，先渲染页面为图片再 OCR

    逐张识别，将 OcrLine 转为 dict 后交给 AmountParser 提取金额，
    通过 progress 信号实时上报进度，finished_ok 一次性回传完整结果。

    结果结构：
        { path: {"candidate": AmountCandidate, "raw_texts": [str, ...]} }
    """

    def __init__(self, paths: list[str], file_type: str = "image", parent=None):
        super().__init__(parent)
        self._paths = [p for p in paths if p and os.path.exists(p)]
        self._file_type = file_type  # "image" | "pdf"

    def _safe_run(self):
        if not self._paths:
            self.finished_ok.emit({})
            return

        engine = OcrEngine()
        total = len(self._paths)
        result_map: dict = {}

        for i, path in enumerate(self._paths):
            file_name = os.path.basename(path)
            if i == 0:
                tip = "正在加载 OCR 模型，请稍候..."
                if self._file_type == "pdf":
                    tip = "正在加载 OCR 模型（发票识别），请稍候..."
                self.progress.emit(0, total, tip)

            try:
                if self._file_type == "pdf":
                    line_dicts = self._ocr_pdf(engine, path, file_name, i, total)
                else:
                    lines = engine.recognize(path)
                    line_dicts = [{"text": l.text, "score": l.score} for l in lines]
            except Exception as e:
                result_map[path] = {
                    "candidate": AmountParser.extract([]),
                    "raw_texts": [],
                    "error": str(e),
                }
                self.progress.emit(i + 1, total, f"{file_name} 识别失败：{e}")
                continue

            candidate = AmountParser.extract(line_dicts)
            raw_texts = [d["text"] for d in line_dicts]

            result_map[path] = {
                "candidate": candidate,
                "raw_texts": raw_texts,
            }
            self.progress.emit(i + 1, total, f"已识别 {file_name}")

        self.finished_ok.emit(result_map)

    def _ocr_pdf(self, engine: OcrEngine, pdf_path: str, file_name: str,
                 idx: int, total: int) -> list[dict]:
        """渲染 PDF 每页为临时图片后 OCR，合并所有页面的文本行。

        返回合并后的 line_dicts 列表，供 AmountParser 统一提取金额。
        """
        from app.core.pdf_renderer import PdfRenderer

        page_count = PdfRenderer.get_page_count(pdf_path)
        if page_count == 0:
            return []

        all_line_dicts: list[dict] = []

        for page_idx in range(page_count):
            # 限制最多渲染前 4 页（发票通常只有 1-2 页，4 页足够覆盖多页发票）
            if page_idx >= 4:
                break

            self.progress.emit(
                idx, total,
                f"{file_name} 第 {page_idx + 1}/{min(page_count, 4)} 页"
            )

            # 渲染当前页为图片
            img = PdfRenderer.render_page(pdf_path, page_idx, dpi=200)
            if img is None:
                continue

            # 写入临时文件供 OCR 引擎读取
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    suffix=".png", delete=False
                ) as tmp:
                    tmp_path = tmp.name
                img.save(tmp_path, "PNG")

                lines = engine.recognize(tmp_path)
                for line in lines:
                    all_line_dicts.append({"text": line.text, "score": line.score})
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

        return all_line_dicts
