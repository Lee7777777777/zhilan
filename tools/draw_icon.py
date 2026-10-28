# -*- coding: utf-8 -*-
"""生成知览的镂空图标源图（透明背景 + 线条文档），再用 make_icon.py 转 ico

用法:
    python tools/draw_icon.py                       # 输出 assets/icon/icon-src.png
    python tools/make_icon.py assets/icon/icon-src.png assets/icon/app.ico

线条粗细、颜色都集中在下面的常量里，改完重跑即可。
"""
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
BLUE = (65, 146, 252)        # 主线条色
DEEP = (28, 88, 200)         # 折页填充色

W_FRONT = 62                 # 前层描边宽度
W_BACK = 34                  # 后层描边宽度
W_BAR = 40                   # 内容横线粗细

# 前层文档轮廓（右上角为折角斜边）
FRONT = [(340, 250), (590, 250), (770, 430), (770, 860), (340, 860)]
# 折页三角
FOLD = [(590, 250), (770, 430), (590, 430)]
# 后层文档（提供层次）
BACK = [(270, 180), (520, 180), (700, 360), (700, 790), (270, 790)]
# 内容横线：(y, 右边界)，第三条短一些
BARS = ((545, 690), (640, 690), (735, 615))


def draw(out: Path):
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.line(BACK + [BACK[0]], fill=BLUE + (95,), width=W_BACK, joint="curve")
    d.line(FRONT + [FRONT[0]], fill=BLUE + (255,), width=W_FRONT, joint="curve")
    d.polygon(FOLD, fill=DEEP + (255,))
    for y, x1 in BARS:
        d.rounded_rectangle((415, y, x1, y + W_BAR), radius=W_BAR // 2, fill=BLUE + (255,))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


if __name__ == "__main__":
    target = draw(Path("assets/icon/icon-src.png"))
    print("源图 ->", target)
