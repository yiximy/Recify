# -*- coding: utf-8 -*-
"""应用偏好配置：JSON 读写（窗口几何/主题/最近菜单）"""
from __future__ import annotations

import json
import os


class AppConfig:
    """轻量偏好读写，持久化窗口尺寸、主题、最近激活菜单。

    注意：文件夹路径由 Store 管理，此处仅管 UI 偏好。
    """

    DEFAULTS = {
        "theme": "Elegant Light",
        "last_menu": "home",
        "window_geometry": "",  # QByteArray base64 字符串
    }

    def __init__(self, path: str):
        self._path = path
        self._data: dict = self._load()

    def _load(self) -> dict:
        """加载配置，缺失则用默认值补全。"""
        data = dict(self.DEFAULTS)
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data.update(loaded)
            except (json.JSONDecodeError, IOError):
                pass
        return data

    def save(self):
        """原子写保存。"""
        tmp_path = self._path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except IOError:
            pass

    def get(self, key: str, default=None):
        """读取配置项。"""
        if default is None:
            default = self.DEFAULTS.get(key)
        return self._data.get(key, default)

    def set(self, key: str, value):
        """设置配置项并立即保存。"""
        self._data[key] = value
        self.save()
