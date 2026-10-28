# -*- coding: utf-8 -*-
"""路径解析：区分只读资源与可写数据，兼容源码运行与 PyInstaller 打包"""
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))


def _resource_root() -> Path:
    """只读资源（assets/web、app/ui）。onefile 模式下位于解压出的临时目录"""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def _data_root() -> Path:
    """可写数据（library/）。打包后固定放在 exe 同级目录，避免随临时目录被清除"""
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


RESOURCE_DIR = _resource_root()
DATA_DIR = _data_root()
WEB_DIR = RESOURCE_DIR / "assets" / "web"
UI_DIR = RESOURCE_DIR / "app" / "ui"
LIB_DIR = DATA_DIR / "library"
ICON_PATH = RESOURCE_DIR / "assets" / "icon" / "app.ico"
