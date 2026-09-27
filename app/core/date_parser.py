# -*- coding: utf-8 -*-
"""日期解析器：从 OCR 文本行中提取票面日期（纯 Python，不依赖 Qt）。"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Optional

_YEAR = r"(?:20\d{2}|2100)"
_MONTH = r"(?:0?[1-9]|1[0-2])"
_DAY = r"(?:0?[1-9]|[12]\d|3[01])"

# 按业务优先级排列；同一行仍以出现位置最靠前者为最终候选。
_DATE_PATTERNS = (
    re.compile(
        rf"(?P<year>{_YEAR})\s*年\s*(?P<month>{_MONTH})"
        rf"\s*月\s*(?P<day>{_DAY})\s*日"
    ),
    re.compile(
        rf"(?<!\d)(?P<year>{_YEAR})\s*(?P<sep>[-/.])\s*"
        rf"(?P<month>{_MONTH})\s*(?P=sep)\s*(?P<day>{_DAY})(?!\d)"
    ),
    re.compile(
        rf"(?<!\d)(?P<year>{_YEAR})(?P<month>0[1-9]|1[0-2])"
        rf"(?P<day>0[1-9]|[12]\d|3[01])(?!\d)"
    ),
)
_COMPACT_PATTERN_INDEX = 2
_COMPACT_PREFIX = re.compile(r"(?:日期|时间)\s*[:：]?\s*$")
_TIME_SUFFIX = re.compile(r"\s*\d{1,2}:\d{2}")


def _to_iso_date(year: str, month: str, day: str) -> Optional[str]:
    """校验并转换日期；不合法（含不存在的日期）时返回 None。"""
    try:
        parsed = date(int(year), int(month), int(day))
    except ValueError:
        return None
    if not 2000 <= parsed.year <= 2100:
        return None
    return parsed.isoformat()


def _compact_has_context(text: str, match: re.Match) -> bool:
    """8 位连写须为独立行，或邻近日期/时间关键词/时间部分。"""
    token = match.group(0)
    if text.strip() == token:
        return True
    start, end = match.span()
    prefix = text[max(0, start - 12):start]
    suffix = text[end:end + 10]
    return bool(_COMPACT_PREFIX.search(prefix) or _TIME_SUFFIX.match(suffix))


def _first_date_in_line(line: str) -> Optional[str]:
    """返回单行中位置最靠前的合法日期。"""
    text = unicodedata.normalize("NFKC", line or "")
    candidates: list[tuple[int, str]] = []
    for index, pattern in enumerate(_DATE_PATTERNS):
        for match in pattern.finditer(text):
            if index == _COMPACT_PATTERN_INDEX and not _compact_has_context(text, match):
                continue
            iso_date = _to_iso_date(
                match.group("year"), match.group("month"), match.group("day")
            )
            if iso_date is not None:
                candidates.append((match.start(), iso_date))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def parse_date_from_lines(lines: list[str]) -> Optional[str]:
    """从 OCR 文本行解析日期，返回 ISO 格式 ``YYYY-MM-DD``。

    优先解析含「开票日期」的行，再按原始行序解析通用日期；
    无年份的部分日期不解析，交由调用方回退文件修改时间。
    """
    if not lines:
        return None

    normalized_lines = [
        unicodedata.normalize("NFKC", str(line)) if line is not None else ""
        for line in lines
    ]
    for line in normalized_lines:
        if "开票日期" not in line:
            continue
        parsed = _first_date_in_line(line)
        if parsed is not None:
            return parsed

    for line in normalized_lines:
        parsed = _first_date_in_line(line)
        if parsed is not None:
            return parsed
    return None


def parse_datetime_from_lines(lines: list[str]) -> Optional[str]:
    """兼容日期时间命名；当前仅返回日期粒度 ``YYYY-MM-DD``。"""
    return parse_date_from_lines(lines)


def _run_assertions() -> None:
    """运行多格式正反例断言，供直接执行模块时快速自检。"""
    positives = {
        "开票日期：2026年7月9日": "2026-07-09",
        "开票日期：2026年07月09日": "2026-07-09",
        "2026-07-09 10:30": "2026-07-09",
        "2026/7/9 10:30:45": "2026-07-09",
        "2026.07.09": "2026-07-09",
        "2026 - 07 - 09": "2026-07-09",
        "2026 年 07 月 09 日": "2026-07-09",
        "20260709": "2026-07-09",
        "支付时间：20260709 10:30": "2026-07-09",
        "２０２６－０７－０９ １０：３０": "2026-07-09",
        "2024-02-29": "2024-02-29",
    }
    for line, expected in positives.items():
        assert parse_date_from_lines([line]) == expected, line

    assert parse_date_from_lines(["普通日期 2026-07-09", "开票日期：2026-08-01"]) \
        == "2026-08-01"
    assert parse_date_from_lines(["2026-13-01"]) is None
    assert parse_date_from_lines(["2026-02-31"]) is None
    assert parse_date_from_lines(["2025-02-29"]) is None
    assert parse_date_from_lines(["07-09 10:30"]) is None
    assert parse_date_from_lines(["订单号 202607090001"]) is None
    assert parse_date_from_lines(["订单号 20260709"]) is None
    assert parse_date_from_lines(["联系电话 13800138000"]) is None
    assert parse_date_from_lines([]) is None
    print("date_parser assertions passed")


if __name__ == "__main__":
    _run_assertions()