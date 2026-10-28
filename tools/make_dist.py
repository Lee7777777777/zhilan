# -*- coding: utf-8 -*-
"""生成可分发的源码压缩包：zhilan-<版本>-source.zip

用法: python tools/make_dist.py

包含：全部源码、离线前端资源、示例、工具脚本、构建配置与文档。
排除：个人知识库（library/）、git 历史（.git/）、本地记忆（.workbuddy/）、
      构建产物（build/、dist/、exe）、Python 缓存。
解压到任意目录即可运行（脚本内的路径都按自身位置解析，与目录名无关）。
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import __version__          # noqa: E402

DIRS = ("app", "assets", "sample", "tools")
FILES = ("main.py", "README.md", "LICENSE", ".gitignore", "requirements.txt",
         "zhilan.spec", "build_exe.bat", "启动知览.bat", "dev_server.py")

SKIP_DIR_PARTS = {".git", ".workbuddy", "build", "dist", "library", "__pycache__"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".tmp", ".zip")


def collect():
    out = [ROOT / f for f in FILES if (ROOT / f).is_file()]
    for d in DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(ROOT)
            if any(part in SKIP_DIR_PARTS for part in rel.parts):
                continue
            if p.suffix.lower() in SKIP_SUFFIXES:
                continue
            out.append(p)
    return out


def main():
    files = collect()
    top = "zhilan-%s" % __version__
    out = ROOT / ("zhilan-%s-source.zip" % __version__)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            z.write(p, "%s/%s" % (top, p.relative_to(ROOT).as_posix()))
    print("打包完成:", out.name)
    print("  文件数: %d" % len(files))
    print("  大小:   %.1f MB" % (out.stat().st_size / 1048576))
    print("  顶层:   %s/  （解压后进入该目录运行）" % top)
    return out


if __name__ == "__main__":
    main()
