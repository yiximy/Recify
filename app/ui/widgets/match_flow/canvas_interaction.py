# -*- coding: utf-8 -*-
"""FlowCanvas 的平移、缩放、右键菜单与橡皮筋样式。"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen, QWheelEvent
from PySide6.QtWidgets import QProxyStyle, QStyle

from .items import FlowNodeItem, FlowWireItem

_RUBBER_BAND_FILL = QColor(64, 158, 255, 48)
_RUBBER_BAND_EDGE = QColor(64, 158, 255, 205)
_RIGHT_CLICK_THRESHOLD = 3.0


class _FlowViewStyle(QProxyStyle):
    """只覆盖橡皮筋框绘制，不影响 MonkeyQt 其他控件。"""

    def drawControl(self, element, option, painter, widget=None):
        if element == QStyle.ControlElement.CE_RubberBand:
            painter.save()
            rect = option.rect
            painter.fillRect(rect, _RUBBER_BAND_FILL)
            painter.setPen(QPen(_RUBBER_BAND_EDGE, 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            painter.restore()
            return
        super().drawControl(element, option, painter, widget)


class FlowInteractionMixin:
    """为 FlowCanvas 提供框选、中右键平移与直接缩放事件。"""

    _MIN_ZOOM = 0.4
    _MAX_ZOOM = 2.5

    def mousePressEvent(self, event):
        button = event.button()
        if button in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            if self._scene.is_linking():
                self._scene.cancel_link()
                event.accept()
                return
            self._panning = button == Qt.MouseButton.MiddleButton
            self._pan_button = button
            self._pan_press = event.position()
            self._pan_last = event.position()
            if self._panning:
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if button == Qt.MouseButton.LeftButton \
                and self.itemAt(event.position().toPoint()) is None \
                and not self._scene.is_linking():
            self._scene.clear_wire_selection()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_button is not None:
            pos = event.position()
            if self._pan_button == Qt.MouseButton.RightButton \
                    and not self._panning \
                    and self._distance(pos, self._pan_press) >= _RIGHT_CLICK_THRESHOLD:
                self._panning = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._panning and self._pan_last is not None:
                delta = pos - self._pan_last
                hbar = self.horizontalScrollBar()
                vbar = self.verticalScrollBar()
                hbar.setValue(hbar.value() - int(delta.x()))
                vbar.setValue(vbar.value() - int(delta.y()))
            self._pan_last = pos
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pan_button is not None and event.button() == self._pan_button:
            was_panning = self._panning
            button = self._pan_button
            click_pos = event.position()
            press_pos = self._pan_press
            self._panning = False
            self._pan_button = None
            self._pan_press = None
            self._pan_last = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if button == Qt.MouseButton.RightButton and not was_panning \
                    and self._distance(click_pos, press_pos) < _RIGHT_CLICK_THRESHOLD:
                self._show_context_menu(click_pos.toPoint(),
                                        event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    @staticmethod
    def _distance(a, b) -> float:
        if a is None or b is None:
            return 0.0
        return math.hypot(a.x() - b.x(), a.y() - b.y())

    def _show_context_menu(self, view_pos, screen_pos):
        """右键轻点统一在 release 阶段路由上下文菜单。"""
        if self._scene.is_linking():
            self._scene.cancel_link()
            return
        item = self.itemAt(view_pos)
        if isinstance(item, FlowNodeItem):
            self._scene.clear_wire_selection()
            self._scene.request_node_menu(item.node.node_id, screen_pos)
            return
        if isinstance(item, FlowWireItem):
            if item.wire is None:
                self._scene.cancel_link()
            else:
                self._scene.select_wire(item)
                self._scene.request_wire_menu(item.wire.wire_id, screen_pos)
            return
        self._scene.request_canvas_menu(screen_pos)

    def contextMenuEvent(self, event):
        # 右键路径已由 press/move/release 自定义，屏蔽 Qt 默认重复调用。
        event.accept()

    def wheelEvent(self, event: QWheelEvent):
        angle = event.angleDelta().y()
        if angle == 0:
            angle = event.pixelDelta().y()
        if angle == 0:
            super().wheelEvent(event)
            return
        factor = 1.15 if angle > 0 else 1 / 1.15
        new_zoom = self._zoom * factor
        new_zoom = max(self._MIN_ZOOM, min(self._MAX_ZOOM, new_zoom))
        factor = new_zoom / self._zoom
        self.scale(factor, factor)
        self._zoom = new_zoom
        event.accept()

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
        # 失焦取消 linking/平移，防止状态悬空。
        self._panning = False
        self._pan_button = None
        self._pan_press = None
        self._pan_last = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._scene.cancel_link()
        super().focusOutEvent(event)
