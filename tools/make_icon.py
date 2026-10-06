#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成应用图标 assets/app.ico（多尺寸），顺便给桌面快捷方式用。

    python -m tools.make_icon
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont   # noqa: E402

OUT = ROOT / "assets" / "app.ico"
SIZE = 256
RADIUS = 58

TOP = (37, 99, 235)      # #2563eb 亮蓝
BOTTOM = (23, 37, 84)    # #172554 深蓝

FONT_CANDIDATES = ["msyh.ttc", "msyhbd.ttc", "simhei.ttf", "Deng.ttf", "simsun.ttc"]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in FONT_CANDIDATES:
        path = Path(r"C:\Windows\Fonts") / name
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                continue
    return ImageFont.load_default()


def build() -> Path:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 竖向渐变底色
    for y in range(SIZE):
        ratio = y / (SIZE - 1)
        color = tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * ratio) for i in range(3))
        draw.line([(0, y), (SIZE, y)], fill=color + (255,))

    # 圆角遮罩
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1],
                                           radius=RADIUS, fill=255)
    img.putalpha(mask)

    # 中间一个「译」字
    font = _font(158)
    draw.text((SIZE // 2, SIZE // 2 - 6), "译", font=font, fill=(255, 255, 255, 255),
              anchor="mm")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="ICO",
             sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    return OUT


def main() -> int:
    path = build()
    size = path.stat().st_size
    print(f"图标已生成: {path}  ({size} 字节)")
    print("包含尺寸: 256 / 128 / 64 / 48 / 32 / 16")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
