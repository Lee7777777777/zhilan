# -*- coding: utf-8 -*-
"""知览 · 本地知识库：桌面窗口外壳（WebView2）+ 本地服务"""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import webview

from app.paths import DATA_DIR, LIB_DIR
import app.server as app_server
from app.server import INDEX, load_settings, notify_frontend, serve, set_pending

BG_BY_MODE = {"dark": "#1b1e23", "light": "#f6f7f9", "sepia": "#f3ead9"}
WINDOW_TITLE = "知览 · 本地知识库"
INSTANCE_FILE = DATA_DIR / ".instance.json"


def collect_md_args(argv):
    """从命令行参数里挑出存在的 .md 文件（右键菜单会以 "%1" 传进来）"""
    out = []
    for raw in argv[1:]:
        if not raw or raw.startswith("-"):
            continue
        p = Path(raw)
        if p.suffix.lower() == ".md" and p.is_file():
            out.append(p.resolve())
    return out


def existing_port():
    """读取上次写下的端口并探测是否真的还活着，避免被残留文件误导"""
    try:
        data = json.loads(INSTANCE_FILE.read_text(encoding="utf-8"))
        port = int(data.get("port") or 0)
    except Exception:
        return None
    if not port:
        return None
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port, timeout=1.5) as r:
            return port if r.status == 200 else None
    except Exception:
        # 端口没人应答：上次多半是强杀或崩溃，把残留文件清掉别耽误下次启动
        try:
            INSTANCE_FILE.unlink()
        except OSError:
            pass
        return None


