# -*- coding: utf-8 -*-
"""文件夹选择条组件"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QFileDialog, QLineEdit,
)
from monkeyqt import MkButton


class FolderPicker(QWidget):
    """文件夹选择条：路径输入框 + 选择按钮。

    信号：
        folderChanged(str): 文件夹路径变化时发出
    """

    folderChanged = Signal(str)

    def __init__(self, label: str = "文件夹", parent=None):
        super().__init__(parent)
        self._label = label
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 路径显示框（只读）
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText(f"请选择{self._label}...")
        self.path_edit.setMinimumHeight(36)
        self.path_edit.setStyleSheet("""
            QLineEdit {
                background: #f5f7fa;
                border: 1px solid #dcdfe6;
                border-radius: 6px;
                padding: 0 12px;
                color: #606266;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #409eff;
            }
        """)
        layout.addWidget(self.path_edit, stretch=1)

        # 选择按钮
        self.btn_select = MkButton(f"选择{self._label}", type="default")
        self.btn_select.clicked.connect(self._on_select)
        layout.addWidget(self.btn_select)

    def _on_select(self):
        """打开文件夹选择对话框。"""
        current = self.path_edit.text() or ""
        folder = QFileDialog.getExistingDirectory(
            self, f"选择{self._label}", current
        )
        if folder:
            self.path_edit.setText(folder)
            self.folderChanged.emit(folder)

    def get_path(self) -> str:
        """获取当前选择的文件夹路径。"""
        return self.path_edit.text()

    def set_path(self, path: str):
        """设置文件夹路径（不触发信号）。"""
        self.path_edit.setText(path)

    def clear(self):
        """清空路径（不触发信号）。"""
        self.path_edit.clear()

    def set_label(self, label: str):
        """更新标签文本。"""
        self._label = label
        self.path_edit.setPlaceholderText(f"请选择{self._label}...")
        self.btn_select.setText(f"选择{self._label}")
