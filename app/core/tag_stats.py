# -*- coding: utf-8 -*-
"""自定义标签统计口径（Qt-free，纯计算）。

本模块是「按标签统计」的唯一实现：``Store.get_tag_stats()``、导出对话框预览
与导出生成都经由它，避免口径分叉。

统计口径（对齐 ``.ai/brief.md`` 追加节）：对每个标签 T，
  * 发票集合 = {发票 f : f 带 T} ∪ {发票 f : f 属于带 T 的发票组合}
  * 张数 = 发票集合大小（支付侧标签**不**参与张数）
  * 支付集合 = 三者并集去重（跳过不存在/missing 的支付记录）：
      - 发票集合内每张发票 ``linked_payment_ids`` 的并集
      - 支付记录自身带 T
      - 属于带 T 的**支付**组合的支付记录
  * 金额 = Σ 支付集合的 ``final_amount``（None 视为 0）
  * 日期区间 = 发票集合日期（``get_document_date``，回退文件修改时间）[min, max]
  * 备注 = 贡献该类别的组合名（发票组合 + 贡献了金额的支付组合，、连接）
          ＋「含 N 张未匹配支付」（N>0 时；N = 发票集合内无有效支付记录的发票数）

「未分类」= 发票自身无标签、其发票组合无标签、其关联支付记录无标签、
其关联支付所属支付组合无标签者，口径同上。

纯支付类别（只给支付打标签、无关联发票）→ 张数 0、金额 > 0，属预期行为。

跨类别提示：同一支付记录被多个类别共同引用时，会在各归属类别分别计入；
类别内已去重（README 有说明，不额外处理）。
"""
from __future__ import annotations

from .models import normalize_tags


def build_tag_stats(store) -> dict:
    """按标签统计，返回 ``{"tags": [类别...], "untagged": 类别}``。"""
    invoices = {f.file_id: f for f in store.get_invoices()}
    payments = {f.file_id: f for f in store.get_payments(include_missing=True)}
    inv_combos = store.get_combos("invoice")
    pay_combos = store.get_combos("payment")

    # 发票 -> 所属「发票组合」的 [(组合名, 组合标签)]，供未分类判定
    inv_combos_of: dict[str, list[tuple[str, list]]] = {}
    for combo in inv_combos:
        entry = (combo.get("name", ""), normalize_tags(combo.get("tags", [])))
        for fid in combo.get("file_ids", []):
            inv_combos_of.setdefault(fid, []).append(entry)

    # 支付 -> 所属「支付组合」的 [(组合名, 组合标签)]，供未分类判定
    pay_combos_of: dict[str, list[tuple[str, list]]] = {}
    for combo in pay_combos:
        entry = (combo.get("name", ""), normalize_tags(combo.get("tags", [])))
        for fid in combo.get("file_ids", []):
            pay_combos_of.setdefault(fid, []).append(entry)

    def invoice_set_for(tag: str) -> tuple[set, list]:
        """T 的发票集合（自身带 T ∪ 属于带 T 的发票组合）及其组合名。"""
        ids: set = set()
        combo_names: list = []
        for fid, inv in invoices.items():
            if tag in normalize_tags(inv.tags):
                ids.add(fid)
        for combo in inv_combos:
            if tag not in normalize_tags(combo.get("tags", [])):
                continue
            contributed = False
            for fid in combo.get("file_ids", []):
                if fid in invoices:
                    ids.add(fid)
                    contributed = True
            name = combo.get("name", "")
            if contributed and name and name not in combo_names:
                combo_names.append(name)
        return ids, combo_names

    def payment_set_for(tag: str, ids: set) -> tuple[set, list]:
        """T 的支付集合（三方并集去重）及其贡献了金额的支付组合名。"""
        payment_ids: set = set()
        combo_names: list = []
        for fid in ids:
            inv = invoices[fid]
            for pid in getattr(inv, "linked_payment_ids", []) or []:
                pay = payments.get(pid)
                if pay is None or pay.missing:
                    continue
                payment_ids.add(pid)
        for pid, pay in payments.items():
            if pay.missing:
                continue
            if tag in normalize_tags(pay.tags):
                payment_ids.add(pid)
        for combo in pay_combos:
            if tag not in normalize_tags(combo.get("tags", [])):
                continue
            contributed = False
            for pid in combo.get("file_ids", []):
                pay = payments.get(pid)
                if pay is None or pay.missing:
                    continue
                payment_ids.add(pid)
                contributed = True
            name = combo.get("name", "")
            if contributed and name and name not in combo_names:
                combo_names.append(name)
        return payment_ids, combo_names

    def category(tag: str, ids: set, inv_combo_names: list) -> dict:
        payment_ids, pay_combo_names = payment_set_for(tag, ids)

        amount = 0.0
        for pid in payment_ids:
            rec = payments[pid].amount
            if rec is None:
                continue
            value = rec.final_amount
            if value is not None:
                amount += value

        unmatched = 0
        dates: list = []
        for fid in ids:
            inv = invoices[fid]
            valid_linked = 0
            for pid in getattr(inv, "linked_payment_ids", []) or []:
                pay = payments.get(pid)
                if pay is None or pay.missing:
                    continue
                valid_linked += 1
            if valid_linked == 0:
                unmatched += 1
            date_iso, _source = store.get_document_date(inv)
            if date_iso:
                dates.append(date_iso)

        start = min(dates) if dates else ""
        end = max(dates) if dates else ""

        combo_names = list(inv_combo_names)
        for name in pay_combo_names:
            if name not in combo_names:
                combo_names.append(name)

        combo_text = "、".join(combo_names)
        if unmatched:
            tail = f"含 {unmatched} 张未匹配支付"
            note = f"{combo_text}、{tail}" if combo_text else tail
        else:
            note = combo_text
        return {
            "tag": tag,
            "count": len(ids),
            "amount": round(amount, 2),
            "date_start": start,
            "date_end": end,
            "date_text": store.format_date_range(start, end),
            "combo_names": list(combo_names),
            "unmatched": unmatched,
            "note": note,
        }

    def is_untagged(fid: str, inv) -> bool:
        """发票计入未分类：自身/发票组合/关联支付/关联支付组合均无标签。"""
        if normalize_tags(inv.tags):
            return False
        if any(tags for _name, tags in inv_combos_of.get(fid, [])):
            return False
        for pid in getattr(inv, "linked_payment_ids", []) or []:
            pay = payments.get(pid)
            if pay is None or pay.missing:
                continue
            if normalize_tags(pay.tags):
                return False
            if any(tags for _name, tags in pay_combos_of.get(pid, [])):
                return False
        return True

    categories = [category(tag, *invoice_set_for(tag))
                  for tag in store.get_all_tags()]
    untagged_ids = {fid for fid, inv in invoices.items()
                    if is_untagged(fid, inv)}
    untagged = category("未分类", untagged_ids, [])
    return {"tags": categories, "untagged": untagged}