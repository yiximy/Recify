# -*- coding: utf-8 -*-
"""QThread 基类：统一后台线程的进度上报与异常处理"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class BaseWorker(QThread):
    """后台工作线程基类。

    信号：
        progress(int, int, str): (current, total, message) 进度上报
        finished_ok(object): 正常完成，携带结果对象
        failed(str): 发生错误，携带错误描述
    """

    progress = Signal(int, int, str)   # current, total, message
    finished_ok = Signal(object)
    failed = Signal(str)

    def run(self):
        """线程入口，子类实现具体逻辑。"""
        try:
            self._safe_run()
        except Exception as e:
            self.failed.emit(str(e))

    def _safe_run(self):
        """子类重写：执行实际工作，通过 emit 信号回报进度与结果。"""
        raise NotImplementedError
