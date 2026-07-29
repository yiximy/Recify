# -*- coding: utf-8 -*-
"""应用启动：QApplication 初始化、主题应用、异常钩子、日志"""
import sys
import os
import traceback
from datetime import datetime

# 项目根目录（main.py 所在目录）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 将 PaddleX 模型缓存重定向到项目目录（必须在 import paddleocr/paddlex 之前设置）
# 注意：PaddlePaddle C++ 推理引擎不支持含非 ASCII（如中文）的路径，
# 当项目路径含中文时，回退到项目所在盘根目录的 paddlex_cache（ASCII 路径）
_cache_candidate = os.path.join(PROJECT_ROOT, "cache", "paddlex")
if _cache_candidate.isascii():
    _paddlex_cache = _cache_candidate
else:
    _drive = os.path.splitdrive(PROJECT_ROOT)[0]
    _paddlex_cache = os.path.join(_drive + os.sep, "paddlex_cache")
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", _paddlex_cache)

# 确保运行时数据目录存在
for subdir in ("data", "config", "cache", "logs"):
    os.makedirs(os.path.join(PROJECT_ROOT, subdir), exist_ok=True)


def _setup_logging():
    """配置日志文件，记录运行时错误。"""
    log_dir = os.path.join(PROJECT_ROOT, "logs")
    log_file = os.path.join(log_dir, "app.log")
    return log_file


def _install_excepthook(log_file):
    """安装全局异常钩子，未捕获异常写入日志并弹出提示。"""
    def excepthook(exc_type, exc_value, exc_tb):
        # 写入日志文件
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\n[{ts}] 未捕获异常\n{tb_text}\n")
        except Exception:
            pass
        # 控制台也输出
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        # 尝试用 MkMessage 弹窗提示（若 Qt 已初始化）
        try:
            from monkeyqt import MkMessage
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                MkMessage.error(None, f"程序发生错误：{exc_value}\n详情已记录到日志。")
        except Exception:
            pass

    sys.excepthook = excepthook


def run():
    """启动应用程序。"""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    # 高 DPI 支持（Qt6 默认启用，显式设置以确保）
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("发票与支付记录核对辅助系统")
    app.setOrganizationName("InvoiceReconciliation")

    # 应用主题
    from app.ui.theme import apply_theme
    apply_theme(app)

    # 安装异常钩子
    log_file = _setup_logging()
    _install_excepthook(log_file)

    # 初始化数据存储
    from app.core.store import Store
    store = Store(os.path.join(PROJECT_ROOT, "data", "store.json"))

    # 初始化偏好配置
    from app.core.app_config import AppConfig
    config = AppConfig(os.path.join(PROJECT_ROOT, "config", "app_config.json"))

    # 创建主窗口
    from app.ui.main_window import MainWindow
    window = MainWindow(store=store, config=config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    run()
