# -*- coding: utf-8 -*-
"""把 PNG 图标源图转成 Windows .ico（多尺寸）并输出小尺寸预览图
用法: python tools/make_icon.py <源图.png> [输出.ico] [--trim]
  --trim  从四角泛洪填充抠掉纯色背景，并把内容裁到外接方框（适合白底/黑底生成的图）"""
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

SIZES = (256, 128, 64, 48, 32, 24, 16)
MARKER = (255, 0, 255)


def square_up(img):
    """源图非正方形时居中裁方"""
    img = img.convert("RGBA")
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def trim_background(img):
    """四角泛洪填充标记背景色 -> 透明，再裁到内容外接方框并补成正方形"""
    rgb = img.convert("RGB")
    w, h = rgb.size
    filled = rgb.copy()
    for corner in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        ImageDraw.floodfill(filled, corner, MARKER, thresh=48)

    diff = ImageChops.difference(filled, Image.new("RGB", filled.size, MARKER)).convert("L")
    is_bg = diff.point(lambda v: 255 if v < 14 else 0).convert("1")
    alpha = ImageChops.invert(is_bg).convert("L")
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    box = alpha.getbbox()
    out = out.crop(box)
    side = max(out.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(out, ((side - out.width) // 2, (side - out.height) // 2), out)
    return canvas


def main(src, out, trim=False):
    base = Image.open(src)
    base = trim_background(base) if trim else square_up(base)
    base.save(out, format="ICO", sizes=[(s, s) for s in SIZES])
    base.save(out.with_name(out.stem + "-source.png"))

    sheet = Image.new("RGBA", (sum(SIZES) + 26 * (len(SIZES) + 1), 300), (18, 20, 24, 255))
    x = 26
    for s in SIZES:
        thumb = base.resize((s, s), Image.LANCZOS)
        sheet.paste(thumb, (x, (300 - s) // 2), thumb)
        x += s + 26
    preview = out.with_suffix(".preview.png")
    sheet.convert("RGB").save(preview)
    print("ico     ->", out)
    print("源图    ->", out.with_name(out.stem + "-source.png"))
    print("小尺寸预览 ->", preview)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--trim"]
    if not args:
        sys.exit("用法: python tools/make_icon.py <源图.png> [输出.ico] [--trim]")
    source = Path(args[0])
    target = Path(args[1]) if len(args) > 1 else Path("assets/icon/app.ico")
    target.parent.mkdir(parents=True, exist_ok=True)
    main(source, target, trim="--trim" in sys.argv)
