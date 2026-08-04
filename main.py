# -*- coding: utf-8 -*-
"""Recify — 发票与支付记录核对辅助系统

Author:  伊戏 (yiximy)
GitHub:  https://github.com/yiximy
License: MIT
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.app_entry import run


if __name__ == "__main__":
    run()
