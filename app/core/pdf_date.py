# -*- coding: utf-8 -*-
"""票面日期文本层提取：按坐标定位「开票日期」标签同一视觉行的值（纯 Python，不依赖 Qt）。

发票 PDF 自带精确文本层，直接读取可避免 OCR 数字误读（如漏读「26」中的「6」）。
两种版式均覆盖：

- 版式 A：标签与值处于同一视觉行（可能是同一词或相邻词）；
- 版式 B：标签行的值被拆成多个文字块（``2026`` / ``年`` / ``09`` / ``月`` / ``17`` / ``日``）。

文本层缺失（纯图片 PDF）或无法解析时返回空串，由调用方回退 OCR 文本。
"""
from __future__ import annotations

import re

import fitz

from .date_parser import parse_date_from_lines

# 「开票日期」标签，允许字间空白
_LABEL_PATTERN = re.compile(r"开\s*票\s*日\s*期")

# 视觉同一行的纵向重叠容差（pt）：两词纵向区间重叠大于该负值即视为同一行
_ROW_TOLERANCE = 3.0


def _same_visual_row(label: tuple, word: tuple) -> bool:
    """判断 ``word`` 是否与 ``label`` 处于同一视觉行（纵向有重叠）。"""
    overlap = min(label[3], word[3]) - max(label[1], word[1])
    return overlap > -_ROW_TOLERANCE


def _value_for_label(words: list, label_index: int) -> str:
    """拼接标签同一视觉行右侧的词文本（按 x 升序、无分隔）。

    同时兼容标签词内已含值的情形（取标签之后的剩余文本）。
    """
    label = words[label_index]
    match = _LABEL_PATTERN.search(label[4])
    remainder = label[4][match.end():] if match else ""

    label_center = (label[0] + label[2]) / 2.0
    # 值可能与标签右边界轻微重叠（不同字体度量），故按「水平中心位于标签中心右侧」
    # 且纵向同行的词判定，避免误纳左侧相邻字段。
    right = [
        word
        for index, word in enumerate(words)
        if index != label_index
        and (word[0] + word[2]) / 2.0 > label_center
        and _same_visual_row(label, word)
    ]
    right.sort(key=lambda word: word[0])
    return remainder + "".join(word[4] for word in right)


def labeled_invoice_date(path: str) -> str:
    """返回票面「开票日期」``YYYY-MM-DD``；无文本层或解析失败时返回 ``""``。

    多页 PDF 取第一个命中的页面。解析复用 :mod:`date_parser` 的正则与日历校验，
    因此非法日期（如 ``2026年02月30日``）不会被采纳。
    """
    try:
        doc = fitz.open(path)
    except Exception:
        return ""
    try:
        for page in doc:
            words = page.get_text("words")
            for index, word in enumerate(words):
                if not _LABEL_PATTERN.search(word[4]):
                    continue
                candidate = _value_for_label(words, index)
                if not candidate:
                    continue
                parsed = parse_date_from_lines([candidate])
                if parsed:
                    return parsed
    finally:
        doc.close()
    return ""
