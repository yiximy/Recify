# -*- coding: utf-8 -*-
"""JSON 持久化：原子写 + 增量合并，是数据真相源"""
from __future__ import annotations

import json
import os
import threading
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

    # ── 自动比对 ────────────────────────────────────────────

    def get_amount_matches(self) -> list[dict]:
        """查找金额相同的未关联发票-支付记录配对。

        基于 final_amount 匹配（优先 edited > recognized）。
        仅匹配双方均已有金额且尚未互相关联的记录。

        Returns:
            [{"invoice_id": str, "payment_id": str, "invoice_name": str,
              "payment_name": str, "amount": float}, ...]
        """
        with self._lock:
            # 直接从原始数据构建，避免内部递归加锁
            inv_dicts = [
                (fid, d) for fid, d in self._data["invoices"].items()
                if not d.get("missing")
            ]
            pay_dicts = [
                (fid, d) for fid, d in self._data["payments"].items()
                if not d.get("missing")
            ]

            # 构建已关联集合
            linked_pairs = {
                (a["invoice_id"], a["payment_id"])
                for a in self._data["associations"]
            }

            matches = []
            for inv_id, inv_d in inv_dicts:
                inv_amount = inv_d.get("amount", {})
                inv_rec = AmountRecord.from_dict(inv_amount)
                inv_amt = inv_rec.final_amount
                if inv_amt is None:
                    continue

                for pay_id, pay_d in pay_dicts:
                    pay_amount = pay_d.get("amount", {})
                    pay_rec = AmountRecord.from_dict(pay_amount)
                    pay_amt = pay_rec.final_amount
                    if pay_amt is None:
                        continue

                    if abs(inv_amt - pay_amt) > 0.01:
                        continue

                    if (inv_id, pay_id) in linked_pairs:
                        continue

                    matches.append({
                        "invoice_id": inv_id,
                        "payment_id": pay_id,
                        "invoice_name": inv_d["file_name"],
                        "payment_name": pay_d["file_name"],
                        "amount": round(inv_amt, 2),
                    })

            return matches

    def batch_link(self, pairs: list[dict], auto_linked: bool = True) -> int:
        """批量关联发票与支付记录。

        Args:
            pairs: [{"invoice_id": str, "payment_id": str}, ...]
            auto_linked: 是否标记为自动关联

        Returns:
            成功关联的数量
        """
        count = 0
        with self._lock:
            for pair in pairs:
                inv_id = pair["invoice_id"]
                pay_id = pair["payment_id"]
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
                    Association(inv_id, pay_id, now_iso(), auto_linked=auto_linked).to_dict()
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
