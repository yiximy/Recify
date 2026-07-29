# -*- coding: utf-8 -*-
"""金额解析器：从 OCR 识别文本中提取金额信息"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class AmountCandidate:
    """金额识别候选结果"""
    value: Optional[float] = None          # 最终金额值
    source_text: str = ""                  # 来源文本
    confidence: float = 0.0                # 置信度


class AmountParser:
    """金额解析器，从 OCR 文本行中提取金额。

    解析策略（按优先级）：
    1. 带货币符号的金额：¥1234.56、￥1,234.56
    2. 关键词引导的金额：合计 1234.56、金额：1234.56
    3. 独立金额兜底：1234.56、1,234.56
    """

    # 金额正则模式（按优先级排序）
    # 1. 带货币符号：¥ / ￥ / $ / RMB
    PATTERN_CURRENCY = re.compile(
        r'[¥￥$]\s*([\d,]+\.?\d{0,2})'
    )
    # 2. 关键词引导：合计/金额/总额/总计/实付/实收/应付/应收/小计/价税合计 + 金额
    #    兼容英文关键词：Total/Amount/Sum/Paid/Pay
    PATTERN_KEYWORD = re.compile(
        r'(?:合计|金额|总额|总计|实付|实收|应付|应收|小计|价税合计'
        r'|[Tt]otal|[Aa]mount|[Ss]um|[Pp]aid|[Pp]ay)[：:\s]*'
        r'([\d,]+\.?\d{0,2})'
    )
    # 3. 带括号标记：（小写）¥1234.56
    PATTERN_PAREN = re.compile(
        r'[（(]\s*(?:小写|大写|金额)\s*[）)]\s*[¥￥]?\s*([\d,]+\.?\d{0,2})'
    )
    # 4. 独立金额兜底（要求有两位小数，避免误匹配）
    #    支持逗号千分位（1,234.56）和纯数字（1234.56）
    PATTERN_STANDALONE = re.compile(
        r'(?<!\d)((?:\d{1,3}(?:,\d{3})+|\d{1,8})\.\d{2})(?!\d)'
    )

    @classmethod
    def extract(cls, ocr_lines: list) -> AmountCandidate:
        """从 OCR 识别行中提取金额。

        Args:
            ocr_lines: OCR 识别结果列表，每个元素包含 text 和 score

        Returns:
            AmountCandidate 金额候选结果
        """
        if not ocr_lines:
            return AmountCandidate()

        # 收集所有文本和置信度
        texts = []
        all_matches = []

        for line in ocr_lines:
            text = line.get("text", "") if isinstance(line, dict) else str(line)
            score = line.get("score", 0.9) if isinstance(line, dict) else 0.9
            if not text:
                continue
            texts.append(text)
            # 全角转半角
            normalized = cls._normalize_text(text)

            # 按优先级匹配
            for pattern, priority in [
                (cls.PATTERN_CURRENCY, 4),
                (cls.PATTERN_PAREN, 3),
                (cls.PATTERN_KEYWORD, 2),
                (cls.PATTERN_STANDALONE, 1),
            ]:
                for match in pattern.finditer(normalized):
                    raw_val = match.group(1)
                    value = cls._parse_amount(raw_val)
                    if value is not None and value > 0:
                        all_matches.append((value, text, score * priority))

        if not all_matches:
            return AmountCandidate(confidence=0.0)

        # 选择最佳候选：按加权置信度排序，相同值取频率最高
        # 统计每个值的出现频率
        value_freq = {}
        value_weight = {}
        for value, text, weight in all_matches:
            value_freq[value] = value_freq.get(value, 0) + 1
            value_weight[value] = value_weight.get(value, 0) + weight

        # 综合评分 = 权重 + 频率*0.5
        best_value = max(
            value_freq.keys(),
            key=lambda v: value_weight[v] + value_freq[v] * 0.5
        )

        # 找到最佳值对应的来源文本
        best_text = ""
        best_score = 0.0
        for value, text, weight in all_matches:
            if value == best_value:
                if weight > best_score:
                    best_text = text
                    best_score = weight

        return AmountCandidate(
            value=best_value,
            source_text=best_text,
            confidence=min(1.0, best_score / 4.0),  # 归一化到 0-1
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        """全角转半角，统一符号。"""
        result = []
        for ch in text:
            code = ord(ch)
            # 全角空格
            if code == 0x3000:
                result.append(" ")
            # 全角字符（！~ ～）
            elif 0xFF01 <= code <= 0xFF5E:
                result.append(chr(code - 0xFEE0))
            else:
                result.append(ch)
        return "".join(result)

    @staticmethod
    def _parse_amount(raw: str) -> Optional[float]:
        """解析金额字符串，去除千分位逗号。"""
        cleaned = raw.replace(",", "").replace("，", "").strip()
        try:
            value = float(cleaned)
            # 合理性检查：金额应在 0.01 ~ 99999999 之间
            if 0.01 <= value <= 99999999:
                return value
        except ValueError:
            pass
        return None
