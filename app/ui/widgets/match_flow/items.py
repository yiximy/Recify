# -*- coding: utf-8 -*-
"""流程画布图形项：模块节点卡片 / 输入输出端口 / 贝塞尔连线（QGraphicsItem 自绘）。

v2：节点显示绑定摘要（文件/组合 + 金额徽标）与匹配接入统计；store 在创建/刷新时
注入到图形项，仅 refresh_content / tooltip 时读取（paint 不触 store）。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from .model import (
    FlowNode,
    FlowWire,
    KIND_INVOICE,
    KIND_LABELS,
    KIND_MATCH,
    KIND_PAYMENT,
    KIND_SOURCES,
)

# ── 模块配色（画布节点类型色带保留，Elegant Light 一致）──
STYLE = {
    KIND_INVOICE: {"accent": QColor("#409eff"), "bg": QColor("#ecf5ff")},
    KIND_PAYMENT: {"accent": QColor("#67c23a"), "bg": QColor("#f0f9eb")},
    KIND_MATCH: {"accent": QColor("#e6a23c"), "bg": QColor("#fdf6ec")},
}

# ── 几何常量 ──
NODE_W = 210
NODE_H = 96
HEADER_H = 26
PORT_R = 6
_PORT_HOVER_R = 9
_MARGIN = PORT_R + 4          # 卡片外留白，容纳端口/选中描边
_RADIUS = 8

# 连线配色
_WIRE_COLOR = QColor("#a8b2c1")
_WIRE_HOVER = QColor("#409eff")
_WIRE_INVALID = QColor("#f56c6c")
_WIRE_TEMP = QColor("#409eff")
_WIRE_WIDTH = 2.0

_TEXT_DARK = QColor("#303133")
_TEXT_GRAY = QColor("#909399")
_WARN_ORANGE = QColor("#e6a23c")
_BORDER = QColor("#e4e7ed")
_GREEN = QColor("#67c23a")
_WHITE = QColor("#ffffff")
_BADGE_BG = QColor("#f0f2f5")


def _fmt_amount(amount: Optional[float]) -> str:
    """金额显示：None → 「—」，否则千分位两位小数。"""
    if amount is None:
        return "—"
    return f"¥{amount:,.2f}"


def _make_bezier(p0: QPointF, p3: QPointF) -> QPainterPath:
    """横向出/入端的贝塞尔连线（Node-RED 风格自动路径）。"""
    path = QPainterPath(p0)
    dx = abs(p3.x() - p0.x())
    handle = max(40.0, min(160.0, dx * 0.5))
    sign = 1.0 if p3.x() >= p0.x() else -1.0
    c1 = QPointF(p0.x() + sign * handle, p0.y())
    c2 = QPointF(p3.x() - sign * handle, p3.y())
    path.cubicTo(c1, c2, p3)
    return path


class FlowNodeItem(QGraphicsItem):
    """模块节点卡片：色带头 + 名称/信息行 + 金额徽标 + 左右端口。

    交互（由场景协调）：
        - 在输出/输入端口按下 → 开始拖出连线（scene.begin_link；输入端为反向发起，
          连线方向仍按发票→匹配→支付）
        - 卡片其它区域按下 → 默认可移动（ItemIsMovable）
        - 双击 → 打开配置（scene 转成 nodeConfigRequested 信号）
        - 右键 → 节点菜单（配置…/删除模块）
    """

    def __init__(self, node: FlowNode, store=None,
                 parent: Optional[QGraphicsItem] = None):
        super().__init__(parent)
        self.node = node
        self._store = store
        self._inv_in = 0              # 匹配模块：发票入线数
        self._pay_out = 0             # 匹配模块：支付出线数
        self._match_amount: Optional[float] = None   # 匹配模块：链金额（场景刷新注入）
        self._link_target_in = False   # 连线拖拽悬停：本节点输入侧为合法目标（亮左端口）
        self._link_target_out = False  # 连线拖拽悬停：本节点输出侧为合法目标（亮右端口）
        self._link_source = False      # 正在从此节点输出端口正向拖线（右端口高亮）
        self._link_input = False       # 正在从此节点输入端口反向拖线（左端口高亮）
        self._press_scene = QPointF()  # 记录按下点（防双击误拖）
        self._moved = False
        # 源模块派生显示（refresh_content 计算缓存，paint 只读）
        self._bound = False
        self._info_text = ""
        self._badge_text = ""
        self._member_lines: list[str] = []
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                      | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                      | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setToolTip(self._make_tooltip())
        self.setZValue(10)
        if self.node.is_source and self._store is not None:
            self.refresh_content()

    # ── store 注入 ──

    def set_store(self, store):
        self._store = store
        if self.node.is_source and store is not None:
            self.refresh_content()
        elif self.node.is_source:
            self._bound = False
            self._info_text = ""
            self._badge_text = ""
            self.setToolTip(self._make_tooltip())
            self.update()

    # ── 几何 ──

    def boundingRect(self) -> QRectF:
        return QRectF(-_MARGIN, -_MARGIN,
                      NODE_W + 2 * _MARGIN, NODE_H + 2 * _MARGIN)

    def in_port_pos(self) -> QPointF:
        """输入端口（左缘中点）场景坐标。"""
        return self.scenePos() + QPointF(0.0, NODE_H / 2.0)

    def out_port_pos(self) -> QPointF:
        """输出端口（右缘中点）场景坐标。"""
        return self.scenePos() + QPointF(NODE_W, NODE_H / 2.0)

    # ── 内容刷新 ──

    def set_match_summary(self, inv_in: int, pay_out: int):
        """匹配模块：发票入线数 / 支付出线数。"""
        self._inv_in = inv_in
        self._pay_out = pay_out
        self.setToolTip(self._make_tooltip())
        self.update()

    def set_match_amount(self, amount: Optional[float]):
        """匹配模块：链金额（由场景在线路/绑定变化时刷新注入）。"""
        self._match_amount = amount
        self.setToolTip(self._make_tooltip())
        self.update()

    def refresh_content(self):
        """绑定/参数/名称变化后重算派生显示并重绘。"""
        if self.node.is_source and self._store is not None:
            self._compute_binding()
        self.setToolTip(self._make_tooltip())
        self.update()

    # ── 源模块绑定摘要计算（store 读取仅在此处）──

    def _compute_binding(self):
        node = self.node
        store = self._store
        getter = store.get_invoice if node.kind == KIND_INVOICE else store.get_payment
        member_lines: list[str] = []
        seen_ids: set[str] = set()
        singles: list[str] = []

        def add_member(f):
            fid = getattr(f, "file_id", "")
            if fid in seen_ids:
                return
            seen_ids.add(fid)
            member_lines.append(self._member_line(f))

        for fid in node.file_ids:
            f = getter(fid)
            if f is None or getattr(f, "missing", False):
                continue
            if fid in seen_ids:
                continue
            seen_ids.add(fid)
            singles.append(fid)
            member_lines.append(self._member_line(f))
        combos: list[tuple[str, str, int]] = []
        for cid in node.combo_ids:
            combo = store.get_combo(cid)
            if not combo or combo.get("kind") != node.kind:
                continue
            members = [fid for fid in combo.get("file_ids", [])
                       if self._file_exists(getter, fid)]
            if not members:
                continue
            combos.append((cid, combo.get("name", ""), len(members)))
            for fid in members:
                f = getter(fid)
                if f is not None and not getattr(f, "missing", False):
                    add_member(f)

        self._bound = bool(singles or combos)
        if not self._bound:
            self._info_text = "未绑定文件/组合"
            self._badge_text = ""
        elif len(combos) == 1 and not singles:
            _cid, cname, cmembers = combos[0]
            self._info_text = f"组合「{cname}」（{cmembers} 文件）"
            self._badge_text = _fmt_amount(node.bind_amount(store))
        else:
            parts = []
            if len(singles) == 1 and not combos:
                f = getter(singles[0])
                self._info_text = getattr(f, "file_name", "") or ""
            else:
                if singles:
                    parts.append(f"{len(singles)} 文件")
                if combos:
                    parts.append(f"{len(combos)} 组合")
                self._info_text = " · ".join(parts)
            self._badge_text = _fmt_amount(node.bind_amount(store))
        self._member_lines = member_lines

    @staticmethod
    def _file_exists(getter, fid: str) -> bool:
        f = getter(fid)
        return f is not None and not getattr(f, "missing", False)

    def _member_line(self, f) -> str:
        amt = getattr(getattr(f, "amount", None), "final_amount", None)
        name = getattr(f, "file_name", "") or ""
        linked = bool(getattr(f, "linked_payment_ids", [])
                      or getattr(f, "linked_invoice_ids", []))
        text = f"• {name} — {_fmt_amount(amt)}"
        if linked:
            text += "（已关联）"
        return text

    # ── tooltip ──

    def _make_tooltip(self) -> str:
        kind_label = KIND_LABELS.get(self.node.kind, self.node.kind)
        lines = [f"{kind_label}模块：{self.node.name}"]
        if self.node.is_source:
            if self._bound:
                lines.extend(self._member_lines or [self._info_text])
                lines.append(f"绑定金额：{self._badge_text}")
            else:
                lines.append("未绑定文件/组合（双击配置绑定）")
        else:
            tol = self.node.params.get("tolerance", 0.01)
            lines.append(f"金额容差：±{tol:g} 元")
            lines.append(f"链金额：{_fmt_amount(self._match_amount)}")
            lines.append(f"接入：发票 {self._inv_in} 路 → 支付 {self._pay_out} 路")
        lines.append("左右端口均可拖动连接 · 双击配置 · 右键菜单 · 节点可拖动")
        return "\n".join(lines)

    # ── 交互 ──

    def _hit_output_port(self, local: QPointF) -> bool:
        c = QPointF(NODE_W, NODE_H / 2.0)
        return (local - c).manhattanLength() <= 16

    def _hit_input_port(self, local: QPointF) -> bool:
        """输入端口（左缘中点）命中：按下即反向发起拖线。"""
        c = QPointF(0.0, NODE_H / 2.0)
        return (local - c).manhattanLength() <= 16

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            self._moved = True
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            # 位置变化 → 更新本节点关联连线（勿在此 setPos，防递归）
            scene = self.scene()
            if scene is not None and hasattr(scene, "sync_wires_for_node"):
                scene.sync_wires_for_node(self.node.node_id)
            self.node.x = self.pos().x()
            self.node.y = self.pos().y()
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._hit_output_port(event.pos()):
                self._link_source = True
                self._moved = False
                self._press_scene = event.scenePos()
                scene = self.scene()
                if scene is not None and hasattr(scene, "begin_link"):
                    scene.begin_link(self.node.node_id)
                event.accept()
                return
            if self._hit_input_port(event.pos()):
                # 输入端口反向发起：连线方向不变，最终方向由
                # scene.begin_link(from_input=True) 按 can_connect(目标, 本模块) 判定
                self._moved = False
                self._press_scene = event.scenePos()
                scene = self.scene()
                if scene is not None and hasattr(scene, "begin_link"):
                    scene.begin_link(self.node.node_id, from_input=True)
                event.accept()
                return
            self._moved = False
            self._press_scene = event.scenePos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        scene = self.scene()
        if (event.buttons() & Qt.MouseButton.LeftButton) and scene is not None \
                and hasattr(scene, "is_linking") and scene.is_linking():
            scene.update_temp(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        scene = self.scene()
        if event.button() == Qt.MouseButton.LeftButton and scene is not None \
                and hasattr(scene, "is_linking") and scene.is_linking():
            scene.finish_link(event.scenePos())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        # 位移阈值：双击前若已拖动则不当作配置意图
        if not self._moved:
            scene = self.scene()
            if scene is not None and hasattr(scene, "request_config"):
                scene.request_config(self.node.node_id)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        scene = self.scene()
        # 连线拖拽中在节点体上右键：先取消连线，不弹菜单
        if scene is not None and hasattr(scene, "is_linking") and scene.is_linking():
            scene.cancel_link()
            event.accept()
            return
        if scene is not None and hasattr(scene, "request_node_menu"):
            scene.request_node_menu(self.node.node_id, event.screenPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    # ── 绘制 ──

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem,
              widget: Optional[QWidget] = None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        style = STYLE.get(self.node.kind, STYLE[KIND_MATCH])
        accent = style["accent"]

        # 卡片主体
        card = QRectF(0.0, 0.0, NODE_W, NODE_H)
        path = QPainterPath()
        path.addRoundedRect(card, _RADIUS, _RADIUS)
        painter.setPen(QPen(_BORDER, 1))
        painter.setBrush(_WHITE)
        painter.drawPath(path)

        # 色带头（裁到圆角内）
        painter.save()
        painter.setClipPath(path)
        header = QRectF(0.0, 0.0, NODE_W, HEADER_H)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRect(header)
        kind_label = KIND_LABELS.get(self.node.kind, self.node.kind)
        painter.setFont(self._font(12, bold=True))
        painter.setPen(_WHITE)
        painter.drawText(header.adjusted(10, 0, -10, 0),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         kind_label)
        painter.restore()

        # 名称
        name_rect = QRectF(10, HEADER_H + 6, NODE_W - 20, 18)
        painter.setFont(self._font(12, bold=True))
        painter.setPen(_TEXT_DARK)
        painter.drawText(name_rect,
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         self._elided(painter, self.node.name, name_rect.width()))

        # 信息行（源=绑定摘要/警示；匹配=金额 + 参数/接入）
        info_rect = QRectF(10, HEADER_H + 26, NODE_W - 20, 16)
        if self.node.is_source:
            if self._bound:
                painter.setPen(_TEXT_GRAY)
            else:
                painter.setPen(_WARN_ORANGE)
            painter.drawText(info_rect,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             self._elided(painter, self._info_text or "未绑定文件/组合",
                                          info_rect.width()))
        else:
            painter.setPen(_TEXT_GRAY)
            painter.drawText(info_rect,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             f"金额 {_fmt_amount(self._match_amount)}")
            tol = self.node.params.get("tolerance", 0.01)
            info2 = QRectF(10, HEADER_H + 44, NODE_W - 20, 16)
            painter.drawText(info2,
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             f"±{tol:g} 元 · 发票 {self._inv_in} 入 · 支付 {self._pay_out} 出")

        # 源模块：右下角金额徽标
        if self.node.is_source and self._badge_text:
            painter.setFont(self._font(10, bold=True))
            fm = QFontMetrics(painter.font())
            tw = fm.horizontalAdvance(self._badge_text)
            bw = tw + 14
            badge = QRectF(NODE_W - 8 - bw, NODE_H - 24, bw, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_BADGE_BG)
            painter.drawRoundedRect(badge, 9, 9)
            painter.setPen(_TEXT_DARK)
            painter.drawText(badge.adjusted(7, 0, -7, 0),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             self._badge_text)

        # 连线悬停合法目标高亮：命中侧端口 + 卡片描绿边（合法目标统一用绿色描边）
        if self._link_target_in or self._link_target_out:
            painter.setPen(QPen(_GREEN, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(card.adjusted(1, 1, -1, -1), _RADIUS, _RADIUS)

        # 选中描边
        if self.isSelected():
            painter.setPen(QPen(QColor("#409eff"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(card.adjusted(1, 1, -1, -1), _RADIUS, _RADIUS)

        # 端口（左=输入：悬停「输入侧」合法目标/反向拖线源高亮；右=输出：悬停「输出侧」合法目标/正向拖线源高亮）
        self._draw_port(painter, QPointF(0.0, NODE_H / 2.0), accent,
                        self._link_target_in or self._link_input)
        self._draw_port(painter, QPointF(NODE_W, NODE_H / 2.0), accent,
                        self._link_target_out or self._link_source, output=True)

    def _draw_port(self, painter: QPainter, center: QPointF,
                   accent: QColor, active: bool, output: bool = False):
        r = _PORT_HOVER_R if active else PORT_R
        painter.setPen(QPen(_WHITE, 2))
        painter.setBrush(accent if active else _WHITE)
        painter.drawEllipse(center, r, r)
        painter.setPen(QPen(accent if active else QColor("#c0c4cc"), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, PORT_R, PORT_R)

    def _font(self, size: int, bold: bool = False) -> QFont:
        f = QFont()
        f.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"])
        f.setPixelSize(size)
        f.setBold(bold)
        return f

    @staticmethod
    def _elided(painter: QPainter, text: str, width: float) -> str:
        fm = QFontMetrics(painter.font())
        return fm.elidedText(text, Qt.TextElideMode.ElideMiddle, int(width))


class FlowWireItem(QGraphicsItem):
    """贝塞尔连线：源模块输出 → 匹配模块输入 / 匹配模块输出 → 支付模块输入。

    - shape() 加宽命中（约 12px），便于点击/右键选中删除
    - hover/选中高亮加粗变色
    - 也可作为「临时橡皮筋线」使用（temp=True，终点随鼠标更新）
    """

    _HIT_WIDTH = 12.0

    def __init__(self, wire: Optional[FlowWire] = None, temp: bool = False,
                 parent: Optional[QGraphicsItem] = None):
        super().__init__(parent)
        self.wire = wire              # 正式连线；temp 线为 None
        self._temp = temp
        self._p0 = QPointF()
        self._p3 = QPointF()
        self._hover = False
        self._selected = False
        self._invalid = False
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton
                                     | Qt.MouseButton.RightButton)
        self.setAcceptHoverEvents(True)
        self.setToolTip("连线：右键删除 · 单击选中")
        self.setZValue(0 if not temp else 1000)
        if temp:
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)

    # ── 几何 ──

    def set_endpoints(self, p0: QPointF, p3: QPointF):
        self.prepareGeometryChange()
        self._p0 = p0
        self._p3 = p3
        self.update()

    def set_invalid(self, invalid: bool):
        self._invalid = invalid
        self.update()

    def boundingRect(self) -> QRectF:
        hw = self._HIT_WIDTH
        r = QRectF(self._p0, self._p3).normalized().adjusted(
            -hw, -hw, hw, hw)
        return r

    def shape(self) -> QPainterPath:
        from PySide6.QtGui import QPainterPathStroker
        path = _make_bezier(self._p0, self._p3)
        stroker = QPainterPathStroker()
        stroker.setWidth(self._HIT_WIDTH)
        return stroker.createStroke(path)

    def _build_path(self) -> QPainterPath:
        return _make_bezier(self._p0, self._p3)

    # ── 交互 ──

    def hoverEnterEvent(self, event):
        self._hover = True
        self.setToolTip("连线（右键删除，单击选中）")
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        scene = self.scene()
        if scene is not None and hasattr(scene, "select_wire"):
            scene.select_wire(self)
        event.accept()

    def contextMenuEvent(self, event):
        scene = self.scene()
        # 连线拖拽中右键（临时线/正式线/节点体上的线）：一律先取消连线
        if scene is not None and hasattr(scene, "is_linking") and scene.is_linking():
            scene.cancel_link()
            event.accept()
            return
        if self.wire is None:
            # 临时橡皮筋线：右键 = 取消连线（不弹菜单）
            if scene is not None and hasattr(scene, "cancel_link"):
                scene.cancel_link()
            event.accept()
            return
        if scene is not None and hasattr(scene, "request_wire_menu"):
            scene.request_wire_menu(self.wire.wire_id, event.screenPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    # ── 绘制 ──

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem,
              widget: Optional[QWidget] = None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._temp:
            color = _WIRE_INVALID if self._invalid else _WIRE_TEMP
            pen = QPen(color, _WIRE_WIDTH)
            pen.setStyle(Qt.PenStyle.DashLine)
        else:
            if self._hover or self._selected:
                pen = QPen(_WIRE_HOVER, _WIRE_WIDTH + 0.8)
            else:
                pen = QPen(_WIRE_COLOR, _WIRE_WIDTH)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._build_path())

    def set_selected(self, selected: bool):
        self._selected = selected
        self.update()