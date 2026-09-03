# -*- coding: utf-8 -*-
"""流程画布数据模型（Qt-free）：节点 / 连线 / 绑定语义 / 链校验。

与 UI 解耦：本模块不依赖 Qt，便于纯逻辑验证（can_connect v2 矩阵 /
validate / executable_chains）。绑定解析依赖外部「store」对象（鸭子类型，
只需 get_invoice / get_payment / get_combo 等方法），由调用方注入。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

# ── 模块类型常量 ──
KIND_INVOICE = "invoice"
KIND_PAYMENT = "payment"
KIND_MATCH = "match"
KIND_LABELS = {
    KIND_INVOICE: "电子发票",
    KIND_PAYMENT: "支付记录",
    KIND_MATCH: "匹配",
}
KIND_SOURCES = {KIND_INVOICE, KIND_PAYMENT}

DEFAULT_PARAMS = {"tolerance": 0.01}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@dataclass
class FlowNode:
    """画布上的一个模块节点。

    字段：
        node_id: 唯一标识
        kind: KIND_INVOICE / KIND_PAYMENT / KIND_MATCH
        name: 展示名（可编辑；自动铺时源=文件/组合名、匹配=「匹配 ¥金额」）
        file_ids: 源模块直接绑定的单文件（非组合成员）
        combo_ids: 源模块绑定的组合整组（combo_id 引用）
        params: 匹配模块参数，仅 {"tolerance": float}
        x/y: 卡片左上角在画布场景坐标系中的位置
    """

    node_id: str
    kind: str
    name: str
    file_ids: list[str] = field(default_factory=list)
    combo_ids: list[str] = field(default_factory=list)
    params: dict = field(default_factory=lambda: dict(DEFAULT_PARAMS))
    x: float = 0.0
    y: float = 0.0

    @property
    def is_source(self) -> bool:
        return self.kind in KIND_SOURCES

    # ── 绑定派生语义（store 注入，Qt-free）──

    def _member_getter(self, store):
        """按 kind 返回文件查询函数（get_invoice / get_payment），匹配模块为 None。"""
        if self.kind == KIND_INVOICE:
            return store.get_invoice
        if self.kind == KIND_PAYMENT:
            return store.get_payment
        return None

    def _iter_member_ids(self, store):
        """产出有效成员 file_id（直接绑定 + 组合成员，去重，跳过 missing/已删除）。

        组合已删除或类型不符时整组忽略；组合内成员同样做 missing 过滤。
        """
        getter = self._member_getter(store)
        if getter is None:
            return
        seen: set[str] = set()
        for fid in self.file_ids:
            f = getter(fid)
            if f is None or getattr(f, "missing", False):
                continue
            if fid not in seen:
                seen.add(fid)
                yield fid
        for cid in self.combo_ids:
            combo = store.get_combo(cid)
            if not combo or combo.get("kind") != self.kind:
                continue
            for fid in combo.get("file_ids", []):
                f = getter(fid)
                if f is None or getattr(f, "missing", False):
                    continue
                if fid not in seen:
                    seen.add(fid)
                    yield fid

    def canonical_file_ids(self, store) -> list[str]:
        """解析绑定为去重后的真实文件 id 列表（跳过 missing/已删除/类型不符）。"""
        return list(self._iter_member_ids(store))

    def is_bound(self, store) -> bool:
        """是否已绑定至少一个真实文件。"""
        return bool(self.canonical_file_ids(store))

    def bind_amount(self, store) -> float:
        """Σ 口径：全部绑定成员 final_amount 求和（round 2）。

        跳过 missing 与无金额成员（与引擎 _build_match_units 的组合求和一致）；
        单文件=自身金额、组合=成员求和、多绑定=全部求和。
        注意：所有成员都无金额时返回 0.0，调用方应先用 has_amount() 判定，
        勿把 0.0 当作真实金额参与容差比较。
        """
        if self.kind not in KIND_SOURCES:
            return 0.0
        getter = self._member_getter(store)
        if getter is None:
            return 0.0
        total = 0.0
        for fid in self._iter_member_ids(store):
            f = getter(fid)
            if f is None:
                continue
            amt = getattr(getattr(f, "amount", None), "final_amount", None)
            if amt is None:
                continue
            total += amt
        return round(total, 2)

    def has_amount(self, store) -> bool:
        """绑定成员中是否存在至少一个 final_amount（未识别/无金额时为 False）。"""
        if self.kind not in KIND_SOURCES:
            return False
        getter = self._member_getter(store)
        if getter is None:
            return False
        for fid in self._iter_member_ids(store):
            f = getter(fid)
            if f is None:
                continue
            amt = getattr(getattr(f, "amount", None), "final_amount", None)
            if amt is not None:
                return True
        return False


@dataclass
class FlowWire:
    """一条连线：src 输出 → dst 输入。

    v2 合法形态仅两类：发票模块 → 匹配模块；匹配模块 → 支付模块。
    """

    wire_id: str
    src_id: str
    dst_id: str


class FlowModel:
    """画布配置的真相源（内存态，每次打开对话框新建，不持久化）。"""

    def __init__(self) -> None:
        self.nodes: list[FlowNode] = []
        self.wires: list[FlowWire] = []
        self._seq: dict = {KIND_INVOICE: 0, KIND_PAYMENT: 0, KIND_MATCH: 0}

    # ── 节点 ──

    def add_node(self, kind: str, x: float, y: float) -> FlowNode:
        """新建节点（同类可多实例），默认命名带序号。"""
        self._seq[kind] = self._seq.get(kind, 0) + 1
        label = KIND_LABELS.get(kind, kind)
        node = FlowNode(
            node_id=_new_id("n"),
            kind=kind,
            name=f"{label} {self._seq[kind]}",
            x=x,
            y=y,
        )
        self.nodes.append(node)
        return node

    def get_node(self, node_id: str) -> Optional[FlowNode]:
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        return None

    def remove_node(self, node_id: str) -> list[str]:
        """删除节点并级联删除其连线，返回被删除的连线 id 列表。"""
        self.nodes = [n for n in self.nodes if n.node_id != node_id]
        removed = [w.wire_id for w in self.wires
                   if w.src_id == node_id or w.dst_id == node_id]
        self.wires = [w for w in self.wires
                      if w.src_id != node_id and w.dst_id != node_id]
        return removed

    def source_nodes_of(self, kind: Optional[str] = None) -> list[FlowNode]:
        """返回源模块节点（可指定发票/支付）。"""
        return [n for n in self.nodes
                if n.kind in KIND_SOURCES and (kind is None or n.kind == kind)]

    def match_nodes(self) -> list[FlowNode]:
        return [n for n in self.nodes if n.kind == KIND_MATCH]

    # ── 连线 ──

    def can_connect(self, src_id: str, dst_id: str) -> tuple[bool, str]:
        """校验连线合法性（v2 矩阵）。

        合法：发票模块.out → 匹配模块.in；匹配模块.out → 支付模块.in。
        其余一律非法并给中文原因。

        Returns:
            (True, "") 或 (False, 中文原因)
        """
        src = self.get_node(src_id)
        dst = self.get_node(dst_id)
        if src is None or dst is None:
            return False, "模块不存在"
        if src.node_id == dst.node_id:
            return False, "不能连接到模块自身"
        if any(w.src_id == src_id and w.dst_id == dst_id for w in self.wires):
            return False, "这两个模块已经连接，请先删除原连线"
        if src.kind == KIND_INVOICE:
            if dst.kind == KIND_MATCH:
                return True, ""
            return False, "发票模块输出只能连接到匹配模块输入"
        if src.kind == KIND_MATCH:
            if dst.kind == KIND_PAYMENT:
                return True, ""
            if dst.kind == KIND_MATCH:
                return False, "匹配模块之间无需连线"
            return False, "匹配模块输出只能连接到支付模块输入"
        if src.kind == KIND_PAYMENT:
            return False, "支付模块是链尾结果：只接收匹配模块输出，不能引出连线"
        return False, "无法建立该连线"

    def add_wire(self, src_id: str, dst_id: str) -> Optional[FlowWire]:
        ok, _reason = self.can_connect(src_id, dst_id)
        if not ok:
            return None
        wire = FlowWire(_new_id("w"), src_id, dst_id)
        self.wires.append(wire)
        return wire

    def remove_wire(self, wire_id: str) -> bool:
        before = len(self.wires)
        self.wires = [w for w in self.wires if w.wire_id != wire_id]
        return len(self.wires) < before

    def wires_of(self, node_id: str) -> list[FlowWire]:
        """节点所有关联连线（作为源或目标）。"""
        return [w for w in self.wires
                if w.src_id == node_id or w.dst_id == node_id]

    def wires_to(self, dst_id: str) -> list[FlowWire]:
        """以 dst 为入线目标的连线。"""
        return [w for w in self.wires if w.dst_id == dst_id]

    def wires_from(self, src_id: str) -> list[FlowWire]:
        """以 src 为出线源的连线。"""
        return [w for w in self.wires if w.src_id == src_id]

    def match_io(self, match_id: str) -> tuple[int, int, int]:
        """匹配模块接入统计：返回 (发票入线数, 支付出线数, 非法入线数)。

        非法入线 = 来源不是发票模块（v2 矩阵下不应出现，validate 防御）。
        """
        inv_in = 0
        pay_out = 0
        bad_in = 0
        for w in self.wires:
            if w.dst_id == match_id:
                src = self.get_node(w.src_id)
                if src is not None and src.kind == KIND_INVOICE:
                    inv_in += 1
                else:
                    bad_in += 1
            elif w.src_id == match_id:
                dst = self.get_node(w.dst_id)
                if dst is not None and dst.kind == KIND_PAYMENT:
                    pay_out += 1
        return inv_in, pay_out, bad_in

    # ── 校验与执行链 ──

    def chain_amount(self, match_id: str, store) -> Optional[float]:
        """匹配模块当前链金额：恰 1 条发票入线 + ≥1 条支付出线且发票侧已绑定时
        取发票侧（发票单元）绑定金额；否则返回 None（卡片显示「—」，不把 0 当真实金额）。

        一对多聚合链（1 发票单元 → N 支付支线）的链金额 = 发票单元金额。
        """
        if store is None:
            return None
        node = self.get_node(match_id)
        if node is None or node.kind != KIND_MATCH:
            return None
        ins = self.wires_to(match_id)
        outs = self.wires_from(match_id)
        if len(ins) != 1 or len(outs) < 1:
            return None
        src = self.get_node(ins[0].src_id)
        if src is None or src.kind != KIND_INVOICE or not src.is_bound(store):
            return None
        return src.bind_amount(store)

    def executable_chains(self) -> list[tuple[FlowNode, FlowNode, list[FlowNode]]]:
        """返回可执行链 [(匹配模块, 发票模块, [支付模块…])]。

        完整形态 = 匹配模块恰有 1 条发票入线 + ≥1 条支付出线、无非法入线，
        且出线目标全部为支付模块。一对多聚合链（1 发票单元 → N 支付支线）
        以单条链返回，支付模块列表为出线支付模块（≥1）；手动单链
        （1 支付）天然兼容（列表长度 1）。
        """
        chains: list[tuple[FlowNode, FlowNode, list[FlowNode]]] = []
        for m in self.match_nodes():
            inv_in, pay_out, bad_in = self.match_io(m.node_id)
            if inv_in != 1 or pay_out < 1 or bad_in:
                continue
            inv = None
            for w in self.wires_to(m.node_id):
                src = self.get_node(w.src_id)
                if src is not None and src.kind == KIND_INVOICE:
                    inv = src
                    break
            pays: list[FlowNode] = []
            valid = True
            for w in self.wires_from(m.node_id):
                dst = self.get_node(w.dst_id)
                if dst is None or dst.kind != KIND_PAYMENT:
                    valid = False
                    break
                pays.append(dst)
            if inv is not None and valid and pays:
                chains.append((m, inv, pays))
        return chains

    def validate(self, store) -> list[str]:
        """执行前配置校验（v2），返回中文问题列表（空 = 通过）。

        Args:
            store: 绑定解析所需的数据源（用于 canonical_file_ids / bind_amount）。
        """
        if not self.nodes:
            return ["画布为空：请先从左侧拖入模块，或确认存在金额匹配候选"]
        issues: list[str] = []
        matches = self.match_nodes()
        if not matches:
            issues.append(
                "缺少匹配模块：请拖入一个「匹配」模块，并分别接入发票与支付模块")

        # 1) 每个匹配模块的链形态
        for m in matches:
            inv_in, pay_out, bad_in = self.match_io(m.node_id)
            if bad_in:
                issues.append(
                    f"匹配模块「{m.name}」的输入来自支付模块，请改接发票模块")
            if inv_in == 0:
                issues.append(
                    f"匹配模块「{m.name}」缺少发票输入，请将发票模块输出连接到它")
            elif inv_in > 1:
                issues.append(
                    f"匹配模块「{m.name}」同时接入 {inv_in} 个发票模块，"
                    "一条链只对应一个发票模块")
            if pay_out == 0:
                issues.append(
                    f"匹配模块「{m.name}」缺少支付输出，请将输出连接到支付模块")
            # 支付出线 ≥1 合法：自动铺按发票单元聚合时 1 个匹配模块可接多个
            # 同额支付支线（1 发票单元 → N 支付）；手动单链（1 支付）同样兼容。
            for w in self.wires_from(m.node_id):
                dst = self.get_node(w.dst_id)
                if dst is not None and dst.kind != KIND_PAYMENT:
                    issues.append(
                        f"匹配模块「{m.name}」的输出只能连接到支付模块")
                    break

        # 2) 参与链的源模块必须已绑定（未接线模块惰性不查）
        for w in self.wires:
            src = self.get_node(w.src_id)
            dst = self.get_node(w.dst_id)
            if src is None or dst is None:
                continue
            if dst.kind == KIND_MATCH and src.kind == KIND_INVOICE \
                    and not src.is_bound(store):
                issues.append(f"发票模块「{src.name}」尚未绑定文件或组合")
            if src.kind == KIND_MATCH and dst.kind == KIND_PAYMENT \
                    and not dst.is_bound(store):
                issues.append(f"支付模块「{dst.name}」尚未绑定文件或组合")

        # 3) 同一 file_id 不得被两个不同源节点引用（跨模块绑定冲突兜底）
        reported: set[str] = set()
        for kind in KIND_SOURCES:
            bound = [n for n in self.nodes
                     if n.kind == kind and n.is_bound(store)]
            owner: dict[str, FlowNode] = {}
            for n in bound:
                for fid in n.canonical_file_ids(store):
                    if fid in owner and owner[fid].node_id != n.node_id \
                            and fid not in reported:
                        reported.add(fid)
                        issues.append(
                            f"文件「{self._file_display_name(store, kind, fid)}」"
                            "同时被两个模块绑定，请先移除其一")
                        continue
                    owner.setdefault(fid, n)
        return issues

    @staticmethod
    def _file_display_name(store, kind: str, file_id: str) -> str:
        """按 kind 取文件展示名（缺失时退回 file_id）。"""
        if kind == KIND_INVOICE:
            f = store.get_invoice(file_id)
        else:
            f = store.get_payment(file_id)
        if f is None:
            return file_id
        return getattr(f, "file_name", None) or file_id