def record_instance(port):
    try:
        INSTANCE_FILE.write_text(
            json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    except OSError:
        pass


def forward_to_existing(port, paths):
    """把待打开的文件交给已经运行的窗口，返回是否全部成功"""
    ok = True
    for p in paths:
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:%d/api/open" % port,
                data=json.dumps({"path": str(p)}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST")
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            ok = False
    return ok


def activate_existing():
    """没有文件参数又已经开着窗口时，把那个窗口提到前台"""
    try:
        from ctypes import windll
        hwnd = windll.user32.FindWindowW(None, WINDOW_TITLE)
        if hwnd:
            windll.user32.ShowWindow(hwnd, 9)
            windll.user32.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass
    return False


def library_problem():
    """库目录不可写时，后续所有保存都会失败，不如在启动阶段就说清楚"""
    try:
        probe = LIB_DIR / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return None
    except Exception as ex:
        return str(ex)


# WebView2 Evergreen Runtime 的更新通道 GUID，用来判断有没有装运行时
WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"


def webview2_version():
    """返回 WebView2 运行时版本号，本机没装则返回 None。

    Windows 11 出厂自带；Windows 10 有一部分机器（尤其是长期未更新的 LTSC
    或精简版）没有，界面会直接起不来，所以启动前先探一次。
    """
    try:
        import winreg
    except ImportError:
        return "unknown"          # 非 Windows 平台，交给 pywebview 自己处理
    base = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\%s" % WEBVIEW2_GUID
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for flags in (0, winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(root, base, 0, winreg.KEY_READ | flags) as k:
                    try:
                        return winreg.QueryValueEx(k, "pv")[0]
                    except OSError:
                        return "已安装"      # 键在但没有版本号，也算装了
            except OSError:
                continue
    return None


def fatal(msg):
    """没有窗口可用时的最后提示：原生消息框，不依赖前端"""
    try:
        from ctypes import windll
        windll.user32.MessageBoxW(None, msg, "知览 · 启动失败", 0x10)
    except Exception:
        print(msg, file=sys.stderr)


class Api:
    """暴露给前端 JS 的原生能力"""

    def __init__(self):
        self._window = None
        self._target = None

    def set_import_target(self, category=None):
        """记住当前选中的分类，拖拽导入时归入该分类"""
        self._target = category or None
        return True

    def import_files(self, category=None):
        try:
            fd = webview.FileDialog.OPEN
        except AttributeError:
            fd = webview.OPEN_DIALOG
        paths = self._window.create_file_dialog(
            fd, allow_multiple=True, file_types=("Markdown (*.md)", "所有文件 (*.*)")
        )
        if paths:
            self.import_paths(list(paths), category)
        return True

    def import_paths(self, paths, category=None):
        added, errors = [], []
        target = category or self._target
        for p in paths:
            f = Path(str(p))
            if f.suffix.lower() != ".md" or not f.is_file():
                continue
            try:
                entry = INDEX.add(f, target)
                added.append(entry)
            except Exception as ex:
                errors.append("%s: %s" % (f.name, ex))
        # 不依赖 evaluate_js（部分环境上会挂住）：置为待打开，页面通过长轮询取走后自行刷新
        if added:
            set_pending(added[-1]["id"])
            notify_frontend()
        return {"added": [e["title"] for e in added], "errors": errors}

    def reveal_in_folder(self, eid):
        """在资源管理器中定位原始 .md 文件"""
        try:
            entry = INDEX.find(eid)
        except StopIteration:
            return False
        origin = entry.get("origin_dir")
        if not origin:                       # 库内新建的知识点，定位库内副本
            item = INDEX.path(eid)
            if item.exists():
                subprocess.Popen(["explorer", "/select,", str(item)])
                return True
            return False
        target = Path(origin) / entry.get("source_name", "")
        if target and target.exists():
            subprocess.Popen(["explorer", "/select,", str(target)])
            return True
        if origin and Path(origin).is_dir():
            os.startfile(str(origin))
            return True
        return False

    def _pick_folder(self):
        """弹出文件夹选择框，取消时返回 None"""
        if not self._window:
            return None
        try:
            flag = webview.FOLDER_DIALOG
        except AttributeError:
            flag = getattr(webview, "FOLDER_DIALOG", None)
        if flag is None:
            return None
        try:
            picked = self._window.create_file_dialog(flag, allow_multiple=False)
        except Exception:
            return None
        if not picked:
            return None
        return picked[0] if isinstance(picked, (list, tuple)) else picked

    def export_entry(self, eid):
        """导出单条知识点（正文 + 图片）到用户选择的文件夹"""
        dest = self._pick_folder()
        if not dest:
            return {"ok": False, "error": "已取消"}
        try:
            info = INDEX.export_entry(eid, dest)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        return {"ok": True, **info}

    def export_library(self):
        """把整个知识库打包成 zip 备份"""
        dest = self._pick_folder()
        if not dest:
            return {"ok": False, "error": "已取消"}
        try:
            info = INDEX.export_library(dest)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        return {"ok": True, **info}


API = None


def apply_window_icon(win):
    """给窗口标题栏与任务栏设上应用图标（源码运行时 exe 图标不存在，靠这里补）"""
    from ctypes import c_int, c_uint, c_void_p, c_wchar_p, windll

    from app.paths import ICON_PATH

    if not ICON_PATH.is_file():
        return
    try:
        hwnd = int(win.native.Handle)
    except Exception:
        return
    try:
        user32 = windll.user32
        user32.LoadImageW.restype = c_void_p
        user32.LoadImageW.argtypes = [c_void_p, c_wchar_p, c_uint, c_int, c_int, c_uint]
        user32.SendMessageW.restype = c_int
        user32.SendMessageW.argtypes = [c_void_p, c_uint, c_void_p, c_void_p]
        path, IMAGE_ICON, LR_LOADFROMFILE = str(ICON_PATH), 1, 0x0010
        small = user32.LoadImageW(None, path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        big = user32.LoadImageW(None, path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE) or small
        if small:
            user32.SendMessageW(hwnd, 0x0080, 0, small)          # WM_SETICON / ICON_SMALL
        if big:
            user32.SendMessageW(hwnd, 0x0080, 1, big)            # WM_SETICON / ICON_BIG
    except Exception:
        pass


def on_started():
    """页面加载完成后注册原生拖放（pywebview 6 通过 DOM 事件投递文件路径）"""
    win = webview.windows[0]

    def handle_drop(event):
        data = event if isinstance(event, dict) else getattr(event, "event", {}) or {}
        files = (data.get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if paths:
            API.import_paths(paths)

    def bind():
        apply_window_icon(win)
        try:
            win.dom.body.on("drop", handle_drop)
        except Exception as ex:
            print("拖放未启用:", ex, file=sys.stderr)
            try:
                win.evaluate_js("window.toast && toast('拖放导入不可用，请改用「导入知识点」按钮')")
            except Exception:
                pass

    win.events.loaded += bind


def main():
    global API
    problem = library_problem()
    if problem:
        fatal("知识库目录无法写入：\n%s\n\n%s\n\n请检查文件夹权限、只读属性或磁盘空间后重试。"
              % (LIB_DIR, problem))
        return
    files = collect_md_args(sys.argv)

    # 已经有窗口在跑：文件转交过去，别开第二个进程抢着写同一个库
    running = existing_port()
    if running:
        enough = forward_to_existing(running, files) if files else False
        if files and enough:
            activate_existing()   # 把窗口叫到前台：既让用户看到，也解除浏览器对定时器的节流
            return
        if not files and activate_existing():
            return

    API = Api()
    httpd, url = serve()
    record_instance(httpd.server_address[1])
    for f in files:
        try:
            entry = INDEX.add(f)
            set_pending(entry["id"])
        except Exception as ex:
            print("导入失败 %s: %s" % (f, ex), file=sys.stderr)

    window = webview.create_window(
        WINDOW_TITLE,
        url,
        js_api=API,
        width=1280,
        height=820,
        min_size=(1040, 620),
        text_select=True,
        easy_drag=False,
        background_color=BG_BY_MODE.get(load_settings()["mode"], "#1b1e23"),
    )
    API._window = window
    # 让服务端在处理 /api/open 时能把页面叫起来（窗口被遮挡时定时器会被节流）
    app_server.NOTIFY = lambda js: window.evaluate_js(js)
    try:
        webview.start(on_started, debug="--debug" in sys.argv)
    except Exception as ex:
        # 最常见的失败原因就是 Windows 10 上缺 WebView2 运行时，给可执行的指引而不是堆栈
        if webview2_version() is None:
            fatal("本机没有检测到 Microsoft Edge WebView2 运行时，界面无法渲染。\n\n"
                  "Windows 10 的部分版本不会预装它。请下载安装（约 1 MB 引导器，需联网）：\n%s\n\n"
                  "装好后重新双击启动知览即可。" % WEBVIEW2_URL)
            return
        raise
    finally:
        httpd.shutdown()
        try:
            if INSTANCE_FILE.is_file():
                INSTANCE_FILE.unlink()
        except OSError:
            pass


def env_check():
    """python main.py --check：不启动窗口，只报告启动条件是否满足"""
    import platform

    print("知览 环境自检")
    print("-" * 46)
    print("系统        : %s %s (%s)" % (platform.system(), platform.release(), platform.version()))
    print("架构        : %s" % (platform.machine(),))
    print("Python      : %s" % sys.version.split()[0])
    if sys.version_info < (3, 9):
        print("             !! 需要 Python 3.9 及以上")
    else:
        print("             OK")
    try:
        import webview as _wv
        print("pywebview   : %s" % getattr(_wv, "__version__", "已安装"))
    except Exception as ex:
        print("pywebview   : 缺失 (%s)" % ex)
    ver = webview2_version()
    if ver:
        print("WebView2    : %s" % ver)
    else:
        print("WebView2    : 未安装 -> %s" % WEBVIEW2_URL)
    problem = library_problem()
    print("知识库目录  : %s" % LIB_DIR)
    print("             %s" % ("OK" if not problem else "不可写：%s" % problem))
    for mod, name in (("markdown_it", "markdown-it-py"),
                      ("mdit_py_plugins", "mdit-py-plugins"),
                      ("frontmatter", "python-frontmatter")):
        try:
            __import__(mod)
            print("%-12s: OK" % name)
        except Exception:
            print("%-12s: 缺失" % name)
    print("-" * 46)
    print("全部就绪" if ver and not problem else "请先按上面带 !! / 未安装 的项目处理")


if __name__ == "__main__":
    if "--check" in sys.argv:
        env_check()
    else:
        try:
            main()
        except Exception:
            # 打包成无控制台的 exe 后异常无处可看，落盘便于排查
            import traceback

            from app.paths import DATA_DIR, FROZEN

            if FROZEN:
                (DATA_DIR / "知览-崩溃日志.txt").write_text(
                    traceback.format_exc(), encoding="utf-8")
            raise
