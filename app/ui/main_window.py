# -*- coding: utf-8 -*-
"""主窗口：MkWindow + MkMenu 侧边栏 + QStackedWidget 内容区"""
from __future__ import annotations

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget
from monkeyqt import MkWindow, MkMenu


class MainWindow(MkWindow):
    """应用主窗口，集成 MonkeyQt 自定义标题栏与侧边栏导航。"""

    def __init__(self, store=None, config=None):
        super().__init__(
            use_custom_title_bar=True,
            preset="default",
            sidebar_full_height=True,
        )

        self.store = store
        self.config = config

        # 自定义标题栏：加高、移除下边框线
        self.titlebar._height = 48
        self.titlebar._border_bottom = "none"
        self.titlebar.apply_theme_colors()
        self.titlebar.rebuild_layout()
        self.update_style()

        self.setWindowTitle("发票与支付记录核对辅助系统")
        self.resize(1440, 920)

        self._build_ui()
        self._connect_signals()
        self._restore_state()

    def _build_ui(self):
        """构建主界面：左侧侧边栏 + 右侧内容区。"""
        # 中央容器
        self.central_widget = QWidget()
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # ── 左侧侧边栏 ──
        self.sidebar = MkMenu(title="发票核对系统", collapse_mode="hamburger")
        self.sidebar.set_border_right("none")
        self.sidebar.add_item("home", "数据总览", icon="house")
        self.sidebar.add_item("compare", "比对关联模式", icon="link")
        self.sidebar.add_item("amount", "计算金额模式", icon="currency-cny")
        self.main_layout.addWidget(self.sidebar)

        # ── 右侧内容区 ──
        self.right_widget = QWidget()
        self.right_layout = QVBoxLayout(self.right_widget)
        self.right_layout.setContentsMargins(20, 20, 20, 20)
        self.right_layout.setSpacing(16)

        # 堆叠页面
        self.content_area = QStackedWidget()

        # 实例化三个页面
        from app.ui.pages.home_page import HomePage
        from app.ui.pages.compare_page import ComparePage
        from app.ui.pages.amount_page import AmountPage

        self.page_home = HomePage(store=self.store)
        self.page_home.setObjectName("home")

        self.page_compare = ComparePage(store=self.store)
        self.page_compare.setObjectName("compare")

        self.page_amount = AmountPage(store=self.store)
        self.page_amount.setObjectName("amount")

        self.content_area.addWidget(self.page_home)
        self.content_area.addWidget(self.page_compare)
        self.content_area.addWidget(self.page_amount)

        self.right_layout.addWidget(self.content_area, stretch=1)
        self.main_layout.addWidget(self.right_widget, stretch=1)

        self.setCentralWidget(self.central_widget)

        # 默认选中首页（_restore_state 会覆盖为上次菜单）
        self.sidebar.set_active("home")

    def _connect_signals(self):
        """连接信号与槽。"""
        self.sidebar.itemClicked.connect(self._on_menu_clicked)

    def _restore_state(self):
        """从配置恢复窗口几何与最近激活页。"""
        if self.config:
            # 恢复窗口几何
            geo_b64 = self.config.get("window_geometry", "")
            if geo_b64:
                self.restoreGeometry(QByteArray.fromBase64(geo_b64.encode("ascii")))
            # 恢复最近菜单
            last_menu = self.config.get("last_menu", "home")
            self._on_menu_clicked(last_menu)
            self.sidebar.set_active(last_menu)

    def _on_menu_clicked(self, item_id: str):
        """侧边栏菜单点击切换页面。"""
        mapping = {
            "home": self.page_home,
            "compare": self.page_compare,
            "amount": self.page_amount,
        }
        if widget := mapping.get(item_id):
            self.content_area.setCurrentWidget(widget)
            # 触发页面激活回调（用于刷新数据）
            if hasattr(widget, "on_page_activated"):
                widget.on_page_activated()
            # 持久化最近菜单
            if self.config:
                self.config.set("last_menu", item_id)

    def closeEvent(self, event: QCloseEvent):
        """关闭时保存窗口几何。"""
        if self.config:
            geo = self.saveGeometry()
            self.config.set("window_geometry",
                            bytes(geo.toBase64()).decode("ascii"))
        super().closeEvent(event)
