# -*- coding: utf-8 -*-
"""JSON 持久化：原子写 + 增量合并，是数据真相源"""
from __future__ import annotations

import json
import os
import threading
import uuid
from typing import Optional

from .models import (
    InvoiceFile, PaymentFile, Association, AmountRecord,
    generate_file_id, now_iso,
)


class Store:
    """主数据存储，管理发票、支付记录、关联关系、金额记录。

    所有 UI 操作通过 Store 的方法读写数据，Store 是唯一真相源。
    线程安全（内部加锁），支持 QThread 后台调用。
    """

    VERSION = "1.0"

    def __init__(self, store_path: str):
        self._path = store_path
        self._lock = threading.RLock()
        self._data: dict = self._load()
        # 数据变更回调列表（UI 层可注册刷新）
        self._listeners: list = []

    # ── 持久化 ──────────────────────────────────────────────

    def _load(self) -> dict:
        """从 JSON 文件加载数据，文件不存在则返回空结构。"""
        if not os.path.exists(self._path):
            return self._empty_data()
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 确保结构完整
            data.setdefault("version", self.VERSION)
            data.setdefault("invoices", {})
            data.setdefault("payments", {})
            data.setdefault("associations", [])
            data.setdefault("invoice_folder", "")
            data.setdefault("payment_folder", "")
            data.setdefault("combos", [])
            return data
        except (json.JSONDecodeError, IOError):
            return self._empty_data()

    def _empty_data(self) -> dict:
        return {
            "version": self.VERSION,
            "last_updated": "",
            "invoice_folder": "",
            "payment_folder": "",
            "invoices": {},
            "payments": {},
            "associations": [],
            "combos": [],
        }

    def _save(self):
        """原子写：先写 .tmp 再 os.replace，防崩溃损坏。"""
        self._data["last_updated"] = now_iso()
        tmp_path = self._path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self._path)

    def _notify(self):
        """通知所有监听器数据已变更。"""
        for cb in self._listeners:
            try:
                cb()
            except Exception:
                pass

    def on_changed(self, callback):
        """注册数据变更回调（UI 层用于刷新视图）。"""
        self._listeners.append(callback)

    # ── 文件夹路径 ──────────────────────────────────────────

    def get_folder(self, kind: str) -> str:
        """获取文件夹路径。kind: 'invoice' 或 'payment'"""
        with self._lock:
            return self._data.get(f"{kind}_folder", "")

    def set_folder(self, kind: str, path: str):
        """设置文件夹路径并持久化。"""
        with self._lock:
            self._data[f"{kind}_folder"] = path
            self._save()
            self._notify()

    # ── 扫描合并 ────────────────────────────────────────────

    def merge_invoices(self, scanned: list[InvoiceFile]):
        """增量合并发票扫描结果，保留已有关联。"""
        with self._lock:
            existing = self._data["invoices"]
            new_ids = {inv.file_id for inv in scanned}
            # 标记缺失文件
            for fid, inv_dict in existing.items():
                if fid not in new_ids:
                    inv_dict["missing"] = True
            # 合并新扫描结果（保留 linked_payment_ids）
            for inv in scanned:
                if inv.file_id in existing:
                    old = existing[inv.file_id]
                    inv.linked_payment_ids = old.get("linked_payment_ids", [])
                    inv.amount = AmountRecord.from_dict(old.get("amount"))
                existing[inv.file_id] = inv.to_dict()
            self._save()
            self._notify()

    def merge_payments(self, scanned: list[PaymentFile]):
        """增量合并支付记录扫描结果，保留已有关联和金额。"""
        with self._lock:
            existing = self._data["payments"]
            new_ids = {pay.file_id for pay in scanned}
            for fid, pay_dict in existing.items():
                if fid not in new_ids:
                    pay_dict["missing"] = True
            for pay in scanned:
                if pay.file_id in existing:
                    old = existing[pay.file_id]
                    pay.linked_invoice_ids = old.get("linked_invoice_ids", [])
                    pay.amount = AmountRecord.from_dict(old.get("amount"))
                existing[pay.file_id] = pay.to_dict()
            self._save()
            self._notify()

    # ── 查询 ────────────────────────────────────────────────

    def get_invoices(self, include_missing: bool = False) -> list[InvoiceFile]:
        """获取所有发票。"""
        with self._lock:
            result = []
            for d in self._data["invoices"].values():
                if not include_missing and d.get("missing"):
                    continue
                result.append(InvoiceFile.from_dict(d))
            return result

    def get_payments(self, include_missing: bool = False) -> list[PaymentFile]:
        """获取所有支付记录。"""
        with self._lock:
            result = []
            for d in self._data["payments"].values():
                if not include_missing and d.get("missing"):
                    continue
                result.append(PaymentFile.from_dict(d))
            return result

    def get_invoice(self, file_id: str) -> Optional[InvoiceFile]:
        with self._lock:
            d = self._data["invoices"].get(file_id)
            return InvoiceFile.from_dict(d) if d else None

    def get_payment(self, file_id: str) -> Optional[PaymentFile]:
        with self._lock:
            d = self._data["payments"].get(file_id)
            return PaymentFile.from_dict(d) if d else None

    # ── 关联管理 ────────────────────────────────────────────

    def add_association(self, invoice_id: str, payment_id: str) -> bool:
        """建立发票与支付记录的关联（多对多）。"""
        with self._lock:
            inv = self._data["invoices"].get(invoice_id)
            pay = self._data["payments"].get(payment_id)
            if not inv or not pay:
                return False
            # 双写关联列表
            if payment_id not in inv.setdefault("linked_payment_ids", []):
                inv["linked_payment_ids"].append(payment_id)
            if invoice_id not in pay.setdefault("linked_invoice_ids", []):
                pay["linked_invoice_ids"].append(invoice_id)
            # 冗余关联表
            exists = any(
                a["invoice_id"] == invoice_id and a["payment_id"] == payment_id
                for a in self._data["associations"]
            )
            if not exists:
                self._data["associations"].append(
                    Association(invoice_id, payment_id, now_iso()).to_dict()
                )
            self._save()
            self._notify()
            return True

    def remove_association(self, invoice_id: str, payment_id: str) -> bool:
        """解除发票与支付记录的关联。"""
        with self._lock:
            inv = self._data["invoices"].get(invoice_id)
            pay = self._data["payments"].get(payment_id)
            if inv and payment_id in inv.get("linked_payment_ids", []):
                inv["linked_payment_ids"].remove(payment_id)
            if pay and invoice_id in pay.get("linked_invoice_ids", []):
                pay["linked_invoice_ids"].remove(invoice_id)
            self._data["associations"] = [
                a for a in self._data["associations"]
                if not (a["invoice_id"] == invoice_id and a["payment_id"] == payment_id)
            ]
            self._save()
            self._notify()
            return True

    def is_linked(self, invoice_id: str, payment_id: str) -> bool:
        """检查是否已关联。"""
        with self._lock:
            inv = self._data["invoices"].get(invoice_id)
            return bool(inv and payment_id in inv.get("linked_payment_ids", []))

    def rename_linked_files(self, invoice_id: str, payment_id: str,
                            new_base_name: str) -> tuple[str, str] | None:
        """重命名关联的发票与支付文件为统一基名（保留各自扩展名）。

        文件在磁盘上重命名后，同步更新 Store 内的路径、file_id 及所有交叉引用，
        下次重扫不会丢失关联。
        """
        with self._lock:
            inv = self._data["invoices"].get(invoice_id)
            pay = self._data["payments"].get(payment_id)
            if not inv or not pay:
                return None

            inv_dir = os.path.dirname(inv["abs_path"])
            pay_dir = os.path.dirname(pay["abs_path"])
            inv_new = os.path.join(inv_dir, new_base_name + inv["ext"])
            pay_new = os.path.join(pay_dir, new_base_name + pay["ext"])

            # 冲突检查（跳过自身，允许原地同名）
            for new_p, old_p in [(inv_new, inv["abs_path"]), (pay_new, pay["abs_path"])]:
                if new_p != old_p and os.path.exists(new_p):
                    return None

            # 磁盘重命名
            try:
                if inv_new != inv["abs_path"]:
                    os.rename(inv["abs_path"], inv_new)
                if pay_new != pay["abs_path"]:
                    os.rename(pay["abs_path"], pay_new)
            except OSError:
                return None

            # 生成新 file_id（路径变了但 mtime 不变）
            new_inv_id = generate_file_id(inv_new, inv["modified_iso"])
            new_pay_id = generate_file_id(pay_new, pay["modified_iso"])
            old_to_new = {}
            if new_inv_id != invoice_id:
                old_to_new[invoice_id] = new_inv_id
            if new_pay_id != payment_id:
                old_to_new[payment_id] = new_pay_id

            # 更新发票条目
            inv["abs_path"] = inv_new
            inv["file_name"] = os.path.basename(inv_new)
            if new_inv_id != invoice_id:
                inv["file_id"] = new_inv_id
                self._data["invoices"][new_inv_id] = inv
                del self._data["invoices"][invoice_id]

            # 更新支付条目
            pay["abs_path"] = pay_new
            pay["file_name"] = os.path.basename(pay_new)
            if new_pay_id != payment_id:
                pay["file_id"] = new_pay_id
                self._data["payments"][new_pay_id] = pay
                del self._data["payments"][payment_id]

            # 更新所有交叉引用：linked_*_ids 列表 + associations 表
            for old, new in old_to_new.items():
                for inv_d in self._data["invoices"].values():
                    lp = inv_d.get("linked_payment_ids", [])
                    if old in lp:
                        lp[lp.index(old)] = new
                for pay_d in self._data["payments"].values():
                    li = pay_d.get("linked_invoice_ids", [])
                    if old in li:
                        li[li.index(old)] = new
                for a in self._data["associations"]:
                    if a["invoice_id"] == old:
                        a["invoice_id"] = new
                    if a["payment_id"] == old:
                        a["payment_id"] = new

            self._save()
            self._notify()
            new_inv_name = inv["file_name"]
            new_pay_name = pay["file_name"]
            return (new_inv_name, new_pay_name)

    # ── 金额管理 ────────────────────────────────────────────

    def _set_amount(self, kind: str, file_id: str, recognized: float = None,
                    edited: float = None, raw_texts: list = None,
                    confidence: float = None, is_confirmed: bool = None):
        """设置文件金额信息。kind: 'payments' | 'invoices'"""
        with self._lock:
            entry = self._data[kind].get(file_id)
            if not entry:
                return
            amount = entry.setdefault("amount", AmountRecord().to_dict())
            if recognized is not None:
                amount["recognized"] = recognized
            if edited is not None:
                amount["edited"] = edited
            if raw_texts is not None:
                amount["raw_texts"] = raw_texts
            if confidence is not None:
                amount["confidence"] = confidence
            if is_confirmed is not None:
                amount["is_confirmed"] = is_confirmed
            amount["processed_at"] = now_iso()
            self._save()
            self._notify()

    def set_amount(self, payment_id: str, recognized: float = None,
                   edited: float = None, raw_texts: list = None,
                   confidence: float = None, is_confirmed: bool = None):
        """设置/更新支付记录的金额信息。"""
        self._set_amount("payments", payment_id, recognized=recognized,
                         edited=edited, raw_texts=raw_texts, confidence=confidence,
                         is_confirmed=is_confirmed)

    def get_confirmed_amounts(self, include_missing: bool = False) -> list[tuple[str, str, float]]:
        """获取所有已确认金额的支付记录。返回 [(payment_id, file_name, amount), ...]

        默认排除 missing（磁盘已删除、重扫后标记缺失）的记录，与
        get_payments()/get_summary() 保持一致，避免已删除记录仍计入总额。
        """
        with self._lock:
            result = []
            for fid, pay_dict in self._data["payments"].items():
                if not include_missing and pay_dict.get("missing"):
                    continue
                amount = pay_dict.get("amount", {})
                if amount.get("is_confirmed"):
                    # 用 final_amount：优先 edited，其次 recognized
                    rec = AmountRecord.from_dict(amount)
                    val = rec.final_amount
                    if val is not None:
                        result.append((fid, pay_dict.get("file_name", ""), val))
            return result


    # ── 组合（Combo）管理 ──────────────────────────────────

    def create_combo(self, kind: str, name: str, file_ids: list[str]) -> str:
        """创建组合：kind 为 'invoice' | 'payment'。

        成员 file_ids 有序、去重，仅保留当前存在且未缺失的文件。
        Returns:
            新组合的 combo_id
        """
        with self._lock:
            data_key = "invoices" if kind == "invoice" else "payments"
            valid: list[str] = []
            seen: set[str] = set()
            for fid in file_ids:
                if fid in seen:
                    continue
                seen.add(fid)
                entry = self._data[data_key].get(fid)
                if entry and not entry.get("missing"):
                    valid.append(fid)
            combo_id = "cb_" + uuid.uuid4().hex[:16]
            self._data.setdefault("combos", []).append({
                "combo_id": combo_id,
                "kind": kind,
                "name": (name or "未命名组合").strip(),
                "file_ids": valid,
                "created_at": now_iso(),
            })
            self._save()
            self._notify()
            return combo_id

    def delete_combo(self, combo_id: str) -> bool:
        """删除组合，返回是否删除成功。"""
        with self._lock:
            combos = self._data.get("combos", [])
            for i, c in enumerate(combos):
                if c["combo_id"] == combo_id:
                    combos.pop(i)
                    self._save()
                    self._notify()
                    return True
            return False

    def get_combos(self, kind: str) -> list[dict]:
        """获取指定类型的组合列表（副本，避免外部误改）。"""
        with self._lock:
            return [
                dict(c) for c in self._data.get("combos", [])
                if c.get("kind") == kind
            ]

    def get_combo(self, combo_id: str) -> Optional[dict]:
        """按 combo_id 获取组合（副本）。"""
        with self._lock:
            for c in self._data.get("combos", []):
                if c["combo_id"] == combo_id:
                    return dict(c)
            return None

    def add_combo_files(self, combo_id: str, file_ids: list[str]):
        """向组合追加成员（去重，仅保留存在且未缺失的文件）。"""
        with self._lock:
            combo = next(
                (c for c in self._data.get("combos", [])
                 if c["combo_id"] == combo_id),
                None,
            )
            if not combo:
                return
            data_key = "invoices" if combo["kind"] == "invoice" else "payments"
            for fid in file_ids:
                if fid in combo["file_ids"]:
                    continue
                entry = self._data[data_key].get(fid)
                if entry and not entry.get("missing"):
                    combo["file_ids"].append(fid)
            self._save()
            self._notify()

    def remove_combo_file(self, combo_id: str, file_id: str):
        """从组合移除成员文件（组合可留空）。"""
        with self._lock:
            combo = next(
                (c for c in self._data.get("combos", [])
                 if c["combo_id"] == combo_id),
                None,
            )
            if not combo:
                return
            if file_id in combo["file_ids"]:
                combo["file_ids"].remove(file_id)
                self._save()
                self._notify()

    def get_combo_total(self, combo_id: str) -> float:
        """组合成员 final_amount 求和（round 2），跳过 missing/无金额成员。"""
        with self._lock:
            combo = next(
                (c for c in self._data.get("combos", [])
                 if c["combo_id"] == combo_id),
                None,
            )
            if not combo:
                return 0.0
            data_key = "invoices" if combo["kind"] == "invoice" else "payments"
            total = 0.0
            for fid in combo.get("file_ids", []):
                entry = self._data[data_key].get(fid)
                if not entry or entry.get("missing"):
                    continue
                rec = AmountRecord.from_dict(entry.get("amount"))
                amt = rec.final_amount
                if amt is None:
                    continue
                total += amt
            return round(total, 2)

    # ── 自动比对 ────────────────────────────────────────────


    def get_amount_matches(self) -> list[dict]:
        """查找金额相同的未关联「文件组」配对。

        匹配单元为单文件或组合（成员 final_amount 求和）：
        - 单文件金额 ↔ 单文件金额
        - 组合总额 ↔ 单文件金额 / 单文件金额 ↔ 组合总额 / 组合总额 ↔ 组合总额
        任一成员已关联的候选跳过；missing 文件与无金额单元跳过。

        Returns:
            [{"invoice_ids": [str], "payment_ids": [str], "invoice_name": str,
              "payment_name": str, "amount": float,
              "is_combo_invoice": bool, "is_combo_payment": bool}, ...]
        """
        with self._lock:
            inv_units = self._build_match_units("invoices")
            pay_units = self._build_match_units("payments")

            # 已关联集合：任一成员已关联即跳过候选
            linked_pairs = {
                (a["invoice_id"], a["payment_id"])
                for a in self._data["associations"]
            }

            matches = []
            for iu in inv_units:
                for pu in pay_units:
                    if abs(iu["amount"] - pu["amount"]) > 0.01:
                        continue
                    if any(
                        (iid, pid) in linked_pairs
                        for iid in iu["ids"] for pid in pu["ids"]
                    ):
                        continue
                    matches.append({
                        "invoice_ids": list(iu["ids"]),
                        "payment_ids": list(pu["ids"]),
                        "invoice_name": iu["name"],
                        "payment_name": pu["name"],
                        "amount": round(iu["amount"], 2),
                        "is_combo_invoice": iu["is_combo"],
                        "is_combo_payment": pu["is_combo"],
                    })
            return matches

    def _build_match_units(self, data_key: str) -> list[dict]:
        """构建金额匹配单元列表：单文件（非组合成员）与组合。"""
        kind = "invoice" if data_key == "invoices" else "payment"
        member_ids: set[str] = set()
        combos = self._data.get("combos", [])
        for c in combos:
            if c.get("kind") == kind:
                member_ids.update(c.get("file_ids", []))

        units: list[dict] = []
        # 单文件单元（不在任何组合中）
        for fid, d in self._data[data_key].items():
            if d.get("missing") or fid in member_ids:
                continue
            rec = AmountRecord.from_dict(d.get("amount"))
            amt = rec.final_amount
            if amt is None:
                continue
            units.append({
                "ids": [fid],
                "name": d.get("file_name", ""),
                "amount": amt,
                "is_combo": False,
            })
        # 组合单元（成员金额求和，至少一个成员有金额才纳入）
        for c in combos:
            if c.get("kind") != kind:
                continue
            total = 0.0
            has_amount = False
            for fid in c.get("file_ids", []):
                entry = self._data[data_key].get(fid)
                if not entry or entry.get("missing"):
                    continue
                rec = AmountRecord.from_dict(entry.get("amount"))
                amt = rec.final_amount
                if amt is None:
                    continue
                total += amt
                has_amount = True
            if not has_amount:
                continue
            units.append({
                "ids": list(c["file_ids"]),
                "name": c.get("name", ""),
                "amount": round(total, 2),
                "is_combo": True,
            })
        return units


    def batch_link(self, pairs: list[dict], auto_linked: bool = True) -> int:
        """批量关联发票与支付记录（支持组合↔组合的成员两两组合）。

        Args:
            pairs: [{"invoice_ids": [str], "payment_ids": [str]}, ...]
                   兼容旧结构 {"invoice_id": str, "payment_id": str}
            auto_linked: 是否标记为自动关联

        Returns:
            成功关联的数量
        """
        count = 0
        with self._lock:
            for pair in pairs:
                inv_ids = pair.get("invoice_ids") or (
                    [pair["invoice_id"]] if pair.get("invoice_id") else []
                )
                pay_ids = pair.get("payment_ids") or (
                    [pair["payment_id"]] if pair.get("payment_id") else []
                )
                for inv_id in inv_ids:
                    for pay_id in pay_ids:
                        inv = self._data["invoices"].get(inv_id)
                        pay = self._data["payments"].get(pay_id)
                        if not inv or not pay:
                            continue
                        # 避免重复：检查双向关联列表 + 关联表
                        exists = (
                            pay_id in inv.setdefault("linked_payment_ids", [])
                            or any(
                                a["invoice_id"] == inv_id and a["payment_id"] == pay_id
                                for a in self._data["associations"]
                            )
                        )
                        if exists:
                            continue
                        inv["linked_payment_ids"].append(pay_id)
                        pay.setdefault("linked_invoice_ids", []).append(inv_id)
                        self._data["associations"].append(
                            Association(
                                inv_id, pay_id, now_iso(), auto_linked=auto_linked
                            ).to_dict()
                        )
                        count += 1
            if count > 0:
                self._save()
                self._notify()
        return count

    def _build_auto_link_index(self) -> set:
        """构建自动关联索引集合，用于 O(1) 查询。"""
        return {
            (a["invoice_id"], a["payment_id"])
            for a in self._data["associations"]
            if a.get("auto_linked", False)
        }

    def is_auto_linked(self, invoice_id: str, payment_id: str) -> bool:
        """检查是否为自动关联（O(1) 基于内存索引）。"""
        with self._lock:
            return (invoice_id, payment_id) in self._build_auto_link_index()

    def set_invoice_amount(self, invoice_id: str, recognized: float = None,
                           edited: float = None, raw_texts: list = None,
                           confidence: float = None, is_confirmed: bool = None):
        """设置发票的金额信息。"""
        self._set_amount("invoices", invoice_id, recognized=recognized,
                         edited=edited, raw_texts=raw_texts, confidence=confidence,
                         is_confirmed=is_confirmed)

    def get_summary(self) -> dict:
        """获取数据总览统计。"""
        with self._lock:
            invoices = [d for d in self._data["invoices"].values() if not d.get("missing")]
            payments = [d for d in self._data["payments"].values() if not d.get("missing")]
            linked_inv = sum(1 for i in invoices if i.get("linked_payment_ids"))
            linked_pay = sum(1 for p in payments if p.get("linked_invoice_ids"))
            confirmed = [p for p in payments
                         if p.get("amount", {}).get("is_confirmed")]
            total = sum(
                AmountRecord.from_dict(p.get("amount", {})).final_amount or 0
                for p in confirmed
            )
            return {
                "invoice_count": len(invoices),
                "payment_count": len(payments),
                "linked_invoices": linked_inv,
                "linked_payments": linked_pay,
                "confirmed_count": len(confirmed),
                "total_amount": round(total, 2),
            }
