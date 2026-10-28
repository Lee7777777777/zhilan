# -*- coding: utf-8 -*-
"""本地 HTTP 服务：向桌面窗口（或浏览器）提供 UI 静态资源与知识点 API"""
import json
import mimetypes
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from app.kb_index import KnowledgeIndex, atomic_write
from app.paths import LIB_DIR, UI_DIR, WEB_DIR
from app.renderer import (IMG_RE, MdRenderer, is_local_image, read_text,
                          split_image_target)

INDEX = KnowledgeIndex(LIB_DIR)


def settings_file() -> Path:
    """设置跟着库根目录走：换成别的库时不会误写到真实数据上"""
    return INDEX.root / "settings.json"


# 外部打开（右键菜单 / 命令行传入 .md）时暂存要展示的条目，前端取走即清空
_PENDING = {"id": None}
_PENDING_LOCK = threading.Lock()
_PING_HITS = {"n": 0}


def set_pending(eid):
    with _PENDING_LOCK:
        _PENDING["id"] = eid


def note_ping():
    with _PENDING_LOCK:
        _PING_HITS["n"] += 1
        return _PING_HITS["n"]


def take_pending():
    with _PENDING_LOCK:
        eid = _PENDING["id"]
        _PENDING["id"] = None
    if not eid:
        return None
    try:
        INDEX.find(eid)
    except StopIteration:
        return None        # 条目已被移除，别让前端去打开一个不存在的 id
    return eid


# 由 main.py 注入：把"有新文件要打开"直接推给窗口里的页面。
# 只靠前端定时器不行——窗口被遮挡时 Chromium 会把它节流到一分钟一次。
NOTIFY = None


def notify_frontend():
    cb = NOTIFY
    if not cb:
        return
    def run():
        try:
            cb("window.__pendingNow && window.__pendingNow()")
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()

# 外观设置：键 -> (默认值, 最小值, 最大值)；None 表示不做数值裁剪
NUMERIC = {
    "fontScale": (16, 13, 22),
    "lineHeight": (1.75, 1.4, 2.2),
    "contentWidth": (860, 620, 1200),
    "sideWidth": (288, 220, 400),
}
FLAGS = {
    "mode": ("dark", {"dark", "light", "sepia"}),
    "codeTheme": ("dark", {"dark", "light"}),
    "fontFamily": ("sans", {"sans", "serif", "mono"}),
    "density": ("comfortable", {"comfortable", "compact"}),
    "showToc": (True, None),
}
ACCENT_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def default_settings():
    out = {k: v[0] for k, v in NUMERIC.items()}
    out.update({k: v[0] for k, v in FLAGS.items()})
    out["accent"] = "#5aa2f0"
    return out


def clamp_settings(raw):
    merged = default_settings()
    if isinstance(raw, dict):
        merged.update({k: v for k, v in raw.items() if k in merged})
    for key, (_, lo, hi) in NUMERIC.items():
        try:
            merged[key] = max(lo, min(hi, float(merged[key])))
        except (TypeError, ValueError):
            merged[key] = NUMERIC[key][0]
    for key, allowed in (("mode", FLAGS["mode"][1]), ("codeTheme", FLAGS["codeTheme"][1]),
                         ("fontFamily", FLAGS["fontFamily"][1]), ("density", FLAGS["density"][1])):
        if merged[key] not in allowed:
            merged[key] = default_settings()[key]
    if not ACCENT_RE.match(str(merged["accent"])):
        merged["accent"] = "#5aa2f0"
    merged["showToc"] = bool(merged["showToc"])
    return merged


def load_settings(path=None):
    target = Path(path) if path else settings_file()
    try:
        return clamp_settings(json.loads(target.read_text(encoding="utf-8")))
    except Exception:
        return default_settings()


def save_settings(raw, path=None):
    target = Path(path) if path else settings_file()
    data = clamp_settings(raw)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, json.dumps(data, ensure_ascii=False, indent=2))
    return data

def rewrite_local_images(body: str, eid: str) -> str:
    """把相对路径图片指向 /media/<eid>/<rel>；带空格的路径也能正确改写并做 URL 编码"""
    def repl(m):
        alt = m.group(1)
        url, title = split_image_target(m.group(2))
        if not is_local_image(url):
            return m.group(0)          # 绝对地址 / data: / file: 一律不动
        rel = quote(url.replace("\\", "/"), safe="/")
        return "![%s](/media/%s/%s%s)" % (alt, eid, rel, title)

    return IMG_RE.sub(repl, body)


