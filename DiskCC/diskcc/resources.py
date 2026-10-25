"""资源文件定位：兼容源码运行与 PyInstaller 单文件解包环境。"""

from __future__ import annotations

import os
import sys

_ASSETS_DIR = "assets"


def assets_dir() -> str:
    """返回 assets 目录的绝对路径（onefile 模式下位于解包临时目录）。"""
    base = getattr(sys, "_MEIPASS", None)  # PyInstaller --onefile 解包目录
    if base and os.path.isdir(os.path.join(base, _ASSETS_DIR)):
        return os.path.join(base, _ASSETS_DIR)
    # 源码运行：项目根/assets
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, _ASSETS_DIR)


def asset_path(name: str) -> str:
    return os.path.join(assets_dir(), name)


def app_icon_path() -> str:
    """优先 ico（Windows 任务栏/标题栏更清晰），缺失时回落 png。"""
    ico = asset_path("diskcc.ico")
    if os.path.isfile(ico):
        return ico
    return asset_path("logo.png")
