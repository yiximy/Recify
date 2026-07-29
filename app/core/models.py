# -*- coding: utf-8 -*-
"""数据模型：领域对象定义（纯 Python，不依赖 Qt）"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


def generate_file_id(abs_path: str, modified_iso: str) -> str:
    """基于文件绝对路径 + 修改时间生成稳定 ID。

    路径不变即可复现，重扫后增量合并而非覆盖。
    """
    raw = f"{abs_path}|{modified_iso}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class FileInfo:
    """文件基础信息"""
    file_id: str
    file_name: str
    abs_path: str
    size_bytes: int
    modified_iso: str
    ext: str
    missing: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FileInfo":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class AmountRecord:
    """金额识别与编辑记录"""
    raw_texts: list = field(default_factory=list)       # OCR 原始文本片段
    recognized: Optional[float] = None                   # OCR 识别金额
    edited: Optional[float] = None                       # 用户手动修正金额
    is_confirmed: bool = False                           # 是否已确认
    confidence: float = 0.0                              # 识别置信度
    processed_at: str = ""                               # 处理时间 ISO

    @property
    def final_amount(self) -> Optional[float]:
        """最终金额：优先用户编辑，其次识别值"""
        if self.edited is not None:
            return self.edited
        return self.recognized

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AmountRecord":
        if d is None:
            return cls()
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class InvoiceFile(FileInfo):
    """发票文件（PDF）"""
    page_count: int = 0
    linked_payment_ids: list = field(default_factory=list)
    amount: AmountRecord = field(default_factory=AmountRecord)

    def to_dict(self) -> dict:
        d = FileInfo.to_dict(self)
        d["page_count"] = self.page_count
        d["linked_payment_ids"] = self.linked_payment_ids
        d["amount"] = self.amount.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "InvoiceFile":
        base = FileInfo.from_dict(d)
        return cls(
            **{k: getattr(base, k) for k in FileInfo.__dataclass_fields__},
            page_count=d.get("page_count", 0),
            linked_payment_ids=d.get("linked_payment_ids", []),
            amount=AmountRecord.from_dict(d.get("amount")),
        )


@dataclass
class PaymentFile(FileInfo):
    """支付记录文件（图片）"""
    linked_invoice_ids: list = field(default_factory=list)
    amount: AmountRecord = field(default_factory=AmountRecord)

    def to_dict(self) -> dict:
        d = FileInfo.to_dict(self)
        d["linked_invoice_ids"] = self.linked_invoice_ids
        d["amount"] = self.amount.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PaymentFile":
        base = FileInfo.from_dict(d)
        return cls(
            **{k: getattr(base, k) for k in FileInfo.__dataclass_fields__},
            linked_invoice_ids=d.get("linked_invoice_ids", []),
            amount=AmountRecord.from_dict(d.get("amount")),
        )


@dataclass
class Association:
    """发票与支付记录的关联关系"""
    invoice_id: str
    payment_id: str
    created_at: str = ""
    auto_linked: bool = False          # 是否为自动关联（非人工确认）

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Association":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def now_iso() -> str:
    """当前时间 ISO 字符串"""
    return datetime.now().isoformat(timespec="seconds")
