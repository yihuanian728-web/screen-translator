#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""离线自测：不依赖屏幕和鼠标，验证「图片 -> OCR -> 翻译」整条链路。

    python -m tools.selftest            只测 OCR 和方向判断（不联网）
    python -m tools.selftest --online   额外实测每个翻译接口
    python main.py --selftest-online    等价写法
"""

from __future__ import annotations

import argparse
import difflib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont      # noqa: E402

from st_core import ocr as ocr_mod, pipeline, translator as tr_mod   # noqa: E402
from st_core.capture import enable_dpi_awareness  # noqa: E402
from st_core.config import Config                 # noqa: E402
from st_core.console import setup_console         # noqa: E402

OUT_DIR = ROOT / "_selftest"

EN_SAMPLE = "The quick brown fox jumps over the lazy dog."
ZH_SAMPLE = "今天天气很好，我们一起去公园散步吧。"

FONT_CANDIDATES_EN = ["segoeui.ttf", "arial.ttf", "calibri.ttf", "msyh.ttc"]
FONT_CANDIDATES_ZH = ["msyh.ttc", "msyhl.ttc", "simhei.ttf", "simsun.ttc", "Deng.ttf"]


def _font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    fonts_dir = Path(r"C:\Windows\Fonts")
    for name in names:
        path = fonts_dir / name
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                continue
    return ImageFont.load_default()


def make_sample(text: str, zh: bool, path: Path, size: int = 26) -> Path:
    """把一段文字画成白底黑字的图片，模拟截图。"""
    font = _font(FONT_CANDIDATES_ZH if zh else FONT_CANDIDATES_EN, size)
    pad = 18
    tmp = Image.new("RGB", (10, 10), "white")
    d = ImageDraw.Draw(tmp)
    bbox = d.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    img = Image.new("RGB", (w + pad * 2, h + pad * 2), "white")
    ImageDraw.Draw(img).text((pad - bbox[0], pad - bbox[1]), text, fill="#101010", font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def _ratio(a: str, b: str) -> float:
    norm = lambda s: "".join(s.split()).lower()          # noqa: E731
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def _check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'通过' if ok else '失败'}] {name}{('  ' + detail) if detail else ''}")
    return ok


def run_selftest(cfg: Config | None = None, online: bool = False) -> int:
    cfg = cfg or Config()
    print("=" * 62)
    print("屏幕翻译器 自测")
    print("=" * 62)
    enable_dpi_awareness()

    ok_all = True

    # ---------------------------------------------------------- 环境
    print("\n[1/5] 环境")
    usable = ocr_mod.available_engines()
    print(f"  可用 OCR 引擎: {[k for k, v in usable.items() if v] or '无'}")
    langs = ocr_mod.windows_ocr_languages()
    print(f"  Windows OCR 语言: {langs or '无'}")
    try:
        api = ocr_mod._load_winrt()
        print(f"  WinRT 绑定: {api['root']}（阻塞式 .get() 可用）")
    except Exception as exc:
        print(f"  WinRT 绑定: 不可用 -> {exc}")
    try:
        engine = ocr_mod.choose_engine(cfg["ocr_engine"])
        ok_all &= _check("存在可用的 OCR 引擎", True, f"默认使用 {engine}")
    except Exception as exc:
        ok_all &= _check("存在可用的 OCR 引擎", False, str(exc))
        return 1

    # ---------------------------------------------------------- 样图
    print("\n[2/5] 生成样图")
    en_img = OUT_DIR / "sample_en.png"
    zh_img = OUT_DIR / "sample_zh.png"
    make_sample(EN_SAMPLE, False, en_img)
    make_sample(ZH_SAMPLE, True, zh_img)
    print(f"  {en_img}")
    print(f"  {zh_img}")

    # ---------------------------------------------------------- 英文 OCR
    print("\n[3/5] 英文截图 -> 识别 -> 中译")
    t0 = time.time()
    try:
        res_en = ocr_mod.recognize(Image.open(en_img), lang_hint="en", engine=cfg["ocr_engine"])
        print(f"  识别结果：{res_en.text!r}  ({res_en.engine}/{res_en.lang}, "
              f"{(time.time() - t0) * 1000:.0f}ms)")
        for note in res_en.notes:
            print(f"  ! {note}")
        ok_all &= _check("英文 OCR 内容正确", _ratio(res_en.text, EN_SAMPLE) > 0.9,
                         f"相似度 {_ratio(res_en.text, EN_SAMPLE):.2f}")
        ok_all &= _check("方向判断为英译中", tr_mod.detect_direction(res_en.text) == "en2zh")
    except Exception as exc:
        ok_all &= _check("英文 OCR", False, f"{type(exc).__name__}: {exc}")
        res_en = None

    # ---------------------------------------------------------- 中文 OCR
    print("\n[4/5] 中文截图 -> 识别 -> 英译")
    t0 = time.time()
    try:
        res_zh = ocr_mod.recognize(Image.open(zh_img), lang_hint="zh", engine=cfg["ocr_engine"])
        print(f"  识别结果：{res_zh.text!r}  ({res_zh.engine}/{res_zh.lang}, "
              f"{(time.time() - t0) * 1000:.0f}ms)")
        for note in res_zh.notes:
            print(f"  ! {note}")
        ok_all &= _check("中文 OCR 内容正确", _ratio(res_zh.text, ZH_SAMPLE) > 0.9,
                         f"相似度 {_ratio(res_zh.text, ZH_SAMPLE):.2f}")
        ok_all &= _check("方向判断为中译英", tr_mod.detect_direction(res_zh.text) == "zh2en")
    except Exception as exc:
        ok_all &= _check("中文 OCR", False, f"{type(exc).__name__}: {exc}")
        res_zh = None

    # ---------------------------------------------------------- 自动模式
    print("\n[5/5] 自动语言判断 + 翻译")
    try:
        auto_en = ocr_mod.recognize(Image.open(en_img), engine=cfg["ocr_engine"])
        auto_zh = ocr_mod.recognize(Image.open(zh_img), engine=cfg["ocr_engine"])
        print(f"  英文图 auto 模式: {auto_en.lang} -> {auto_en.text[:40]!r}")
        print(f"  中文图 auto 模式: {auto_zh.lang} -> {auto_zh.text[:40]!r}")
        ok_all &= _check("auto 模式能识别两种语言",
                         _ratio(auto_en.text, EN_SAMPLE) > 0.8 and _ratio(auto_zh.text, ZH_SAMPLE) > 0.8)
    except Exception as exc:
        ok_all &= _check("auto 模式", False, f"{type(exc).__name__}: {exc}")

    print("\n  --- 翻译链路 ---")
    if online:
        probes = [(EN_SAMPLE, "auto"), (ZH_SAMPLE, "auto")]
        for provider in ("deepseek", "bing", "google", "youdao", "mymemory"):
            for text, direction in probes:
                t0 = time.time()
                try:
                    out = tr_mod.translate(text, direction=direction, provider=provider, cfg={})
                    print(f"  [通过] {provider:<9} {out.src}->{out.tgt} "
                          f"{(time.time() - t0) * 1000:.0f}ms: {out.text[:44]}")
                except Exception as exc:
                    print(f"  [跳过] {provider:<9} {str(exc).splitlines()[0][:70]}")
    else:
        # 不联网时至少验证分段、方向、错误处理
        chunks = tr_mod._split_text("a" * 50 + "。" + "b" * 50, 40)
        ok_all &= _check("长文本自动分段", len(chunks) >= 3, f"{len(chunks)} 段")
        try:
            tr_mod.translate("   ", direction="auto", provider="bing", cfg={})
            ok_all &= _check("空文本会报错", False)
        except Exception:
            ok_all &= _check("空文本会报错", True)
        print("  （加 --online 可以实测各个翻译接口）")

    print("\n" + "=" * 62)
    print("自测结果：" + ("全部通过" if ok_all else "有失败项"))
    print("=" * 62)
    return 0 if ok_all else 1


def main() -> int:
    setup_console()
    ap = argparse.ArgumentParser(description="屏幕翻译器自测")
    ap.add_argument("--online", action="store_true", help="额外实测各个翻译接口")
    ap.add_argument("--direction", default=None)
    args = ap.parse_args()
    cfg = Config()
    if args.direction:
        cfg.data["direction"] = args.direction
    return run_selftest(cfg, online=args.online)


if __name__ == "__main__":
    raise SystemExit(main())
