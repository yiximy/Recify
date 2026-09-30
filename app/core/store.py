# -*- coding: utf-8 -*-
"""JSON 持久化：原子写 + 增量合并，是数据真相源"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import date
from typing import Iterable, Optional

from .models import (
    InvoiceFile, PaymentFile, Association, AmountRecord,
    generate_file_id, now_iso, normalize_tags,
)
from .rename_plan import (
    has_target_conflict, plan_target_paths, remap_dict_keys, rename_paths,
)
from .file_identity import plan_rename_adoptions
from .tag_stats import build_tag_stats


def _parse_iso_date(value: str):
    """解析 ISO 日期字符串（YYYY-MM-DD）；非法/为空返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


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
        # 最近一次 merge 的改名自愈结果：[(旧文件名, 新文件名), ...]，供 UI 提示
        self.last_rename_adoptions: list[tuple[str, str]] = []

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

    def merge_invoices(self, scanned: list[InvoiceFile],
                       mark_missing: bool = True):
        """增量合并发票扫描结果，保留已有关联。

        Args:
            mark_missing: True=本次未扫到的同类型文件标 missing（文件夹切换替换语义）；
                False=纯增量累加（画布多文件夹并集场景，不误伤其他活动文件夹）。
        """
        with self._lock:
            existing = self._data["invoices"]
            new_ids = {inv.file_id for inv in scanned}
            self.last_rename_adoptions = []
            # 标记缺失文件
            if mark_missing:
                # True（默认）= 替换语义：本次未扫到的同类型文件全部标 missing
                for fid, inv_dict in existing.items():
                    if fid not in new_ids:
                        inv_dict["missing"] = True
            else:
                # False = 增量累加：仅对「本次扫描文件夹内」消失的文件定向标 missing，
                # 其它活动文件夹不受影响（画布多文件夹场景）
                scanned_dirs = {self._dir_key(inv.abs_path) for inv in scanned}
                for fid, inv_dict in existing.items():
                    if fid not in new_ids and inv_dict.get("abs_path") \
                            and self._dir_key(inv_dict["abs_path"]) in scanned_dirs:
                        inv_dict["missing"] = True
            # 改名自愈规划：此刻新记录尚未写入 existing，可据 id 差异识别
            rename_plan = plan_rename_adoptions(scanned, existing)
            # 合并新扫描结果（保留 linked_payment_ids）
            for inv in scanned:
                if inv.file_id in existing:
                    old = existing[inv.file_id]
                    inv.linked_payment_ids = old.get("linked_payment_ids", [])
                    inv.tags = normalize_tags(old.get("tags", []))
                    inv.amount = AmountRecord.from_dict(old.get("amount"))
                    if old.get("document_date"):
                        inv.document_date = old.get("document_date", "")
                        inv.document_date_source = old.get("document_date_source", "")
                existing[inv.file_id] = inv.to_dict()
            # 改名自愈落地：接管金额/日期/关联并重映射交叉引用
            self._adopt_renamed("invoices", "linked_payment_ids", rename_plan)
            # 重扫后清理「成员全部缺失/不存在」的空壳发票组合（保留部分缺失组合）
            self._prune_shell_combos("invoice")
            self._save()
            self._notify()

    def merge_payments(self, scanned: list[PaymentFile],
                       mark_missing: bool = True):
        """增量合并支付记录扫描结果，保留已有关联和金额。

        Args:
            mark_missing: 同 merge_invoices，True=替换语义，False=增量累加。
        """
        with self._lock:
            existing = self._data["payments"]
            new_ids = {pay.file_id for pay in scanned}
            self.last_rename_adoptions = []
            if mark_missing:
                # True（默认）= 替换语义
                for fid, pay_dict in existing.items():
                    if fid not in new_ids:
                        pay_dict["missing"] = True
            else:
                # False = 增量累加：仅定向清理本次扫描文件夹内消失的文件
                scanned_dirs = {self._dir_key(pay.abs_path) for pay in scanned}
                for fid, pay_dict in existing.items():
                    if fid not in new_ids and pay_dict.get("abs_path") \
                            and self._dir_key(pay_dict["abs_path"]) in scanned_dirs:
                        pay_dict["missing"] = True
            # 改名自愈规划：此刻新记录尚未写入 existing，可据 id 差异识别
            rename_plan = plan_rename_adoptions(scanned, existing)
            for pay in scanned:
                if pay.file_id in existing:
                    old = existing[pay.file_id]
                    pay.linked_invoice_ids = old.get("linked_invoice_ids", [])
                    pay.tags = normalize_tags(old.get("tags", []))
                    pay.amount = AmountRecord.from_dict(old.get("amount"))
                    if old.get("document_date"):
                        pay.document_date = old.get("document_date", "")
                        pay.document_date_source = old.get("document_date_source", "")
                existing[pay.file_id] = pay.to_dict()
            # 改名自愈落地：接管金额/日期/关联并重映射交叉引用
            self._adopt_renamed("payments", "linked_invoice_ids", rename_plan)
            # 重扫后清理「成员全部缺失/不存在」的空壳支付组合（保留部分缺失组合）
            self._prune_shell_combos("payment")
            self._save()
            self._notify()

    def _adopt_renamed(self, data_key: str, link_key: str,
                       plan: list[tuple[str, str]]):
        """改名自愈落地：把 missing 旧记录的身份接管给被识别的新记录。

        对每条 ``(旧 id, 新 id)`` 配对：新记录继承 OCR 金额、票面/手动日期与
        关联列表；删除旧 missing 记录（避免被后续文件重复认领）；最后统一
        重映射交叉引用（linked_*_ids / associations / combos.file_ids）。
        记录 (旧名, 新名) 到 ``last_rename_adoptions`` 供 UI 提示。
        """
        if not plan:
            return
        existing = self._data[data_key]
        old_to_new = dict(plan)
        for old_id, new_id in plan:
            old = existing.get(old_id)
            new = existing.get(new_id)
            if old is None or new is None:
                continue
            new["amount"] = old.get("amount", AmountRecord().to_dict())
            new[link_key] = list(old.get(link_key, []))
            new["tags"] = normalize_tags(old.get("tags", []))
            if old.get("document_date"):
                new["document_date"] = old["document_date"]
                new["document_date_source"] = old.get("document_date_source", "")
            self.last_rename_adoptions.append(
                (old.get("file_name", ""), new.get("file_name", ""))
            )
            del existing[old_id]
        self._remap_file_ids(old_to_new)

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

    def prune_dangling_links(self, file_id: str) -> int:
        """清理该文件指向「记录不存在 / missing」对象的失效关联，返回条数。

        只处理该文件自身一侧的 ``linked_*_ids`` 与对应 ``associations`` 冗余
        条目，不改动对方记录（不静默丢数据、不越权修改无关记录）。
        选择「按文件」而非「按 kind 全局」的理由：右键入口天然是单文件语义，
        作用域最小、可解释；全局清理会一次性改动用户未主动触发的数据。
        """
        with self._lock:
            removed = 0
            for data_key, link_key, partner_key in (
                ("invoices", "linked_payment_ids", "payments"),
                ("payments", "linked_invoice_ids", "invoices"),
            ):
                entry = self._data[data_key].get(file_id)
                if entry is None:
                    continue
                valid: list[str] = []
                dangling: set[str] = set()
                for partner_id in list(entry.get(link_key, [])):
                    partner = self._data[partner_key].get(partner_id)
                    if partner is not None and not partner.get("missing"):
                        valid.append(partner_id)
                    else:
                        dangling.add(partner_id)
                        removed += 1
                if not dangling:
                    continue
                entry[link_key] = valid
                if data_key == "invoices":
                    self._data["associations"] = [
                        a for a in self._data["associations"]
                        if not (a["invoice_id"] == file_id
                                and a["payment_id"] in dangling)
                    ]
                else:
                    self._data["associations"] = [
                        a for a in self._data["associations"]
                        if not (a["payment_id"] == file_id
                                and a["invoice_id"] in dangling)
                    ]
            if removed:
                self._save()
                self._notify()
            return removed

    def get_associations(self) -> list[dict]:
        """获取关联表副本（供导出等只读消费，避免外部误改内部数据）。"""
        with self._lock:
            return [dict(a) for a in self._data.get("associations", [])]

    def rename_group(self, invoice_ids: list[str], payment_ids: list[str],
                     new_base: str,
                     combo_ids: Iterable[str] = ()) -> list[str] | None:
        """把一组发票与支付文件统一重命名为 new_base（保留各自扩展名）。

        组内文件按 (所在目录, 扩展名) 分组编号：第 1 个为 <new_base><ext>，
        其后依次 _2、_3…；同目录同扩展名保证唯一，跨目录/跨扩展名互不影响。
        冲突即失败（不自动跳号）：任一目标路径被本组之外的文件占用则返回 None；
        任一磁盘重命名失败则回滚已改文件，保证磁盘与 Store 一致。

        Args:
            combo_ids: 需要同步改名的组合 id（其 name 改为 new_base）。

        Returns:
            按 [invoice_ids..., payment_ids...] 顺序的新文件名列表；失败返回 None。
        """
        with self._lock:
            entries: list[dict] = []
            seen_inv: set[str] = set()
            for iid in invoice_ids:
                if iid in seen_inv:
                    continue
                seen_inv.add(iid)
                entry = self._data["invoices"].get(iid)
                if entry is None:
                    return None
                entries.append(entry)
            seen_pay: set[str] = set()
            for pid in payment_ids:
                if pid in seen_pay:
                    continue
                seen_pay.add(pid)
                entry = self._data["payments"].get(pid)
                if entry is None:
                    return None
                entries.append(entry)
            if not entries or not new_base:
                return None

            targets = plan_target_paths(entries, new_base)
            if has_target_conflict(entries, targets):
                return None

            old_to_new: dict[str, str] = {}
            for entry, target in zip(entries, targets):
                new_id = generate_file_id(target, entry["modified_iso"])
                if new_id != entry["file_id"]:
                    old_to_new[entry["file_id"]] = new_id
            new_invoices = remap_dict_keys(self._data["invoices"], old_to_new)
            new_payments = remap_dict_keys(self._data["payments"], old_to_new)
            if new_invoices is None or new_payments is None:
                return None

            pairs = list(zip([e["abs_path"] for e in entries], targets))
            if not rename_paths(pairs):
                return None

            for entry, target in zip(entries, targets):
                entry["abs_path"] = target
                entry["file_name"] = os.path.basename(target)
                entry["file_id"] = old_to_new.get(
                    entry["file_id"], entry["file_id"]
                )
            self._data["invoices"] = new_invoices
            self._data["payments"] = new_payments
            if old_to_new:
                self._remap_file_ids(old_to_new)
            for combo_id in dict.fromkeys(combo_ids):
                combo = next(
                    (c for c in self._data.get("combos", [])
                     if c["combo_id"] == combo_id),
                    None,
                )
                if combo:
                    combo["name"] = new_base

            self._save()
            self._notify()
            return [os.path.basename(t) for t in targets]

    def _remap_file_ids(self, old_to_new: dict[str, str]):
        """把交叉引用（linked_*_ids / associations / combos.file_ids）旧 id 换新。"""
        for old, new in old_to_new.items():
            for inv_d in self._data["invoices"].values():
                linked = inv_d.get("linked_payment_ids", [])
                if old in linked:
                    linked[linked.index(old)] = new
            for pay_d in self._data["payments"].values():
                linked = pay_d.get("linked_invoice_ids", [])
                if old in linked:
                    linked[linked.index(old)] = new
            for assoc in self._data["associations"]:
                if assoc["invoice_id"] == old:
                    assoc["invoice_id"] = new
                if assoc["payment_id"] == old:
                    assoc["payment_id"] = new
            for combo in self._data.get("combos", []):
                if old in combo.get("file_ids", []):
                    combo["file_ids"] = [
                        new if fid == old else fid
                        for fid in combo["file_ids"]
                    ]

    def rename_linked_files(self, invoice_id: str, payment_id: str,
                            new_base_name: str) -> tuple[str, str] | None:
        """薄封装：转调 rename_group([invoice_id], [payment_id])。

        保持既有返回值 (发票新名, 支付新名) 与失败返回 None 的语义。
        """
        names = self.rename_group([invoice_id], [payment_id], new_base_name)
        if names is None or len(names) != 2:
            return None
        return names[0], names[1]

    def group_link_exists(self, invoice_ids: Iterable[str],
                          payment_ids: Iterable[str]) -> bool:
        """两组文件之间是否存在至少 1 条关联。"""
        with self._lock:
            pay_set = set(payment_ids)
            for iid in invoice_ids:
                inv = self._data["invoices"].get(iid)
                if inv and pay_set.intersection(
                        inv.get("linked_payment_ids", [])):
                    return True
            return False

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

    # ── 日期管理 ────────────────────────────────────────────

    def set_document_date(self, kind: str, file_id: str,
                          date_iso: str, source: str) -> None:
        """设置文件的票面日期及来源。kind 支持 invoice/payment 单复数形式。"""
        data_key = {
            "invoice": "invoices",
            "invoices": "invoices",
            "payment": "payments",
            "payments": "payments",
        }.get(kind)
        if data_key is None:
            return
        with self._lock:
            entry = self._data[data_key].get(file_id)
            if not entry:
                return
            entry["document_date"] = date_iso or ""
            entry["document_date_source"] = source or ""
            self._save()
            self._notify()

    @staticmethod
    def get_document_date(file: object) -> tuple[str, str]:
        """读取文件日期；日期为空或非法时回退 modified_iso 的日期部分。

        返回 ``(date_iso, source)``。该函数是引擎与 UI 共用的唯一回退入口。
        """
        if isinstance(file, dict):
            document_date = file.get("document_date", "") or ""
            document_date_source = file.get("document_date_source", "") or ""
            modified_iso = file.get("modified_iso", "") or ""
        else:
            document_date = getattr(file, "document_date", "") or ""
            document_date_source = getattr(file, "document_date_source", "") or ""
            modified_iso = getattr(file, "modified_iso", "") or ""

        document_date = str(document_date).strip()
        if document_date:
            try:
                date.fromisoformat(document_date)
            except ValueError:
                pass
            else:
                return document_date, str(document_date_source).strip()

        return str(modified_iso)[:10], "file"

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
                "tags": [],
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
            result: list[dict] = []
            for c in self._data.get("combos", []):
                if c.get("kind") != kind:
                    continue
                combo = dict(c)
                combo["tags"] = normalize_tags(combo.get("tags", []))
                result.append(combo)
            return result

    def get_combo(self, combo_id: str) -> Optional[dict]:
        """按 combo_id 获取组合（副本）。"""
        with self._lock:
            for c in self._data.get("combos", []):
                if c["combo_id"] == combo_id:
                    combo = dict(c)
                    combo["tags"] = normalize_tags(combo.get("tags", []))
                    return combo
            return None

    def combo_has_active_members(self, combo_id: str) -> bool:
        """组合是否存在至少 1 个「当前存在且未缺失」的成员。

        空壳组合（成员文件已全部删除/重扫标记缺失）应被 UI 候选过滤并在
        merge 后清理；部分缺失组合（仍有可用成员）视为有效。
        """
        with self._lock:
            combo = next(
                (c for c in self._data.get("combos", [])
                 if c["combo_id"] == combo_id),
                None,
            )
            if not combo:
                return False
            data_key = "invoices" if combo["kind"] == "invoice" else "payments"
            return any(
                fid in self._data[data_key]
                and not self._data[data_key][fid].get("missing")
                for fid in combo.get("file_ids", [])
            )

    def _prune_shell_combos(self, kind: str) -> int:
        """移除该 kind 下「成员全部缺失/不存在」的空壳组合，返回删除数量。

        仅在 merge_invoices/merge_payments 重扫后调用（本方法不主动保存，
        由调用方统一 _save/_notify）：重扫标 missing 后组合内文件已全部消失，
        保留无意义（引擎本就跳过、UI 也不应暴露），自动清理避免空壳累积。
        语义取舍：只删「全部成员缺失」的组合；部分缺失组合保留，由 UI 标注。
        注意：既有 store.json 中的存量空壳组合不在此被动清理范围（不主动改用户数据），
        仅保证未来重扫不再累积；展示层另有过滤双保险。
        """
        data_key = "invoices" if kind == "invoice" else "payments"
        removed = 0
        kept: list[dict] = []
        for c in self._data.get("combos", []):
            if c.get("kind") != kind:
                kept.append(c)
                continue
            alive = any(
                fid in self._data[data_key]
                and not self._data[data_key][fid].get("missing")
                for fid in c.get("file_ids", [])
            )
            if alive:
                kept.append(c)
            else:
                removed += 1
        if removed:
            self._data["combos"] = kept
        return removed

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

    # ── 标签（Tag）管理 ────────────────────────────────────

    def set_file_tags(self, kind: str, file_id: str, tags: list) -> None:
        """替换单个发票/支付记录文件的标签（规范化后写库）。"""
        with self._lock:
            data_key = "invoices" if kind == "invoice" else "payments"
            entry = self._data[data_key].get(file_id)
            if entry is None:
                return
            entry["tags"] = normalize_tags(tags)
            self._save()
            self._notify()

    def set_combo_tags(self, combo_id: str, tags: list) -> None:
        """替换单个组合的标签（规范化后写库）。"""
        with self._lock:
            for combo in self._data.get("combos", []):
                if combo["combo_id"] == combo_id:
                    combo["tags"] = normalize_tags(tags)
                    self._save()
                    self._notify()
                    return

    def get_all_tags(self) -> list[str]:
        """返回全部现存标签：按使用次数降序、同次数按名称升序。

        计数口径为「标签出现次数」：文件标签与组合标签各计一次。
        """
        with self._lock:
            counts: dict[str, int] = {}
            for data_key in ("invoices", "payments"):
                for entry in self._data[data_key].values():
                    for tag in normalize_tags(entry.get("tags", [])):
                        counts[tag] = counts.get(tag, 0) + 1
            for combo in self._data.get("combos", []):
                for tag in normalize_tags(combo.get("tags", [])):
                    counts[tag] = counts.get(tag, 0) + 1
            return sorted(counts, key=lambda t: (-counts[t], t))

    @staticmethod
    def format_date_range(start_iso: str, end_iso: str) -> str:
        """日期区间显示：同年 2026.6.30-7.21；跨年 2026.12.30-2027.1.5；同天 2026.6.30。"""
        start = _parse_iso_date(start_iso)
        end = _parse_iso_date(end_iso)
        if start is None and end is None:
            return ""
        if start is None:
            start = end
        if end is None:
            end = start
        head = f"{start.year}.{start.month}.{start.day}"
        if start == end:
            return head
        if start.year == end.year:
            tail = f"{end.month}.{end.day}"
        else:
            tail = f"{end.year}.{end.month}.{end.day}"
        return f"{head}-{tail}"

    def get_tag_stats(self) -> dict:
        """按标签统计（唯一口径，供对话框预览与导出共用）。

        详细口径见 ``app.core.tag_stats`` 模块文档字符串。
        """
        with self._lock:
            return build_tag_stats(self)

    # ── 自动比对 ────────────────────────────────────────────


    def get_amount_matches(
        self,
        invoice_folders: Optional[Iterable[str]] = None,
        payment_folders: Optional[Iterable[str]] = None,
        tolerance: float = 0.01,
        include_combos: bool = True,
        time_tolerance_days: Optional[int] = None,
    ) -> list[dict]:
        """查找金额相同的未关联「文件组」配对。

        匹配单元为单文件或组合（成员 final_amount 求和）：
        - 单文件金额 ↔ 单文件金额
        - 组合总额 ↔ 单文件金额 / 单文件金额 ↔ 组合总额 / 组合总额 ↔ 组合总额
        任一成员已关联的候选跳过；missing 文件与无金额单元跳过。
        开启时间条件时，按双方日期区间最近距离过滤；区间重叠距离为 0 天。

        Args:
            invoice_folders: 可选，发票侧文件夹过滤（目录路径，取并集）。
                单文件单元要求所在目录在集合内；组合单元要求全部非 missing
                成员所在目录在集合内（跨界组合整组跳过）。
            payment_folders: 可选，支付侧文件夹过滤，语义同上。
            tolerance: 金额误差阈值（元），abs 差 ≤ tolerance 视为相同。
            include_combos: 是否纳入组合单元（组合成员不单独匹配的语义不变）。
            time_tolerance_days: 时间容差（天）；None 表示不过滤，旧行为不变。

        Returns:
            [{"invoice_ids": [str], "payment_ids": [str], "invoice_name": str,
              "payment_name": str, "amount": float,
              "is_combo_invoice": bool, "is_combo_payment": bool}, ...]
        """
        with self._lock:
            inv_folders = self._norm_folders(invoice_folders)
            pay_folders = self._norm_folders(payment_folders)
            inv_units = self._build_match_units(
                "invoices", folder_set=inv_folders, include_combos=include_combos,
            )
            pay_units = self._build_match_units(
                "payments", folder_set=pay_folders, include_combos=include_combos,
            )

            # 已关联集合：任一成员已关联即跳过候选
            linked_pairs = {
                (a["invoice_id"], a["payment_id"])
                for a in self._data["associations"]
            }

            matches = []
            for iu in inv_units:
                for pu in pay_units:
                    if abs(iu["amount"] - pu["amount"]) > tolerance:
                        continue
                    if time_tolerance_days is not None:
                        distance = self._date_range_distance_days(
                            iu.get("date_range"), pu.get("date_range")
                        )
                        if distance is None or distance > time_tolerance_days:
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

    @staticmethod
    def _norm_folders(folders: Optional[Iterable[str]]) -> Optional[set[str]]:
        """归一化文件夹集合（normcase + abspath）；None 或空返回 None 表示不过滤。"""
        if not folders:
            return None
        return {os.path.normcase(os.path.abspath(f)) for f in folders}

    @staticmethod
    def _dir_key(abs_path: str) -> str:
        """文件所在目录的归一化键（normcase + abspath），用于文件夹范围判定。"""
        return os.path.normcase(os.path.abspath(os.path.dirname(abs_path)))

    @staticmethod
    def _date_range_distance_days(
        left: Optional[tuple[date, date]],
        right: Optional[tuple[date, date]],
    ) -> Optional[int]:
        """返回两个日期区间的最近天数；无法判定时为 None。"""
        if left is None or right is None:
            return None
        left_start, left_end = left
        right_start, right_end = right
        if left_end < right_start:
            return (right_start - left_end).days
        if right_end < left_start:
            return (left_start - right_end).days
        return 0

    def _build_match_units(self, data_key: str,
                           folder_set: Optional[set[str]] = None,
                           include_combos: bool = True) -> list[dict]:
        """构建金额匹配单元列表：单文件（非组合成员）与组合。

        Args:
            data_key: "invoices" | "payments"
            folder_set: 可选目录集合（已归一化）。单文件单元要求所在目录在集合内；
                组合单元要求全部非 missing 成员所在目录在集合内。
            单文件日期区间为自身日期；组合日期区间为非 missing 成员的 [min, max]。
            include_combos: False 时不产出组合单元（成员保持“不单独匹配”）。
        """
        kind = "invoice" if data_key == "invoices" else "payment"
        member_ids: set[str] = set()
        combos = self._data.get("combos", [])
        for c in combos:
            if c.get("kind") == kind:
                member_ids.update(c.get("file_ids", []))

        def _in_scope(d: dict) -> bool:
            """单个文件条目是否在文件夹范围内（folder_set 为 None 时全放行）。"""
            if folder_set is None:
                return True
            return self._dir_key(d.get("abs_path", "")) in folder_set

        def _entry_date(entry: dict) -> Optional[date]:
            """读取文件日期并提供统一回退。"""
            date_iso, _ = self.get_document_date(entry)
            try:
                return date.fromisoformat(date_iso)
            except ValueError:
                return None

        units: list[dict] = []
        # 单文件单元（不在任何组合中）
        for fid, d in self._data[data_key].items():
            if d.get("missing") or fid in member_ids:
                continue
            if not _in_scope(d):
                continue
            rec = AmountRecord.from_dict(d.get("amount"))
            amt = rec.final_amount
            if amt is None:
                continue
            unit_date = _entry_date(d)
            date_range = (unit_date, unit_date) if unit_date is not None else None
            units.append({
                "ids": [fid],
                "name": d.get("file_name", ""),
                "amount": amt,
                "is_combo": False,
                "date_range": date_range,
            })
        # 组合单元（成员金额求和，至少一个成员有金额才纳入）
        if include_combos:
            for c in combos:
                if c.get("kind") != kind:
                    continue
                if folder_set is not None:
                    # 跨界组合（含选区外非 missing 成员）整组跳过
                    out_of_scope = False
                    for fid in c.get("file_ids", []):
                        entry = self._data[data_key].get(fid)
                        if entry and not entry.get("missing") and not _in_scope(entry):
                            out_of_scope = True
                            break
                    if out_of_scope:
                        continue
                total = 0.0
                has_amount = False
                member_dates: list[date] = []
                for fid in c.get("file_ids", []):
                    entry = self._data[data_key].get(fid)
                    if not entry or entry.get("missing"):
                        continue
                    member_date = _entry_date(entry)
                    if member_date is not None:
                        member_dates.append(member_date)
                    rec = AmountRecord.from_dict(entry.get("amount"))
                    amt = rec.final_amount
                    if amt is None:
                        continue
                    total += amt
                    has_amount = True
                if not has_amount:
                    continue
                date_range = None
                if member_dates:
                    date_range = (min(member_dates), max(member_dates))
                units.append({
                    "ids": list(c["file_ids"]),
                    "name": c.get("name", ""),
                    "amount": round(total, 2),
                    "is_combo": True,
                    "date_range": date_range,
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
