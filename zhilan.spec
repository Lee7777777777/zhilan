# -*- coding: utf-8 -*-
# 知览 · 本地知识库 —— PyInstaller 打包配置
# 用法: pyinstaller --noconfirm --clean 知览.spec
import os

ROOT = SPECPATH

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "assets", "web"), os.path.join("assets", "web")),
        (os.path.join(ROOT, "assets", "icon"), os.path.join("assets", "icon")),
        (os.path.join(ROOT, "app", "ui"), os.path.join("app", "ui")),
    ],
    hiddenimports=[
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
        "clr",
        "markdown_it",
        "mdit_py_plugins.tasklists",
        "mdit_py_plugins.footnote",
        "mdit_py_plugins.admon",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6",
        "PyQt5", "PyQt6", "tkinter", "matplotlib", "numpy", "scipy", "pandas",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="知览",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "assets", "icon", "app.ico"),
)
