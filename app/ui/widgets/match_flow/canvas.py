# -*- coding: utf-8 -*-
"""流程画布：QGraphicsScene 场景 + QGraphicsView 视图。

职责：
    - FlowScene：节点/连线/临时线的生命周期与 linking 状态机、命中与删除、右键菜单、
      store 注入与派生显示刷新（绑定摘要 / 匹配接入 / 金额）
    - FlowCanvas：空白平移、Ctrl+滚轮缩放、侧边栏拖放接收、删除键、空态引导浮层

v2 保留基建：viewportEvent 源头截获拖放、级联删除、平移缩放、空态引导卡片。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QMenu,
)

from .items import (
    FlowNodeItem,
    FlowWireItem,
    NODE_H,
    NODE_W,
)
from .model import (
    FlowModel,
    KIND_INVOICE,
    KIND_MATCH,
    KIND_PAYMENT,
)

# 侧边栏拖放 mime 类型（data 存模块 kind）
MIME_NODE = "application/x-recity-node"

_GRID_COLOR = QColor("#e3e7ee")
_BG_COLOR = QColor("#f5f7fa")

# 空态引导卡片：最大宽度与 rich text 内容（v2 语义，模块说明中性描述）
_GUIDE_MAX_W = 380
_GUIDE_HTML = (
    "<html><body style='color:#303133;'>"
    "<p style='margin:0 0 8px 0; text-align:center; font-size:15px; font-weight:700;'>"
    "从左侧拖入模块开始配置</p>"
    "<p style='margin:0 0 6px 0; font-size:13px;'>"
    "<span style='color:#909399;'>▣</span> <b>电子发票</b>"
    "<span style='font-size:12px; color:#909399;'> 绑定发票文件/组合</span></p>"
    "<p style='margin:0 0 6px 0; font-size:13px;'>"
    "<span style='color:#909399;'>▣</span> <b>支付记录</b>"
    "<span style='font-size:12px; color:#909399;'> 绑定支付记录文件/组合</span></p>"
    "<p style='margin:0 0 6px 0; font-size:13px;'>"
    "<span style='color:#909399;'>▣</span> <b>匹配</b>"
    "<span style='font-size:12px; color:#909399;'> 金额容差与链执行</span></p>"
    "<p style='margin:0 0 6px 0; font-size:12px; color:#909399;'>"
    "若存在金额匹配的未关联配对，本画布会自动铺成"
    "「发票 → 匹配 → 支付」候选链，可直接调整后执行</p>"
    "<p style='margin:0; font-size:12px; color:#909399;'>"
    "手动搭建：发票/匹配/支付各拖一个，发票输出连匹配输入，"
    "匹配输出连支付输入，双击模块绑定文件或调整容差</p>"
    "</body></html>"
)


class FlowScene(QGraphicsScene):
    """画布场景：管理图形项与交互状态机。"""

    nodeConfigRequested = Signal(str)      # 双击节点请求配置
    statusMessage = Signal(str, bool)      # (消息, 是否成功提示)
    nodesChanged = Signal()                # 节点增删（用于空态引导/画布变更）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model: Optional[FlowModel] = None
        self._canvas: Optional["FlowCanvas"] = None
        self._store = None                 # 绑定解析数据源（MatchFlowDialog 注入）
        self._node_items: dict = {}
        self._wire_items: dict = {}
        # linking 状态
        self._linking = False
        self._link_src_id: Optional[str] = None
        self._temp_wire: Optional[FlowWireItem] = None
        self._hover_target_id: Optional[str] = None
        self._selected_wire_id: Optional[str] = None
        self._scene_rect_set = False   # 场景矩形是否已显式设置（_expand 首次留白判定）

    # ── 绑定 ──

    def attach(self, model: FlowModel, canvas: "FlowCanvas"):
        self._model = model
        self._canvas = canvas

    def set_store(self, store):
        """注入 store：已存在的源模块图形项刷新绑定摘要，之后新建项可解析显示。"""
        self._store = store
        for item in self._node_items.values():
            item.set_store(store)
            if item.node.kind == KIND_MATCH:
                self.refresh_match_summary(item.node.node_id)

    @property
    def model(self) -> FlowModel:
        assert self._model is not None
        return self._model

    def node_count(self) -> int:
        return len(self.model.nodes)

    # ── 节点 ──

    def add_node_item(self, kind: str, x: float, y: float):
        """在场景添加一个节点图形项（model 同步新建），返回 FlowNode。"""
        node = self.model.add_node(kind, x, y)
        return self._add_node_graphics(node, x, y)

    def add_prebuilt_node(self, node, x: float, y: float):
        """添加一个已由 model 建好（含绑定/命名）的节点图形项（自动铺用）。"""
        return self._add_node_graphics(node, x, y)

    def _add_node_graphics(self, node, x: float, y: float):
        node.x = x
        node.y = y
        item = FlowNodeItem(node, store=self._store)
        item.setPos(x, y)
        self.addItem(item)
        self._node_items[node.node_id] = item
        if node.kind == KIND_MATCH:
            self.refresh_match_summary(node.node_id)
        self._expand_scene_rect(item)
        self.nodesChanged.emit()
        return node

    def node_item(self, node_id: str) -> Optional[FlowNodeItem]:
        return self._node_items.get(node_id)

    def wire_item(self, wire_id: str) -> Optional[FlowWireItem]:
        return self._wire_items.get(wire_id)

    def remove_node_item(self, node_id: str):
        item = self._node_items.pop(node_id, None)
        if item is not None:
            self.removeItem(item)

    def _expand_scene_rect(self, item):
        """把 item 纳入场景矩形：margin 只在首次加一次，之后仅并集。

        修复前每加一个节点就对整个场景矩形 adjusted(-120,-120,…)，left/top 逐节点
        负向漂移，节点被甩到视口外。Qt 未显式设置时会自动按 item 计算 sceneRect
        （width>0），无法用空矩形判定“首次”，故用内部标志保证只留白一次。
        """
        item_r = item.boundingRect().translated(item.pos())
        if not self._scene_rect_set:
            # 仅首次：以首节点为中心外扩留白
            self.setSceneRect(item_r.adjusted(-120.0, -120.0, 120.0, 120.0))
            self._scene_rect_set = True
            return
        self.setSceneRect(self.sceneRect().united(item_r))

    # ── 连线 linking 状态机 ──

    def is_linking(self) -> bool:
        return self._linking

    def begin_link(self, src_id: str):
        """从输出端口开始拖线（由 FlowNodeItem 按下调用）。"""
        if self._linking:
            self.cancel_link()
        src_item = self.node_item(src_id)
        if src_item is None:
            return
        self._linking = True
        self._link_src_id = src_id
        src_item._link_source = True
        self._temp_wire = FlowWireItem(temp=True)
        self.addItem(self._temp_wire)
        self._temp_wire.set_endpoints(src_item.out_port_pos(), src_item.out_port_pos())
        src_item.update()
        if self._canvas is not None:
            self._canvas.setFocus()

    @staticmethod
    def _is_valid_link_target(src_kind: str, dst_kind: str) -> bool:
        """v2 连线矩阵：invoice.out→match.in；match.out→payment.in。"""
        if src_kind == KIND_INVOICE:
            return dst_kind == KIND_MATCH
        if src_kind == KIND_MATCH:
            return dst_kind == KIND_PAYMENT
        return False

    def update_temp(self, scene_pos: QPointF):
        """拖线移动：更新临时线终点与合法目标高亮。"""
        if not self._linking or self._temp_wire is None:
            return
        src_item = self.node_item(self._link_src_id or "")
        src = self.model.get_node(self._link_src_id or "") if self._link_src_id else None
        if src_item is None or src is None:
            return
        self._temp_wire.set_endpoints(src_item.out_port_pos(), scene_pos)
        target = self._top_node_at(scene_pos)
        valid = target is not None and self._is_valid_link_target(
            src.kind, target.node.kind)
        self._temp_wire.set_invalid(not valid)
        self._set_hover_target(target if valid else None)

    def finish_link(self, scene_pos: QPointF):
        """松开鼠标：命中合法目标则建线，否则取消并给出原因。"""
        if not self._linking:
            return
        src_id = self._link_src_id or ""
        target = self._top_node_at(scene_pos)
        if target is not None:
            wire = self.create_wire(src_id, target.node.node_id)
            if wire is not None:
                self._status(
                    f"已连接：{self._node_name(src_id)} → {self._node_name(wire.dst_id)}",
                    True,
                )
            else:
                _can, reason = self.model.can_connect(
                    src_id, target.node.node_id)
                self._status(reason or "无法建立连线", False)
        self._cleanup_link()

    def cancel_link(self):
        """取消进行中的连线（Esc/右键/失焦/删除源节点时调用）。"""
        if self._linking:
            self._cleanup_link()

    def _cleanup_link(self):
        src_id = self._link_src_id
        if src_id is not None:
            src_item = self.node_item(src_id)
            if src_item is not None:
                src_item._link_source = False
                src_item.update()
        if self._temp_wire is not None:
            self.removeItem(self._temp_wire)
            self._temp_wire = None
        self._set_hover_target(None)
        self._linking = False
        self._link_src_id = None

    def _set_hover_target(self, item: Optional[FlowNodeItem]):
        if self._hover_target_id is not None:
            old = self.node_item(self._hover_target_id)
            if old is not None:
                old._link_target = False
                old.update()
        self._hover_target_id = item.node.node_id if item is not None else None
        if item is not None:
            item._link_target = True
            item.update()

    def _top_node_at(self, scene_pos: QPointF) -> Optional[FlowNodeItem]:
        for it in self.items(scene_pos):
            if isinstance(it, FlowNodeItem):
                return it
        return None

    # ── 连线增删 ──

    def create_wire(self, src_id: str, dst_id: str):
        """建一条正式连线（model 校验 v2 矩阵），成功返回 FlowWire。"""
        wire = self.model.add_wire(src_id, dst_id)
        if wire is None:
            return None
        self._add_wire_item(wire)
        self._refresh_affected_matches(wire)
        return wire

    def _add_wire_item(self, wire):
        src_item = self.node_item(wire.src_id)
        dst_item = self.node_item(wire.dst_id)
        if src_item is None or dst_item is None:
            return
        item = FlowWireItem(wire=wire)
        item.set_endpoints(src_item.out_port_pos(), dst_item.in_port_pos())
        self.addItem(item)
        self._wire_items[wire.wire_id] = item

    def _refresh_affected_matches(self, wire):
        """连线增删后刷新涉及的匹配模块（发票侧 dst 或匹配侧 src）。"""
        for nid in (wire.src_id, wire.dst_id):
            node = self.model.get_node(nid)
            if node is not None and node.kind == KIND_MATCH:
                self.refresh_match_summary(nid)

    def delete_wire(self, wire_id: str, silent: bool = False):
        wire = next((w for w in self.model.wires if w.wire_id == wire_id), None)
        if wire is None:
            return
        self.model.remove_wire(wire_id)
        item = self._wire_items.pop(wire_id, None)
        if item is not None:
            self.removeItem(item)
        if self._selected_wire_id == wire_id:
            self._selected_wire_id = None
        self._refresh_affected_matches(wire)
        if not silent:
            self._status("已删除连线", True)

    def select_wire(self, item: FlowWireItem):
        if self._selected_wire_id is not None and self._selected_wire_id != (
                item.wire.wire_id if item.wire else None):
            old = self.wire_item(self._selected_wire_id)
            if old is not None:
                old.set_selected(False)
        self._selected_wire_id = item.wire.wire_id if item.wire else None
        item.set_selected(True)
        if self._canvas is not None:
            self._canvas.setFocus()

    def clear_wire_selection(self):
        if self._selected_wire_id is not None:
            old = self.wire_item(self._selected_wire_id)
            if old is not None:
                old.set_selected(False)
            self._selected_wire_id = None

    # ── 删除（节点级联）──

    def delete_node(self, node_id: str):
        if self._linking and self._link_src_id == node_id:
            self.cancel_link()
        wires = [w for w in self.model.wires
                 if w.src_id == node_id or w.dst_id == node_id]
        affected = sorted({
            nid for w in wires for nid in (w.src_id, w.dst_id)
            if (lambda n: n is not None and n.kind == KIND_MATCH)(
                self.model.get_node(nid))
        })
        self.model.remove_node(node_id)
        self.remove_node_item(node_id)
        for w in wires:
            item = self._wire_items.pop(w.wire_id, None)
            if item is not None:
                self.removeItem(item)
        if self._selected_wire_id is not None \
                and self.wire_item(self._selected_wire_id) is None:
            self._selected_wire_id = None
        for m_id in affected:
            self.refresh_match_summary(m_id)
        self.nodesChanged.emit()
        self._status(f"已删除模块：{self._node_name(node_id)}", True)

    def delete_selected(self):
        """Delete 键：删除选中的连线或节点。"""
        if (self._selected_wire_id is not None
                and self.wire_item(self._selected_wire_id) is not None):
            self.delete_wire(self._selected_wire_id)
            return
        node_ids = [it.node.node_id for it in self.selectedItems()
                    if isinstance(it, FlowNodeItem)]
        for nid in list(node_ids):
            self.delete_node(nid)

    # ── 刷新与菜单 ──

    def refresh_match_summary(self, match_id: str):
        """连线/绑定变化后刷新匹配模块的接入统计与链金额。"""
        item = self.node_item(match_id)
        if item is None:
            return
        inv_in, pay_out, _bad = self.model.match_io(match_id)
        item.set_match_summary(inv_in, pay_out)
        item.set_match_amount(self.model.chain_amount(match_id, self._store))

    def refresh_all(self):
        """配置/绑定变更后刷新所有节点显示。"""
        for n in self.model.nodes:
            item = self.node_item(n.node_id)
            if item is None:
                continue
            item.refresh_content()
            if n.kind == KIND_MATCH:
                self.refresh_match_summary(n.node_id)

    def sync_wires_for_node(self, node_id: str):
        """节点移动后更新其关联连线几何（由 itemChange 调用，勿 setPos）。"""
        for w in self.model.wires_of(node_id):
            item = self.wire_item(w.wire_id)
            if item is None:
                continue
            src_item = self.node_item(w.src_id)
            dst_item = self.node_item(w.dst_id)
            if src_item is not None and dst_item is not None:
                item.set_endpoints(src_item.out_port_pos(), dst_item.in_port_pos())
        # 节点移出场景后仍可达：随移动扩张场景矩形
        moved = self.node_item(node_id)
        if moved is not None:
            self._expand_scene_rect(moved)

    def request_config(self, node_id: str):
        self.nodeConfigRequested.emit(node_id)

    def request_node_menu(self, node_id: str, screen_pos):
        menu = QMenu()
        act_config = menu.addAction("配置…")
        menu.addSeparator()
        act_delete = menu.addAction("删除模块")
        picked = menu.exec(screen_pos)
        if picked is act_config:
            self.nodeConfigRequested.emit(node_id)
        elif picked is act_delete:
            self.delete_node(node_id)

    def request_wire_menu(self, wire_id: str, screen_pos):
        menu = QMenu()
        act_delete = menu.addAction("删除连线")
        picked = menu.exec(screen_pos)
        if picked is act_delete:
            self.delete_wire(wire_id)

    # ── 工具 ──

    def _node_name(self, node_id: str) -> str:
        node = self.model.get_node(node_id)
        return node.name if node is not None else "未知模块"

    def _status(self, msg: str, ok: bool):
        self.statusMessage.emit(msg, ok)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if self._canvas is not None:
            self._canvas.setFocus()
        # 点击节点时清掉连线选中，避免 Delete 误删连线
        if self._top_node_at(event.scenePos()) is not None:
            self.clear_wire_selection()

    def contextMenuEvent(self, event):
        # 连线拖拽中右键 → 取消连线（吞掉事件，避免临时线菜单/卡死）
        if self._linking:
            self.cancel_link()
            event.accept()
            return
        super().contextMenuEvent(event)

    def drawBackground(self, painter: QPainter, rect):
        """浅底 + 点阵网格（Node-RED 质感但保持轻盈）。"""
        painter.fillRect(rect, _BG_COLOR)
        painter.setPen(QPen(_GRID_COLOR, 1))
        left = int(rect.left()) - (int(rect.left()) % 24)
        top = int(rect.top()) - (int(rect.top()) % 24)
        x = left
        while x < rect.right():
            y = top
            while y < rect.bottom():
                painter.drawPoint(x, y)
                y += 24
            x += 24


class FlowCanvas(QGraphicsView):
    """画布视图：空白平移 + Ctrl 滚轮缩放 + 拖放接收 + 删除键 + 空态引导。"""

    _MIN_ZOOM = 0.4
    _MAX_ZOOM = 2.5

    def __init__(self, model: FlowModel, parent=None):
        super().__init__(parent)
        self._scene = FlowScene(self)
        self.setScene(self._scene)
        self._scene.attach(model, self)
        self._scene.nodeConfigRequested.connect(self._on_config_requested)
        self._scene.nodesChanged.connect(self.update_guide)

        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # 平台拖放事件投递给 viewport（QAbstractScrollArea 的子控件）；同时 view 需 acceptDrops
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self._dnd_active = False      # 正在接收模块拖放（DragLeave/去重判断）
        self.setMouseTracking(True)
        self.setStyleSheet("""
            QGraphicsView {
                background: #f5f7fa;
                border: 1px solid #e4e7ed;
                border-radius: 6px;
            }
        """)

        self.on_config_requested = None      # dialog 注入：fn(node_id)
        self.on_status = None                # dialog 注入：fn(msg, ok)
        self.on_module_added = None          # dialog 注入：fn(node)

        self._panning = False
        self._pan_last = None
        self._zoom = 1.0

        # 空态引导浮层（居中卡片式 rich text，不拦截鼠标）
        self._guide = QLabel(self)
        self._guide.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._guide.setTextFormat(Qt.TextFormat.RichText)
        self._guide.setText(_GUIDE_HTML)
        self._guide.setWordWrap(True)
        self._guide.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._guide.setStyleSheet("""
            QLabel {
                background: #ffffff;
                border: 1px solid #e4e7ed;
                border-radius: 8px;
                padding: 14px 18px;
                font-family: "Microsoft YaHei", "Segoe UI";
            }
        """)
        self._guide.hide()
        self.update_guide()

        self._scene.statusMessage.connect(self._forward_status)

    def _forward_status(self, msg: str, ok: bool):
        if self.on_status is not None:
            self.on_status(msg, ok)

    def _on_config_requested(self, node_id: str):
        if self.on_config_requested is not None:
            self.on_config_requested(node_id)

    @property
    def flow_scene(self) -> FlowScene:
        return self._scene

    # ── 对外 API（供 MatchFlowDialog 使用）──

    def add_module(self, kind: str, view_pos) -> FlowNode:
        """从侧边栏落点添加模块（落点居中）。"""
        # QDropEvent.position() 返回 QPointF；PySide6 mapToScene 无 QPointF 重载，先归一化为 QPoint
        if isinstance(view_pos, QPointF):
            view_pos = view_pos.toPoint()
        scene_pos = self.mapToScene(view_pos)
        x = scene_pos.x() - NODE_W / 2.0
        y = scene_pos.y() - NODE_H / 2.0
        node = self._scene.add_node_item(kind, x, y)
        if self.on_module_added is not None:
            self.on_module_added(node)
        self.setFocus()
        return node

    def scroll_home(self):
        """自动铺后滚动回左上角（内容从 (0,0) 起始）。"""
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().minimum())
        self.verticalScrollBar().setValue(self.verticalScrollBar().minimum())

    def _layout_guide(self):
        """按画布尺寸居中摆放引导卡片：宽约 60%（上限 _GUIDE_MAX_W），高自适应内容。"""
        card_w = min(int(self.width() * 0.6), _GUIDE_MAX_W)
        if card_w <= 0:
            return
        self._guide.setFixedWidth(card_w)
        self._guide.setFixedHeight(self._guide.heightForWidth(card_w))
        x = (self.width() - card_w) // 2
        y = max(0, (self.height() - self._guide.height()) // 2)
        self._guide.move(x, y)

    def update_guide(self):
        if self._scene is None:
            return
        if self._scene.node_count() == 0:
            self._layout_guide()
            self._guide.show()
        else:
            self._guide.hide()

    # ── 视图事件：平移 / 缩放 / 键盘 / 拖放 ──

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton \
                and self.itemAt(event.position().toPoint()) is None \
                and not self._scene.is_linking():
            self._panning = True
            self._pan_last = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._scene.clear_wire_selection()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_last is not None:
            delta = event.position() - self._pan_last
            self._pan_last = event.position()
            hbar = self.horizontalScrollBar()
            vbar = self.verticalScrollBar()
            hbar.setValue(hbar.value() - int(delta.x()))
            vbar.setValue(vbar.value() - int(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning:
            self._panning = False
            self._pan_last = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            angle = event.angleDelta().y()
            factor = 1.15 if angle > 0 else 1 / 1.15
            new_zoom = self._zoom * factor
            new_zoom = max(self._MIN_ZOOM, min(self._MAX_ZOOM, new_zoom))
            factor = new_zoom / self._zoom
            self.scale(factor, factor)
            self._zoom = new_zoom
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._scene.delete_selected()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            if self._scene.is_linking():
                self._scene.cancel_link()
                event.accept()
                return
            super().keyPressEvent(event)
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        # 失焦清 linking 态，防悬空临时线
        self._scene.cancel_link()
        super().focusOutEvent(event)

    # ── 拖放接收：viewportEvent 源头截获（所有投递到 viewport 的 drag/drop 必经）──

    def _accept_node_drag(self, event) -> bool:
        """模块 mime 命中则接受 enter/move/drop 事件；Drop 时落点生成节点。"""
        if not event.mimeData().hasFormat(MIME_NODE):
            return False
        kind = bytes(event.mimeData().data(MIME_NODE)).decode("utf-8")
        if kind not in (KIND_INVOICE, KIND_PAYMENT, KIND_MATCH):
            return False
        if event.type() == QEvent.Type.Drop:
            self.add_module(kind, event.position())
            self._dnd_active = False
        elif event.type() == QEvent.Type.DragEnter:
            self._dnd_active = True
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        return True

    def viewportEvent(self, event) -> bool:
        """源头截获：模块拖放不落入 QGraphicsView 的 scene 转译路径。"""
        etype = event.type()
        if etype in (QEvent.Type.DragEnter, QEvent.Type.DragMove,
                     QEvent.Type.Drop, QEvent.Type.DragLeave):
            if etype == QEvent.Type.DragLeave:
                if self._dnd_active:
                    self._dnd_active = False
                    event.accept()
                    return True
                return super().viewportEvent(event)
            if self._accept_node_drag(event):
                return True
        return super().viewportEvent(event)

    def dragEnterEvent(self, event):
        if not self._accept_node_drag(event):
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if not self._accept_node_drag(event):
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if not self._accept_node_drag(event):
            super().dropEvent(event)

    def dragLeaveEvent(self, event):
        if self._dnd_active:
            self._dnd_active = False
            event.accept()
            return
        super().dragLeaveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_guide()