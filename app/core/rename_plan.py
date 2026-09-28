# -*- coding: utf-8 -*-
"""组合重命名辅助：目标名规划、冲突检测与磁盘两阶段重命名。

纯 Python 实现，不依赖 Qt；供 ``Store.rename_group`` 复用。
"""
from __future__ import annotations

import os


def plan_target_paths(files: list[dict], new_base: str) -> list[str]:
    """按 (所在目录, 扩展名) 分组编号，返回与输入同序的目标绝对路径。

    同组第 1 个为 ``<new_base><ext>``，其后依次 ``<new_base>_2<ext>``、
    ``<new_base>_3<ext>``…；跨目录 / 跨扩展名互不影响。
    """
    counters: dict[tuple[str, str], int] = {}
    targets: list[str] = []
    for f in files:
        directory = os.path.dirname(f["abs_path"])
        ext = f["ext"]
        key = (directory, ext.lower())
        index = counters.get(key, 0) + 1
        counters[key] = index
        base = new_base if index == 1 else f"{new_base}_{index}"
        targets.append(os.path.join(directory, base + ext))
    return targets


def has_target_conflict(files: list[dict], targets: list[str]) -> bool:
    """冲突检测：目标名组内重复，或目标路径被本组之外的文件占用。"""
    own_paths = {f["abs_path"] for f in files}
    seen: set[str] = set()
    for target in targets:
        if target in seen:
            return True
        seen.add(target)
        if os.path.exists(target) and target not in own_paths:
            return True
    return False


def rename_paths(pairs: list[tuple[str, str]]) -> bool:
    """两阶段重命名：先全部改到临时名，再改到目标名。

    先落到临时名可安全处理组内互换（A→B 名 / B→A 名）；任一 ``os.rename``
    失败即回滚到原始路径并返回 False。``orig == target`` 的条目自动跳过。
    """
    moves = [(orig, target) for orig, target in pairs if orig != target]
    if not moves:
        return True

    staged: list[tuple[str, str, str]] = []  # (原路径, 临时路径, 目标路径)
    try:
        for orig, target in moves:
            tmp = _temp_path(orig)
            os.rename(orig, tmp)
            staged.append((orig, tmp, target))
    except OSError:
        _rollback(staged, done=0)
        return False

    done = 0
    for _, tmp, target in staged:
        try:
            os.rename(tmp, target)
        except OSError:
            _rollback(staged, done=done)
            return False
        done += 1
    return True


def remap_dict_keys(mapping: dict, old_to_new: dict[str, str]) -> dict | None:
    """按 old→new 重键；若发生键碰撞（条目数减少）返回 None。"""
    out = {old_to_new.get(key, key): value for key, value in mapping.items()}
    return out if len(out) == len(mapping) else None


def _temp_path(path: str) -> str:
    """为 path 生成一个当前不存在的同目录临时名。"""
    candidate = path + ".rectmp"
    index = 2
    while os.path.exists(candidate):
        candidate = f"{path}.rectmp{index}"
        index += 1
    return candidate


def _rollback(staged: list[tuple[str, str, str]], done: int) -> None:
    """回滚：先把已到目标名的前 done 个退回临时名，再把全部临时名退回原名。"""
    for _, tmp, target in reversed(staged[:done]):
        try:
            os.rename(target, tmp)
        except OSError:
            pass
    for orig, tmp, _ in reversed(staged):
        try:
            os.rename(tmp, orig)
        except OSError:
            pass
