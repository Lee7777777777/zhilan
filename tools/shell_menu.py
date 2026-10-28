# -*- coding: utf-8 -*-
"""注册 / 注销 .md 文件的右键菜单「用知览打开」

用法:
    python tools/shell_menu.py register          # 用项目里的 知览.exe 注册
    python tools/shell_menu.py register --exe "D:\\其他位置\\知览.exe"
    python tools/shell_menu.py status
    python tools/shell_menu.py unregister

只写 HKEY_CURRENT_USER，不需要管理员，也不会改动 .md 的默认打开方式。
Windows 11 的精简右键菜单要求点「显示更多选项」（或按 Shift+F10）才能看到第三方菜单项。
"""
import argparse
import sys
from pathlib import Path

import winreg

ROOT = Path(__file__).resolve().parent.parent
KEY_ASSOC = r"Software\Classes\SystemFileAssociations\.md\shell\ZhiLan"
KEY_APP = r"Software\Classes\Applications\知览.exe"
VERB_NAME = "用知览打开"


def default_exe() -> Path:
    return ROOT / "知览.exe"


def default_icon() -> Path:
    ico = ROOT / "assets" / "icon" / "app.ico"
    return ico if ico.is_file() else default_exe()


def _write(root, path, values):
    with winreg.CreateKey(root, path) as k:
        for name, value in values.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def register(exe: Path, icon: Path) -> None:
    exe, icon = exe.resolve(), icon.resolve()
    if not exe.is_file():
        raise SystemExit("找不到程序：%s" % exe)
    command = '"%s" "%%1"' % exe

    _write(winreg.HKEY_CURRENT_USER, KEY_ASSOC,
           {None: VERB_NAME, "Icon": str(icon)})
    _write(winreg.HKEY_CURRENT_USER, KEY_ASSOC + r"\command", {None: command})

    # 顺带登记到「打开方式」列表
    _write(winreg.HKEY_CURRENT_USER, KEY_APP,
           {"FriendlyAppName": "知览"})
    _write(winreg.HKEY_CURRENT_USER, KEY_APP + r"\shell\open\command", {None: command})
    _write(winreg.HKEY_CURRENT_USER, KEY_APP + r"\SupportedTypes", {".md": ""})

    print("已注册右键菜单：%s" % VERB_NAME)
    print("  菜单键   HKCU\\%s" % KEY_ASSOC)
    print("  可执行   %s" % exe)
    print("  图标     %s" % icon)


def _delete_tree(root, path):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _delete_tree(root, path + "\\" + sub)
    except FileNotFoundError:
        return
    winreg.DeleteKey(root, path)


def unregister() -> None:
    for path in (KEY_ASSOC, KEY_APP):
        _delete_tree(winreg.HKEY_CURRENT_USER, path)
        print("已删除 HKCU\\%s" % path)


def status() -> None:
    ok = True
    for path in (KEY_ASSOC + r"\command", KEY_APP + r"\shell\open\command"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                print("%-58s %s" % (path, winreg.QueryValueEx(k, None)[0]))
        except FileNotFoundError:
            print("%-58s 未注册" % path)
            ok = False
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(description="注册 .md 右键菜单")
    ap.add_argument("action", choices=("register", "unregister", "status"))
    ap.add_argument("--exe", help="知览.exe 的完整路径，默认用项目根目录下的")
    ap.add_argument("--icon", help="图标文件，默认用 assets/icon/app.ico")
    args = ap.parse_args()

    if args.action == "register":
        exe = Path(args.exe) if args.exe else default_exe()
        icon = Path(args.icon) if args.icon else default_icon()
        register(exe, icon)
    elif args.action == "unregister":
        unregister()
    else:
        status()


if __name__ == "__main__":
    main()
