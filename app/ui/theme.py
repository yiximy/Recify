# -*- coding: utf-8 -*-
"""主题常量与应用封装"""
from PySide6.QtGui import QFont, QFontDatabase

# MonkeyQt 内置主题名（Elegant Light 优雅浅色商务风格）
THEME_NAME = "Elegant Light"

def apply_theme(app):
    """应用 MonkeyQt 主题到 QApplication。

    使用 Elegant Light 优雅浅色主题，适合长时间办公使用。
    若主题加载失败则回退到默认样式，不影响程序启动。
    """
    try:
        from monkeyqt import use_theme
        use_theme(app, THEME_NAME)
    except Exception as e:
        # 主题加载失败不应阻断启动，记录警告即可
        print(f"[WARN] 主题加载失败，使用默认样式: {e}")

    # 统一应用字体（优先使用系统默认中文字体）
    _apply_font(app)


def _apply_font(app):
    """设置全局字体，确保中文显示清晰。"""
    font = QFont()
    # Windows 上微软雅黑是最佳中文 UI 字体
    font.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
                      "Noto Sans CJK SC", "Segoe UI", "Arial"])
    font.setPointSize(9)
    app.setFont(font)
