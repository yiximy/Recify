# -*- coding: utf-8 -*-
"""主窗口：MkWindow + MkMenu 侧边栏 + QStackedWidget 内容区"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget,
    QDialog, QLabel, QPushButton, QVBoxLayout as QVBox,
)
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

        # 在标题栏添加「关于」按钮（置于窗口控制按钮左侧）
        self.btn_about = QPushButton("关于")
        self.btn_about.setObjectName("titlebarAboutBtn")
        self.btn_about.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_about.clicked.connect(self._show_about)
        self.btn_about.setStyleSheet("""
            QPushButton#titlebarAboutBtn {
                background: transparent;
                color: #909399;
                border: none;
                font-size: 13px;
                padding: 4px 8px;
                margin-right: 4px;
            }
            QPushButton#titlebarAboutBtn:hover {
                color: #409eff;
            }
        """)
        # 找到标题栏布局，插入到 stretch 之后、窗口按钮之前
        tb_layout = self.titlebar.layout()
        if tb_layout:
            # 布局结构: [icon][title][stretch][min][max][close]
            # 在 stretch(索引2) 之后插入
            tb_layout.insertWidget(3, self.btn_about)
        self.update_style()

        self.setWindowTitle("”愿你开心，不止今天“")
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

    # ── 关于对话框 ─────────────────────────────────────────

    def _show_about(self):
        """显示关于对话框。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("关于 Recify")
        dlg.setFixedSize(420, 350)
        dlg.setStyleSheet("""
            QDialog {
                background: #ffffff;
            }
        """)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(0)

        # 应用名称
        title = QLabel("Recify")
        title.setStyleSheet(
            "font-size: 24px; font-weight: 700; color: #303133;"
        )
        layout.addWidget(title)

        # 副标题
        subtitle = QLabel("发票与支付记录核对辅助系统")
        subtitle.setStyleSheet(
            "font-size: 14px; color: #606266; margin-top: 4px;"
        )
        layout.addWidget(subtitle)

        layout.addSpacing(20)

        # 分隔线
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #ebeef5;")
        layout.addWidget(sep)

        layout.addSpacing(20)

        # 描述
        desc = QLabel(
            "一款基于 PaddleOCR 的桌面端发票智能核对工具，\n"
            "支持 PDF 发票与支付截图的 OCR 金额识别、\n"
            "自动比对关联及文件批量重命名，\n"
            "帮助高效完成报销核对工作。"
        )
        desc.setStyleSheet(
            "font-size: 13px; color: #606266; line-height: 1.6;"
        )
        layout.addWidget(desc)

        layout.addSpacing(18)

        # GitHub 链接
        gh_label = QLabel(
            '项目链接：<a href="https://github.com/yiximy/Recify" '
            'style="color:#409eff;text-decoration:none;font-size:13px;">'
            'github.com/yiximy/Recify</a>'
        )
        gh_label.setOpenExternalLinks(True)
        gh_label.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(gh_label)

        layout.addSpacing(6)

        # 作者（可点击链接）
        author = QLabel(
            '作者：<a href="https://github.com/yiximy" '
            'style="color:#409eff;text-decoration:none;font-size:13px;">'
            '伊戏（yiximy）</a>'
        )
        author.setOpenExternalLinks(True)
        author.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(author)

        layout.addSpacing(6)

        ver = QLabel("版本：1.0.0")
        ver.setStyleSheet("font-size: 12px; color: #c0c4cc;")
        layout.addWidget(ver)

        layout.addStretch()

        # 关闭按钮
        btn_close = QPushButton("确定")
        btn_close.setFixedWidth(88)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background: #409eff;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                font-size: 13px;
                padding: 8px 0px;
            }
            QPushButton:hover {
                background: #337ecc;
            }
        """)
        btn_close.clicked.connect(dlg.accept)
        btn_wrap = QHBoxLayout()
        btn_wrap.addStretch()
        btn_wrap.addWidget(btn_close)
        layout.addLayout(btn_wrap)

        dlg.exec()

    # ── 窗口关闭 ──────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent):
        """关闭时保存窗口几何。"""
        if self.config:
            geo = self.saveGeometry()
            self.config.set("window_geometry",
                            bytes(geo.toBase64()).decode("ascii"))
        super().closeEvent(event)
