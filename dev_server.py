# -*- coding: utf-8 -*-
"""调试用：只起本地服务（不带窗口），便于在浏览器里验证渲染效果
用法: python dev_server.py  [自动导入 sample/ 下的 .md]"""
import time
from pathlib import Path

from app.server import INDEX, serve

if __name__ == "__main__":
    for f in sorted(Path("sample").glob("*.md")):
        if not any(e["source_name"] == f.name for e in INDEX.entries):
            INDEX.add(f)
    httpd, url = serve(8765)
    print("dev server:", url, flush=True)
    while True:
        time.sleep(1)
