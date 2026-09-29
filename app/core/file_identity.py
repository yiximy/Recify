# -*- coding: utf-8 -*-
"""文件身份识别：外部改名自愈的纯逻辑（Qt-free，可单测）。

背景：``models.generate_file_id`` 由「绝对路径 + 修改时间」生成，文件在
资源管理器里改名后路径变化 → id 变化，重扫会得到一条全新记录，旧的
关联 / OCR 金额 / 票面日期全部掉队。

本模块只做一件事：在重扫结果里识别「同一条文件被改名」的新旧记录配对。
启发式（本轮约定，非通用文件身份）：``size_bytes``、``modified_iso``、
``ext`` 三者全等即视为同一文件的候选。

取舍：宁可漏修不可错配 —— 候选不唯一（同尺寸同修改时间的同名扩展名文件）
或候选被多条新记录争抢时一律跳过，不猜测。
"""
from __future__ import annotations

from collections import defaultdict


def _field(record, name):
    """从 dict 或领域对象上取值（兼容 Store 内的 dict 与 dataclass）。"""
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)


def identity_key(record) -> tuple:
    """返回身份键 ``(size_bytes, modified_iso, ext)``；ext 统一小写。"""
    ext = _field(record, "ext")
    if ext is not None:
        ext = str(ext).lower()
    return (_field(record, "size_bytes"), _field(record, "modified_iso"), ext)


def _is_complete(key: tuple) -> bool:
    """身份键字段是否齐全；缺字段的记录不参与配对，避免空值互相误配。"""
    size, modified, ext = key
    return size is not None and bool(modified) and bool(ext)


def plan_rename_adoptions(scanned, existing: dict) -> list[tuple[str, str]]:
    """规划改名自愈配对，返回 ``[(旧 file_id, 新 file_id), ...]``。

    Args:
        scanned: 本次扫描结果（dict 或 InvoiceFile/PaymentFile 均可）。
        existing: Store 中该类文件的 ``file_id -> dict`` 映射（应在本轮
            新记录写入之前传入，缺失记录须已带 ``missing=True``）。

    规则：
        * 只考察「id 不在 existing 中」的新记录；
        * 候选 = ``missing`` 且身份键与新记录全等的既有记录；
        * 候选唯一且该候选未被多条新记录争抢时才采纳，否则跳过。
    """
    new_by_key: dict[tuple, list[str]] = defaultdict(list)
    for record in scanned:
        file_id = _field(record, "file_id")
        if not file_id or file_id in existing:
            continue
        key = identity_key(record)
        if _is_complete(key):
            new_by_key[key].append(file_id)

    if not new_by_key:
        return []

    missing_by_key: dict[tuple, list[str]] = defaultdict(list)
    for file_id, record in existing.items():
        if record.get("missing") and _is_complete(identity_key(record)):
            missing_by_key[identity_key(record)].append(file_id)

    plan: list[tuple[str, str]] = []
    for key, new_ids in new_by_key.items():
        candidates = missing_by_key.get(key, [])
        if len(candidates) == 1 and len(new_ids) == 1:
            plan.append((candidates[0], new_ids[0]))
    return plan