def _safe_join(base: Path, rel: str) -> Path:
    """阻止 ../ 穿越；用 relative_to 判断，避免 notes 与 notes-backup 这类同前缀目录误判"""
    base = base.resolve()
    target = (base / unquote(rel)).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError("path escape") from None
    return target


class Server(ThreadingHTTPServer):
    """页面一次会并发拉十几个资源，默认 backlog=5 容易让连接排队甚至被丢"""
    daemon_threads = True
    request_queue_size = 64


class Handler(BaseHTTPRequestHandler):
    server_version = "ZhiLan/1.0"
    # 用 HTTP/1.0 并逐条关闭连接：WebView2 复用本地长连接时会挂住请求
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(body)
        try:
            self.wfile.flush()
        except Exception:
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    # ---------- GET ----------
    def do_GET(self):
        try:
            self._route_GET()
        except ValueError:
            self._send(403, "forbidden", "text/plain")
        except Exception as ex:
            self._send(500, "internal error: %s" % ex, "text/plain; charset=utf-8")

    def _route_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            return self._file(_safe_join(UI_DIR, "index.html"))
        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            target = _safe_join(WEB_DIR, rel)
            if not target.is_file():
                target = _safe_join(UI_DIR, rel)
            return self._file(target)
        if path.startswith("/media/"):
            return self._media(path[len("/media/"):])
        if path == "/api/entries":
            qs = parse_qs(parsed.query)
            q = qs.get("q", [""])[0].strip().lower()
            cat = qs.get("category", [""])[0].strip()
            items = []
            for e in reversed(INDEX.entries):
                blob = (KnowledgeIndex.display(e) + " " + e.get("title", "") + " "
                        + " ".join(e["tags"])).lower()
                if q and q not in blob:
                    continue
                own = e.get("category") or ""
                if cat == "-" and own:
                    continue
                if cat and cat != "-" and own != cat:
                    continue
                items.append({
                    "id": e["id"], "title": e["title"], "display": KnowledgeIndex.display(e),
                    "alias": e.get("alias"), "tags": e["tags"],
                    "source_name": e["source_name"], "added_at": e["added_at"],
                    "category": e.get("category") or None,
                })
            return self._json({"items": items, "total": len(INDEX.entries)})
        if path == "/api/categories":
            cats, untagged = INDEX.category_view()
            return self._json({"categories": cats, "untagged": untagged, "total": len(INDEX.entries)})
        if path == "/api/settings":
            return self._json(load_settings())
        if path == "/api/maintenance":
            return self._json(INDEX.orphan_report())
        if path == "/api/ping":
            return self._json({"ok": True, "pid": os.getpid(), "hits": note_ping(),
                               "pending": bool(_PENDING["id"])})
        if path == "/api/pending":
            return self._json({"id": take_pending()})
        if path == "/api/wait":
            return self._wait()
        m = re.match(r"^/api/entries/([0-9a-f]{12})$", path)
        if m:
            return self._entry(m.group(1))
        m = re.match(r"^/api/entries/([0-9a-f]{12})/source$", path)
        if m:
            return self._source(m.group(1))
        return self._send(404, "not found", "text/plain")

    def _source(self, eid: str):
        entry = INDEX.find(eid)
        target = INDEX.source_path(eid)
        self._json({
            "id": eid,
            "path": str(target),
            "in_library": target == INDEX.path(eid),
            "content": read_text(target),
            "source_name": entry.get("source_name", target.name),
        })

    def _file(self, f: Path):
        if not f.is_file():
            return self._send(404, "not found", "text/plain")
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, f.read_bytes(), ctype)

    def _wait(self):
        """长轮询：最多挂 25 秒，一来外部文件就立刻返回。
        页面被遮挡时浏览器会把 setInterval 节流到分钟级，但网络请求不受影响。"""
        deadline = time.time() + 25
        while time.time() < deadline:
            eid = take_pending()
            if eid:
                return self._json({"id": eid})
            time.sleep(0.25)
        return self._json({"id": None})

    def _media(self, rest: str):
        """本地图片：优先读 library/assets/<eid>/ 里的副本，没有再回退原件所在目录"""
        eid, _, rel = rest.partition("/")
        try:
            entry = INDEX.find(eid)
        except StopIteration:
            return self._send(404, "not found", "text/plain")
        try:
            cached = _safe_join(INDEX.assets_dir(eid), rel)
            if cached.is_file():
                return self._file(cached)
        except (ValueError, OSError):
            return self._send(403, "forbidden", "text/plain")
        origin = entry.get("origin_dir")
        if not origin:
            return self._send(404, "not found", "text/plain")
        try:
            return self._file(_safe_join(Path(origin), rel))
        except (ValueError, OSError):
            return self._send(403, "forbidden", "text/plain")

    def _entry(self, eid: str):
        try:
            entry = INDEX.find(eid)
        except StopIteration:
            return self._json({"error": "not found"}, 404)
        md_path = INDEX.path(eid)
        title, tags, body = MdRenderer.parse_file(md_path)
        # 本地图片改走 /media 通道
        body = rewrite_local_images(body, eid)
        html, toc = MdRenderer().render(body)
        self._json({
            "id": eid, "title": title, "tags": tags,
            "html": html, "toc": toc,
            "source_name": entry.get("source_name", ""),
            "category": entry.get("category") or None,
            "alias": entry.get("alias"),
            "display": KnowledgeIndex.display(entry),
        })

    # ---------- POST ----------
    def do_POST(self):
        try:
            self._route_POST()
        except ValueError as ex:
            self._send(400, str(ex) or "bad request", "text/plain; charset=utf-8")
        except KeyError:
            self._send(404, "not found", "text/plain")
        except Exception as ex:
            self._send(500, "internal error: %s" % ex, "text/plain; charset=utf-8")

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            raw = self.rfile.read(length).decode("utf-8")
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as ex:
            raise ValueError("invalid request body: %s" % ex)
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def _route_POST(self):
        path = urlparse(self.path).path
        if path == "/api/settings":
            return self._json(save_settings(self._body()))
        if path == "/api/categories":
            return self._json(INDEX.add_category(self._body().get("name", "")))
        if path == "/api/entries":
            body = self._body()
            entry = INDEX.create(body.get("title"), body.get("category"), body.get("content"))
            return self._json({
                "id": entry["id"], "title": entry["title"],
                "display": KnowledgeIndex.display(entry),
                "category": entry.get("category"),
            })
        if path == "/api/maintenance/cleanup":
            return self._json(INDEX.cleanup())
        if path == "/api/open":
            raw = self._body().get("path")
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError("缺少 path")
            src = Path(raw).expanduser()
            if src.suffix.lower() != ".md" or not src.is_file():
                raise ValueError("不是可读取的 .md 文件：%s" % raw)
            entry = INDEX.add(src)
            set_pending(entry["id"])
            notify_frontend()
            return self._json({
                "id": entry["id"], "title": entry["title"],
                "display": KnowledgeIndex.display(entry),
            })
        m = re.match(r"^/api/categories/([0-9a-f]{10})/rename$", path)
        if m:
            return self._json(INDEX.rename_category(m.group(1), self._body().get("name", "")))
        m = re.match(r"^/api/categories/([0-9a-f]{10})/delete$", path)
        if m:
            INDEX.delete_category(m.group(1))
            return self._json({"ok": True})
        m = re.match(r"^/api/entries/([0-9a-f]{12})/rename$", path)
        if m:
            entry = INDEX.set_alias(m.group(1), self._body().get("alias"))
            return self._json({
                "id": entry["id"], "title": entry["title"],
                "alias": entry.get("alias"), "display": KnowledgeIndex.display(entry),
                "source_name": entry.get("source_name"),
            })
        m = re.match(r"^/api/entries/([0-9a-f]{12})/file$", path)
        if m:
            entry = INDEX.rename_source(m.group(1), self._body().get("name"))
            return self._json({
                "id": entry["id"], "source_name": entry["source_name"],
                "path": str(Path(entry["origin_dir"]) / entry["source_name"]),
                "title": entry["title"], "alias": entry.get("alias"),
                "display": KnowledgeIndex.display(entry),
            })
        m = re.match(r"^/api/entries/([0-9a-f]{12})/category$", path)
        if m:
            INDEX.set_category(m.group(1), self._body().get("category"))
            return self._json({"ok": True})
        m = re.match(r"^/api/entries/([0-9a-f]{12})/source$", path)
        if m:
            content = self._body().get("content")
            if not isinstance(content, str):
                raise ValueError("content 必须是字符串")
            return self._json(INDEX.save_source(m.group(1), content))
        m = re.match(r"^/api/entries/([0-9a-f]{12})/delete$", path)
        if m:
            INDEX.remove(m.group(1))     # 失败就让异常冒到 500，不再假装成功
            return self._json({"ok": True})
        return self._send(404, "not found", "text/plain")


def serve(port: int = 0):
    httpd = Server(("127.0.0.1", port), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    # 老库没有图片副本，后台补齐，不阻塞窗口出现
    threading.Thread(target=INDEX.sync_all_assets, daemon=True).start()
    return httpd, "http://127.0.0.1:%d/" % httpd.server_address[1]
