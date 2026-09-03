# -*- coding: utf-8 -*-
"""自动比对 · 流程画布对话框（v2 文件粒度 + 按发票单元聚合自动铺）。

布局：左侧「模块库」（中性白底，可拖入画布） + QGraphicsScene 画布 + 底部状态/按钮。
打开时：若存在金额匹配的未关联候选，按「发票单元」聚合自动铺——
同一发票单元与多个同额支付单元匹配时只建 1 个匹配模块（发票→匹配 1 条入线、
匹配→每个同额支付单元 1 条出线）；多发票单元 × 多支付单元 → 每发票单元各自
1 个匹配模块（发票单元是聚合键）。支付模块跨候选仍共享。
「确定并执行」：validate（缺项不关窗）→ 聚合链展开为 (匹配模块 × 支付模块)
支线，逐支线校验（发票单元金额 vs 该支付单元金额差 ≤ 链容差）→
store.batch_link(auto_linked=True) → result_summary（含 skipped/skip_reasons）。
store.py 引擎不参与重算（候选只在打开时铺一次，之后由用户编辑决定执行）。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QMimeData, QPoint, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QDrag, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QVBoxLayout,
)
from monkeyqt import MkButton, MkMessage

from app.ui.widgets.match_flow.canvas import FlowCanvas, MIME_NODE
from app.ui.widgets.match_flow.config_dialog import NodeConfigDialog
from app.ui.widgets.match_flow.items import NODE_H, NODE_W
from app.ui.widgets.match_flow.model import (
    FlowModel,
    KIND_INVOICE,
    KIND_LABELS,
    KIND_MATCH,
    KIND_PAYMENT,
)

_PALETTE_ITEMS = [
    (KIND_INVOICE, "电子发票", "绑定发票文件/组合"),
    (KIND_PAYMENT, "支付记录", "绑定支付记录文件/组合"),
    (KIND_MATCH, "匹配", "金额容差与链执行"),
]

_STATUS_GRAY = "#909399"
_STATUS_OK = "#409eff"
_STATUS_ERR = "#f56c6c"

# 自动铺三列布局常量
_X_INVOICE = 40.0
_X_MATCH = 40.0 + NODE_W + 150.0
_X_PAYMENT = 40.0 + 2 * (NODE_W + 150.0)
_V_STEP = NODE_H + 40.0
_Y0 = 40.0

_DIALOG_QSS = """
QDialog { background: #ffffff; font-family: "Segoe UI", "Microsoft YaHei"; }
QLabel { color: #606266; }
"""
_PALETTE_QSS = """
QListWidget {
    background: #fafbfc;
    border: 1px solid #e4e7ed;
    border-radius: 6px;
    font-size: 13px;
    outline: none;
}
"""

# 模块库卡片常量（MonkeyQt Elegant Light 浅色一致的圆角浅底卡片；
# 中性化：不用类型彩色做分类，仅用状态色区分 hover/选中）
_PALETTE_DESC_ROLE = Qt.ItemDataRole.UserRole + 1   # 行描述（类型说明小字）
_PALETTE_CARD_BG = "#f7f9fc"
_PALETTE_CARD_BORDER = "#e4e7ed"
_PALETTE_HOVER_BG = "#ecf5ff"
_PALETTE_HOVER_BORDER = "#c6e2ff"
_PALETTE_SEL_BG = "#d9ecff"
_PALETTE_SEL_BORDER = "#79bbff"
_PALETTE_TITLE = "#303133"
_PALETTE_DESC = "#909399"
_PALETTE_ICON = "#c0c4cc"


def _neutral_icon() -> QIcon:
    """模块库中性小图标（纯灰圆角方块，不用类型彩色）。"""
    pm = QPixmap(16, 16)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(_PALETTE_ICON))
    painter.drawRoundedRect(1, 1, 14, 14, 4, 4)
    painter.end()
    return QIcon(pm)


class _PaletteCardDelegate(QStyledItemDelegate):
    """模块库卡片代理：自绘「模块名 + 类型说明小字」两行圆角浅底卡片。

    QListWidgetItem 的文本只能单行绘制（换行会被归一化为 U+2028 且不折行），
    QSS ::item 无法承载两行结构，故卡片背景/边框/hover/选中反馈在此自绘；
    视觉采用 MonkeyQt Elegant Light 浅色风格（#f7f9fc / #e4e7ed / hover #ecf5ff）。
    _PaletteList 的 QDrag + mime 拖拽协议保持不变（text=模块名、UserRole=kind）。
    """

    _ROW_H = 56          # 行高（卡片 + 上下 margin）
    _MARGIN = 4          # 卡片与行边缘间距
    _RADIUS = 8          # 卡片圆角
    _ICON_S = 16

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(160, self._ROW_H)

    @staticmethod
    def _pick_colors(option: QStyleOptionViewItem) -> tuple[str, str]:
        """按状态取 (背景, 边框)：选中优先，其次 hover。"""
        state = option.state
        if state & QStyle.StateFlag.State_Selected:
            return _PALETTE_SEL_BG, _PALETTE_SEL_BORDER
        if state & QStyle.StateFlag.State_MouseOver:
            return _PALETTE_HOVER_BG, _PALETTE_HOVER_BORDER
        return _PALETTE_CARD_BG, _PALETTE_CARD_BORDER

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        card = option.rect.adjusted(self._MARGIN, self._MARGIN,
                                    -self._MARGIN, -self._MARGIN)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 卡片底 + 边框
        bg, border = self._pick_colors(option)
        painter.setPen(QPen(QColor(border), 1))
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(QRectF(card), self._RADIUS, self._RADIUS)
        # 中性图标
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon is not None and not icon.isNull():
            icon_rect = QRect(card.left() + 8, card.top() + 6,
                              self._ICON_S, self._ICON_S)
            icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter)
        # 两行文本：模块名（粗） + 类型说明（小字灰）
        title = str(index.data(Qt.ItemDataRole.DisplayRole)).strip()
        desc = str(index.data(_PALETTE_DESC_ROLE)).strip()
        text_x = card.left() + 8 + self._ICON_S + 8
        text_w = card.right() - text_x - 8
        if title:
            f_title = QFont(option.font)
            f_title.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"])
            f_title.setPixelSize(13)
            f_title.setWeight(QFont.Weight.DemiBold)
            painter.setFont(f_title)
            painter.setPen(QColor(_PALETTE_TITLE))
            t_rect = QRect(text_x, card.top() + 3, text_w, 20)
            elided = painter.fontMetrics().elidedText(
                title, Qt.TextElideMode.ElideRight, text_w)
            painter.drawText(t_rect,
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             elided)
        if desc:
            f_desc = QFont(option.font)
            f_desc.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"])
            f_desc.setPixelSize(11)
            painter.setFont(f_desc)
            painter.setPen(QColor(_PALETTE_DESC))
            d_rect = QRect(text_x, card.top() + 25, text_w, 18)
            elided = painter.fontMetrics().elidedText(
                desc, Qt.TextElideMode.ElideRight, text_w)
            painter.drawText(d_rect,
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             elided)
        painter.restore()


class _PaletteList(QListWidget):
    """模块库列表：中性卡片行 + 手动拖拽（QDrag + mime），拖入画布生成节点。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIconSize(QSize(16, 16))
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setMouseTracking(True)
        self.setStyleSheet(_PALETTE_QSS)
        self.setItemDelegate(_PaletteCardDelegate(self))
        self.setToolTip("按住并拖到右侧画布即可添加模块")
        self._press_item: Optional[QListWidgetItem] = None
        self._press_pos: Optional[QPoint] = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_item = self.itemAt(event.position().toPoint())
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._press_item is not None
                and event.buttons() & Qt.MouseButton.LeftButton
                and self._press_pos is not None
                and (event.position().toPoint() - self._press_pos).manhattanLength()
                >= QApplication.startDragDistance()):
            self._begin_drag(self._press_item)
            self._press_item = None
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_item = None
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def _begin_drag(self, item: QListWidgetItem):
        kind = item.data(Qt.ItemDataRole.UserRole)
        if not kind:
            return
        mime = QMimeData()
        mime.setData(MIME_NODE, kind.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        pm = QPixmap(150, 30)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#c0c4cc"))
        painter.drawRoundedRect(4, 8, 14, 14, 4, 4)
        painter.setPen(QColor("#303133"))
        painter.drawText(26, 12, 150, 18,
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         item.text())
        painter.end()
        drag.setPixmap(pm)
        drag.setHotSpot(QPoint(8, 15))
        drag.exec(Qt.DropAction.CopyAction)


class MatchFlowDialog(QDialog):
    """自动比对流程画布（模态二级界面，v2）。"""

    def __init__(self, store=None, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.result_summary: Optional[dict] = None
        self.model = FlowModel()
        self._status_text = ""

        self.setWindowTitle("自动比对 · 流程画布")
        self.setModal(True)
        self.resize(1580, 920)
        self.setMinimumSize(1280, 680)
        self.setStyleSheet(_DIALOG_QSS)
        self._build_ui()
        self._connect()
        self._populate_palette()
        if self.store is not None:
            self.canvas.flow_scene.set_store(self.store)
            self._auto_place()

    # ── UI ──

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("自动比对 · 流程画布")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #303133;")
        layout.addWidget(title)
        hint = QLabel("自动铺出金额匹配候选链；双击模块绑定文件/调整容差，点「确定并执行」完成批量关联")
        hint.setStyleSheet("font-size: 12px; color: #909399;")
        layout.addWidget(hint)

        # 主体：模块库 + 画布
        body = QHBoxLayout()
        body.setSpacing(10)
        body.addWidget(self._build_palette(), stretch=0)
        self.canvas = FlowCanvas(self.model)
        body.addWidget(self.canvas, stretch=1)
        layout.addLayout(body, stretch=1)

        # 底部状态 + 按钮
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color: {_STATUS_GRAY}; font-size: 12px;")
        bottom.addWidget(self.lbl_status, stretch=1)
        self.btn_cancel = MkButton("取消", type="default")
        self.btn_cancel.setAutoDefault(False)
        self.btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(self.btn_cancel)
        self.btn_ok = MkButton("确定并执行", type="primary")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._on_confirm)
        bottom.addWidget(self.btn_ok)
        layout.addLayout(bottom)

    def _build_palette(self) -> QFrame:
        panel = QFrame()
        panel.setFixedWidth(190)
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        label = QLabel("模块库")
        label.setStyleSheet("font-size: 13px; font-weight: 600; color: #303133;")
        v.addWidget(label)
        self.palette = _PaletteList()
        v.addWidget(self.palette, stretch=1)
        tip = QLabel("拖到右侧画布\n同类模块可添加多个")
        tip.setStyleSheet("color: #c0c4cc; font-size: 12px;")
        v.addWidget(tip)
        return panel

    def _populate_palette(self):
        icon = _neutral_icon()
        for kind, name, desc in _PALETTE_ITEMS:
            item = QListWidgetItem(icon, name)
            item.setData(Qt.ItemDataRole.UserRole, kind)
            item.setData(_PALETTE_DESC_ROLE, desc)
            item.setToolTip(desc)
            self.palette.addItem(item)

    def _connect(self):
        self.canvas.on_config_requested = self._open_config
        self.canvas.on_status = self._show_status
        self.canvas.on_module_added = self._on_module_added

    # ── 自动铺候选链 ──

    def _auto_place(self):
        """打开时自动铺候选链：store.get_amount_matches() 原样调用，不重算引擎。"""
        if self.store is None:
            return
        try:
            matches = self.store.get_amount_matches()
        except Exception:
            matches = []
            self._show_status(
                "读取金额匹配候选失败（数据异常）：可取消后重试或从左侧拖入模块手动搭建",
                False)
            return
        if not matches:
            self._show_status(
                "未找到金额匹配的未关联配对（无金额或已全部关联）：可从左侧拖入模块手动搭建",
                False)
            return
        chains = self._build_candidate_chains(matches)
        self._layout_chains(chains)
        self.canvas.flow_scene.refresh_all()
        self.canvas.scroll_home()
        branch_count = sum(len(pays) for _inv, _m, pays, _amt in chains)
        self._show_status(
            f"已自动铺出 {len(chains)} 组匹配链（{branch_count} 条支付支线）："
            "双击模块可调整绑定或容差，删除/重建后点确定执行",
            True)

    def _build_candidate_chains(self, matches: list[dict]) -> list[tuple]:
        """候选对 → 按发票单元聚合的链 [(发票, 匹配, [支付…], 金额)]。

        同一发票单元与多个同额支付单元匹配时聚合为 1 个匹配模块（支付出线
        多条）；多发票单元 × 多支付单元（多对多）→ 每个发票单元各自 1 个
        匹配模块（发票单元是聚合键）。支付模块跨候选仍共享（只建 1 个节点）。
        """
        inv_nodes: dict[tuple, object] = {}
        pay_nodes: dict[tuple, object] = {}
        inv_meta: dict[tuple, dict] = {}
        group_pays: dict[tuple, list] = {}
        for m in matches:
            inv_key = tuple(sorted(m["invoice_ids"]))
            pay_key = tuple(sorted(m["payment_ids"]))
            inv = inv_nodes.get(inv_key)
            if inv is None:
                inv = self._make_source_node(
                    KIND_INVOICE, inv_key, m.get("invoice_name", ""),
                    bool(m.get("is_combo_invoice")))
                inv_nodes[inv_key] = inv
                inv_meta[inv_key] = m
            pay = pay_nodes.get(pay_key)
            if pay is None:
                pay = self._make_source_node(
                    KIND_PAYMENT, pay_key, m.get("payment_name", ""),
                    bool(m.get("is_combo_payment")))
                pay_nodes[pay_key] = pay
            pays = group_pays.setdefault(inv_key, [])
            if pay not in pays:
                pays.append(pay)
        chains: list[tuple] = []
        for inv_key, inv in inv_nodes.items():
            m0 = inv_meta[inv_key]
            amount = float(m0.get("amount", 0.0))
            match_node = self._make_match_node(amount)
            chains.append((inv, match_node, list(group_pays[inv_key]), amount))
        # 布局稳定序：按金额再按发票名（等价旧布局的金额分簇顺序）
        chains.sort(key=lambda c: (round(c[3], 2), c[0].name))
        return chains

    def _make_source_node(self, kind: str, unit_ids, display_name: str,
                          is_combo: bool):
        """建源模块节点并预绑定：单文件 → file_ids；组合 → combo_ids（反查失败退化单文件）。"""
        node = self.model.add_node(kind, 0.0, 0.0)
        if is_combo:
            cid = self._find_combo_id(kind, unit_ids)
            if cid is not None:
                node.combo_ids = [cid]
            else:
                node.file_ids = list(unit_ids)
        else:
            node.file_ids = list(unit_ids)
        node.name = display_name or KIND_LABELS.get(kind, kind)
        return node

    def _find_combo_id(self, kind: str, unit_ids) -> Optional[str]:
        """反查与单元成员完全一致的组合 combo_id（多组合同成员时取首个）。"""
        if self.store is None:
            return None
        target = sorted(unit_ids)
        for c in self.store.get_combos(kind):
            # 只接受有效组合（≥1 个非 missing 成员）：空壳组合不参与反查
            if not self.store.combo_has_active_members(c["combo_id"]):
                continue
            if sorted(c.get("file_ids", [])) == target:
                return c["combo_id"]
        return None

    def _make_match_node(self, amount: float):
        node = self.model.add_node(KIND_MATCH, 0.0, 0.0)
        node.name = f"匹配 ¥{amount:,.2f}"
        return node

    def _layout_chains(self, chains: list[tuple]):
        """按发票单元聚合布局：发票/匹配列每单元一行对齐，支付列唯一节点逐行。

        支付模块跨候选共享 → 每个支付节点只放置一次（按首见顺序分配行号），
        避免旧布局对共享节点重复加入场景。列坐标相互独立：
        1 发票单元 + N 支付（同额）→ 发票/匹配居首行、N 条支付支线逐行下排；
        多发票单元 × 多支付（多对多）→ 每发票单元一行匹配、支付共享节点交叉连线。
        """
        x_of = {KIND_INVOICE: _X_INVOICE, KIND_MATCH: _X_MATCH,
                KIND_PAYMENT: _X_PAYMENT}
        scene = self.canvas.flow_scene
        pay_order: list = []
        pay_rows: dict = {}
        for _inv, _m, pays, _amount in chains:
            for p in pays:
                if p.node_id not in pay_rows:
                    pay_rows[p.node_id] = len(pay_order)
                    pay_order.append(p)
        for row, (inv, match_node, _pays, _amount) in enumerate(chains):
            y = _Y0 + row * _V_STEP
            scene.add_prebuilt_node(inv, x_of[KIND_INVOICE], y)
            scene.add_prebuilt_node(match_node, x_of[KIND_MATCH], y)
        for row, pay in enumerate(pay_order):
            scene.add_prebuilt_node(pay, x_of[KIND_PAYMENT], _Y0 + row * _V_STEP)
        # 位置就绪后建线（发票 → 匹配 → 每个支付支线）
        for inv, match_node, pays, _amount in chains:
            scene.create_wire(inv.node_id, match_node.node_id)
            for p in pays:
                scene.create_wire(match_node.node_id, p.node_id)

    # ── 交互回调 ──

    def _on_module_added(self, node):
        self._show_status(
            f"已添加模块「{node.name}」：双击绑定文件/组合或配置参数", True)

    def _open_config(self, node_id: str):
        node = self.model.get_node(node_id)
        if node is None:
            return
        summary = ""
        usage: dict = {}
        if node.kind == KIND_MATCH:
            inv_in, pay_out, _bad = self.model.match_io(node_id)
            summary = f"当前接入：发票 {inv_in} 路 → 匹配 → 支付 {pay_out} 路"
            amount = self._match_chain_amount(node_id)
            if amount is not None:
                summary += f"；当前链金额 ¥{amount:,.2f}"
        else:
            usage = self._binding_usage(exclude_node_id=node_id)
        dlg = NodeConfigDialog(node, self.store, parent=self,
                               match_summary=summary, usage=usage)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.canvas.flow_scene.refresh_all()
            self._show_status(f"「{node.name}」配置已更新", True)

    def _binding_usage(self, exclude_node_id: str) -> dict:
        """其它源模块已绑定成员的 file_id → 占有模块描述（供配置弹窗禁用）。"""
        usage: dict = {}
        if self.store is None:
            return usage
        for n in self.model.nodes:
            if not n.is_source or n.node_id == exclude_node_id:
                continue
            if not n.is_bound(self.store):
                continue
            owner = f"{KIND_LABELS.get(n.kind, n.kind)}「{n.name}」"
            for fid in n.canonical_file_ids(self.store):
                usage[fid] = owner
        return usage

    def _match_chain_amount(self, match_id: str) -> Optional[float]:
        """匹配模块当前链金额（统一走 model.chain_amount）。"""
        if self.store is None:
            return None
        return self.model.chain_amount(match_id, self.store)

    def _show_status(self, msg: str, ok: bool):
        self._status_text = msg
        color = _STATUS_OK if ok else _STATUS_ERR
        self.lbl_status.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: 600;")
        self.lbl_status.setText(msg)
        QTimer.singleShot(4000, self._clear_status)

    def _clear_status(self):
        if self.lbl_status.text() == self._status_text:
            self.lbl_status.setText("")

    # ── 确定执行（v2 管线：锁定模型，不重算引擎）──

    def _on_confirm(self):
        """校验 → 逐支线容差判定 → batch_link(auto_linked=True) → result_summary。

        一对多聚合链展开为 (匹配模块 × 支付模块) 支线：每个支线独立做
        发票单元金额 vs 该支付单元金额的容差判定，跳过原因逐支线记录。
        """
        if self.store is None:
            MkMessage.warning(self, "数据未初始化")
            return
        issues = self.model.validate(self.store)
        if issues:
            self._show_status("校验未通过：" + issues[0], False)
            MkMessage.warning(self, "配置不完整：\n\n" + "\n".join(issues))
            return
        chains = self.model.executable_chains()
        if not chains:
            self._show_status("没有可执行链", False)
            MkMessage.warning(
                self, "没有可执行链：请先连接出「发票 → 匹配 → 支付」的完整链")
            return
        # 展开支线：每条 (匹配模块, 发票模块, 支付模块) 独立容差校验
        branches: list[tuple] = [
            (m, inv, pay) for m, inv, pays in chains for pay in pays
        ]

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok_pairs: list[dict] = []
            skipped: list[str] = []
            for m, inv, pay in branches:
                inv_ids = inv.canonical_file_ids(self.store)
                pay_ids = pay.canonical_file_ids(self.store)
                if not inv_ids or not pay_ids:
                    skipped.append(
                        f"「{m.name}」→「{pay.name}」：源模块未绑定文件或组合")
                    continue
                if not inv.has_amount(self.store) or not pay.has_amount(self.store):
                    skipped.append(
                        f"「{m.name}」→「{pay.name}」：一侧绑定文件缺少金额"
                        "（未识别/无金额），无法按金额比对")
                    continue
                inv_amt = inv.bind_amount(self.store)
                pay_amt = pay.bind_amount(self.store)
                tol = float(m.params.get("tolerance", 0.01))
                if abs(inv_amt - pay_amt) <= tol + 1e-9:
                    ok_pairs.append(
                        {"invoice_ids": inv_ids, "payment_ids": pay_ids})
                else:
                    skipped.append(
                        f"「{m.name}」→「{pay.name}」金额差超出容差：¥{inv_amt:,.2f} "
                        f"vs ¥{pay_amt:,.2f}（±{tol:g}）")
            count = self.store.batch_link(ok_pairs, auto_linked=True) \
                if ok_pairs else 0
        finally:
            QApplication.restoreOverrideCursor()

        self.result_summary = {
            "count": count,
            "total": len(branches),
            "found": bool(chains),
            "skipped": len(skipped),
            "skip_reasons": skipped[:20],
        }
        self.accept()
