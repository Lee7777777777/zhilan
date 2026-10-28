# -*- coding: utf-8 -*-
"""调试工具：用 PrintWindow 抓取知览窗口（即使被其他窗口遮挡）
用法: python tools/capture_window.py [输出文件名]"""
import ctypes
import ctypes.wintypes as wt
import sys

from PIL import Image

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
found = []
EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)


def collect(hwnd, _):
    if user32.IsWindowVisible(hwnd):
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if "知览" in buf.value:
                found.append(hwnd)
    return True


user32.EnumWindows(EnumProc(collect), 0)
if not found:
    sys.exit("未找到知览窗口")

hwnd = found[0]
rect = wt.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
w, h = rect.right - rect.left, rect.bottom - rect.top

dc = user32.GetWindowDC(hwnd)
mem = gdi32.CreateCompatibleDC(dc)
bmp = gdi32.CreateCompatibleBitmap(dc, w, h)
gdi32.SelectObject(mem, bmp)
printed = user32.PrintWindow(hwnd, mem, 2)  # PW_RENDERFULLCONTENT


class BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32), ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32),
    ]


hdr = BitmapInfoHeader()
hdr.biSize = ctypes.sizeof(hdr)
hdr.biWidth, hdr.biHeight, hdr.biPlanes = w, h, 1
hdr.biBitCount, hdr.biCompression = 32, 0
pixels = (ctypes.c_char * (w * h * 4))()
bits = gdi32.GetDIBits(mem, bmp, 0, h, pixels, ctypes.byref(hdr), 0)

img = Image.frombytes("RGBA", (w, h), bytes(pixels), "raw", "BGRA", 0, -1).convert("RGB")
out = sys.argv[1] if len(sys.argv) > 1 else ".ui_win.png"
img.save(out)
gdi32.DeleteDC(mem)
user32.ReleaseDC(hwnd, dc)
print("PrintWindow=%s scanlines=%d %dx%d -> %s" % (printed, bits, w, h, out))
