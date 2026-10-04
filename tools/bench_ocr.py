#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OCR 引擎对比脚本：同一张图，不同引擎 / 不同缩放倍数，谁的识别结果更准。

用来决定「自动放大倍数」该取多少 —— 屏幕上的小字放大后通常更好认，
但放太大反而会让文字检测器误判。

    python -m tools.bench_ocr
    python -m tools.bench_ocr --sizes 12,16,26 --scales 1.0,2.0,3.0
"""

from __future__ import annotations

import argparse
import difflib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image                                    # noqa: E402
from st_core import ocr as ocr_mod                       # noqa: E402
from st_core.console import setup_console                # noqa: E402
from tools.selftest import EN_SAMPLE, ZH_SAMPLE, make_sample   # noqa: E402

OUT_DIR = ROOT / "_selftest"


def similarity(a: str, b: str) -> float:
    norm = lambda s: "".join(s.split()).lower()          # noqa: E731
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def main() -> int:
    setup_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="14,20,26", help="字号，逗号分隔")
    ap.add_argument("--scales", default="1.0,2.0,3.0", help="放大倍数，逗号分隔")
    ap.add_argument("--engines", default="windows,rapidocr")
    args = ap.parse_args()

    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    scales = [float(s) for s in args.scales.split(",") if s.strip()]
    engines = [s.strip() for s in args.engines.split(",") if s.strip()]

    usable = ocr_mod.available_engines()
    print("可用引擎:", {k: v for k, v in usable.items()})
    print("Windows OCR 语言:", ocr_mod.windows_ocr_languages())
    print(f"zh 模型: {ocr_mod.windows_ocr_language_for('zh')}  "
          f"en 模型: {ocr_mod.windows_ocr_language_for('en')}")
    print()

    # 预热，免得把模型加载时间算进第一行
    for engine in engines:
        if not usable.get(engine):
            continue
        try:
            ocr_mod.recognize(make_sample("warm up", False, OUT_DIR / "_warm.png", 20),
                              engine=engine, scale=1.0)
        except Exception:
            pass

    for size in sizes:
        for label, text, zh in (("英文", EN_SAMPLE, False), ("中文", ZH_SAMPLE, True)):
            path = make_sample(text, zh, OUT_DIR / f"bench_{'zh' if zh else 'en'}_{size}.png", size)
            img = Image.open(path)
            print("=" * 78)
            print(f"[{label} 字号{size}] 图片 {img.width}x{img.height}  期望：{text}")
            for engine in engines:
                if not usable.get(engine):
                    print(f"  {engine:<9} 未安装，跳过")
                    continue
                for scale in scales:
                    try:
                        t0 = time.time()
                        res = ocr_mod.recognize(img, engine=engine, scale=scale)
                        ms = (time.time() - t0) * 1000
                        print(f"  {engine:<9} scale={scale:<4} {ms:6.0f}ms  "
                              f"相似度 {similarity(res.text, text):.2f}  {res.text!r}")
                    except Exception as exc:
                        print(f"  {engine:<9} scale={scale:<4} 失败: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
