# -*- coding: utf-8 -*-
"""发票与支付记录核对辅助系统 — 程序入口"""

import sys
import os

# 确保项目根目录在 sys.path 中（兼容直接 python main.py 运行）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.app_entry import run


if __name__ == "__main__":
    run()
