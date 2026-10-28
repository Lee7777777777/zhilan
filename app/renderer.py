# -*- coding: utf-8 -*-
"""Markdown -> HTML 渲染核心（纯 Python，无 GUI 依赖，可单测）"""
import re
from html import escape as escapeHtml
from pathlib import Path
from urllib.parse import unquote

import frontmatter
from markdown_it import MarkdownIt
from mdit_py_plugins.admon import admon_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

# 解码顺序：无 BOM 的 UTF-8 / 带 BOM 的 UTF-8 / 简体中文常见 ANSI 编码
ENCODINGS = ("utf-8-sig", "gb18030", "utf-16")


def read_text(path) -> str:
    """按可能性依次尝试解码，全部失败才用替换字符兜底（不抛异常）"""
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    for enc in ENCODINGS:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


# ---------- 图片引用解析（server 与 kb_index 共用，避免循环导入） ----------
IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\n]*)\)")
IMG_TITLE = re.compile(r'^(.*?)(\s+["\'].*["\'])?$', re.S)
SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.\-]*:", re.I)


def split_image_target(raw: str):
    """把 ![](...) 里的内容拆成 (url, 可选 title)，兼容 <带空格的路径> 写法"""
    raw = raw.strip()
    mt = IMG_TITLE.match(raw)
    url = (mt.group(1) or "").strip() if mt else raw
    title = (mt.group(2) or "") if mt else ""
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1].strip()
    return url, title


def is_local_image(url: str) -> bool:
    """相对路径才算本地图片：http/data/file 等 scheme 与 / 开头的绝对路径不动"""
    return bool(url) and not url.startswith(("/", "//")) and not SCHEME_RE.match(url)


def iter_local_images(body: str):
    """逐个产出正文引用到的本地图片相对路径（已做 URL 解码、统一为正斜杠）"""
    for m in IMG_RE.finditer(body):
        url, _ = split_image_target(m.group(2))
        if is_local_image(url):
            yield unquote(url).replace("\\", "/")


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff\- ]", "", text).strip()
    s = re.sub(r"\s+", "-", s)
    return s.lower() or "section"


BLOCK_MATH = re.compile(r"\$\$([\s\S]+?)\$\$")
INLINE_MATH = re.compile(r"(?<!\\)\$(?![\s$])((?:[^$\n]|\\\$)*?[^\s$])\$(?!\$)")
# 占位符用 Unicode 私有区字符包裹，正文里不可能手打出同样的串
SPECIAL = "\ue000"
TOKEN = re.compile(SPECIAL + r"M(\d+)" + SPECIAL)


def protect_math(text):
    """把 $...$ / $$...$$ 换成占位符，避免下划线等被 Markdown 解析成强调（跳过围栏代码块）"""
    store = []

    def stash(open_, body_):
        store.append((open_, body_))
        return "%sM%d%s" % (SPECIAL, len(store) - 1, SPECIAL)

    def mask(chunk):
        chunk = BLOCK_MATH.sub(lambda m: stash("$$", m.group(1)), chunk)
        return INLINE_MATH.sub(lambda m: stash("$", m.group(1)), chunk)

    fence = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
    chunks, cur, in_fence = [], [], False
    for line in text.split("\n"):
        if fence.match(line):
            chunks.append((in_fence, "\n".join(cur)))
            cur = [line]
            in_fence = not in_fence
        else:
            cur.append(line)
    chunks.append((in_fence, "\n".join(cur)))
    return "\n".join(c if is_code else mask(c) for is_code, c in chunks), store


def restore_math(html, store, escape=True):
    def repl(m):
        idx = int(m.group(1))
        if idx >= len(store):          # 防御：占位符数量对不上时原样保留，别抛 IndexError
            return m.group(0)
        open_, body_ = store[idx]
        inner = escapeHtml(body_) if escape else body_
        return "%s%s%s" % (open_, inner, open_)

    return TOKEN.sub(repl, html)


DOLLAR = re.compile(r"\$+([^$]*)\$+")


def plain_math(text):
    """目录等纯文本场景：去掉公式的 $ 包裹，只留可读内容"""
    return DOLLAR.sub(lambda m: m.group(1).strip(), text)


class MdRenderer:
    def __init__(self):
        self.md = (
            MarkdownIt("commonmark")
            .enable(["table", "strikethrough", "linkify"])
            .use(tasklists_plugin)
            .use(footnote_plugin)
            .use(admon_plugin)
        )
        self._toc = []

        def fence_override(_renderer, tokens, idx, options, env):
            token = tokens[idx]
            lang = token.info.strip().split(maxsplit=1)[0] if token.info.strip() else ""
            content = token.content
            if lang == "mermaid":
                return '<div class="mermaid">%s</div>\n' % escapeHtml(content)
            if lang == "math":
                return '<div class="katex-block">$$%s$$</div>\n' % escapeHtml(content)
            if lang:
                return '<pre><code class="language-%s">%s</code></pre>\n' % (
                    escapeHtml(lang), escapeHtml(content))
            return "<pre><code>%s</code></pre>\n" % escapeHtml(content)

        self.md.add_render_rule("fence", fence_override)

        # 标题注入锚点 id + 收集目录
        def heading_text(inline):
            parts = []
            for child in inline.children or []:
                if child.type in ("text", "code_inline"):
                    parts.append(child.content)
            return "".join(parts) or inline.content

        def anchor_core(state):
            self._toc = []
            used = {}
            for i, tok in enumerate(state.tokens):
                if tok.type != "heading_open" or i + 1 >= len(state.tokens):
                    continue
                inline = state.tokens[i + 1]
                if inline.type != "inline":
                    continue
                text = heading_text(inline).strip()
                if not text:
                    continue
                level = int(tok.tag[1])
                base = _slug(text)
                used[base] = used.get(base, 0) + 1
                slug = base if used[base] == 1 else "%s-%d" % (base, used[base] - 1)
                tok.attrSet("id", slug)
                self._toc.append({"level": level, "text": text, "id": slug})

        self.md.core.ruler.push("anchor_inject", anchor_core)

    def render(self, body: str):
        guarded, store = protect_math(body)
        html = self.md.render(guarded)
        toc = [{"level": t["level"], "id": t["id"],
                "text": plain_math(restore_math(t["text"], store, escape=False))}
               for t in self._toc]
        return restore_math(html, store), toc

    @staticmethod
    def parse_file(path):
        """返回 (title, tags, body)；标题优先级: frontmatter > 首个 # 标题 > 文件名"""
        path = Path(path)
        post = frontmatter.loads(read_text(path))
        meta = post.metadata or {}
        body = post.content
        title = str(meta.get("title") or "").strip()
        if not title:
            m = re.search(r"^#\s+(.+)$", body, re.M)
            title = m.group(1).strip() if m else path.stem
        tags = meta.get("tags") or meta.get("category") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in re.split(r"[,，;；]", tags) if t.strip()]
        return title, [str(t) for t in tags], body
