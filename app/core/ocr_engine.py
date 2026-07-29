# -*- coding: utf-8 -*-
"""OCR 引擎：PaddleOCR 封装（懒加载单例）"""
from __future__ import annotations

import os
from typing import Optional

# 抑制 OpenCV 和 PaddlePaddle 的冗余日志
os.environ.setdefault("OPENCV_LOG_LEVEL", "OFF")
# PADDLE_PDX_CACHE_HOME 已在 app_entry.py 中设置，此处不再重复


class OcrLine:
    """OCR 单行识别结果"""
    __slots__ = ("text", "score", "poly")

    def __init__(self, text: str, score: float, poly=None):
        self.text = text
        self.score = score
        self.poly = poly

    def to_dict(self) -> dict:
        return {"text": self.text, "score": self.score, "poly": self.poly}


class OcrEngine:
    """PaddleOCR 封装，懒加载单例。

    首次调用 recognize() 时才导入 paddleocr 并实例化模型，
    避免启动时卡顿和首次模型下载阻塞。
    """

    _instance: Optional["OcrEngine"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._ocr = None
        self._initialized = False
        self._loading = False

    def _ensure_engine(self):
        """懒加载 PaddleOCR 实例。"""
        if self._ocr is not None:
            return

        if self._loading:
            return
        self._loading = True

        try:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(
                lang="ch",
                ocr_version="PP-OCRv5",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
            self._initialized = True
        except ImportError:
            raise RuntimeError(
                "PaddleOCR 未安装，请执行: pip install paddleocr paddlepaddle"
            )
        finally:
            self._loading = False

    def recognize(self, img_path: str) -> list[OcrLine]:
        """识别单张图片中的文字。

        Args:
            img_path: 图片文件路径

        Returns:
            list[OcrLine] 识别结果列表
        """
        self._ensure_engine()
        results = self._ocr.predict(img_path)
        return self._parse_results(results)

    def _parse_results(self, results) -> list[OcrLine]:
        """解析 PaddleOCR 3.x 的输出格式。

        PaddleOCR 3.x predict() 返回的是结果对象列表，
        每个结果包含 rec_texts、rec_scores、dt_polys 字段。
        """
        lines = []
        if not results:
            return lines

        for res in results:
            # PaddleOCR 3.x 返回的结果可能是 dict 或对象
            if isinstance(res, dict):
                texts = res.get("rec_texts", [])
                scores = res.get("rec_scores", [])
                polys = res.get("dt_polys", [])
            else:
                # 对象形式，尝试属性访问
                texts = getattr(res, "rec_texts", []) or []
                scores = getattr(res, "rec_scores", []) or []
                polys = getattr(res, "dt_polys", []) or []

            for i, text in enumerate(texts):
                score = scores[i] if i < len(scores) else 0.9
                poly = polys[i] if i < len(polys) else None
                lines.append(OcrLine(text=text, score=float(score), poly=poly))

        return lines
