#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""真正的端到端测试：开一个已知位置的窗口 -> 截取那个区域 -> OCR -> 翻译。

这一步会验证三件事，而这些是单元测试查不出来的：
    1. 屏幕截图抓到的坐标是不是真的对准了目标区域（DPI 缩放最容易在这里翻车）
    2. 截图里的文字能不能被 OCR 正确认出来
    3. 识别结果能不能翻译回来

运行时屏幕上会闪过一个小窗口，大约 3 秒。

    python -m tools.e2e_test
    python -m tools.e2e_test --keep     保留截图文件方便肉眼检查
"""

from __future__ import annotations

import argparse
import difflib
import sys
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from st_core import capture, pipeline                     # noqa: E402
from st_core.capture import Rect, enable_dpi_awareness     # noqa: E402
from st_core.config import Config                          # noqa: E402
from st_core.console import setup_console                  # noqa: E402

OUT_DIR = ROOT / "_selftest"

EN_TEXT = "Screen region translation works."
ZH_TEXT = "框选屏幕区域就能翻译"

WIN_X, WIN_Y, WIN_W, WIN_H = 260, 240, 760, 130


def similarity(a: str, b: str) -> float:
    norm = lambda s: "".join(s.split()).lower()            # noqa: E731
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def show_window(text: str, font: tuple, zh: bool) -> tk.Tk:
    """在固定位置显示无边框窗口，内容就是待识别的文字。"""
    root = tk.Tk()
    root.overrideredirect(True)                # 去掉标题栏，客户区坐标才等于窗口坐标
    root.geometry(f"{WIN_W}x{WIN_H}+{WIN_X}+{WIN_Y}")
    root.configure(bg="white")
    root.attributes("-topmost", True)
    label = tk.Label(root, text=text, font=font, bg="white", fg="#101010",
                     wraplength=WIN_W - 40, justify="center")
    label.pack(fill="both", expand=True)
    root.update()
    time.sleep(0.7)                            # 等系统真的把窗口画到屏幕上
    return root


def check_case(label: str, text: str, font: tuple, zh: bool, cfg: Config,
               direction: str, keep: bool = False) -> bool:
    rect = Rect(WIN_X, WIN_Y, WIN_X + WIN_W, WIN_Y + WIN_H)
    root = show_window(text, font, zh)
    try:
        # 1) 单纯验证截图坐标对不对：我们截图后自己看一眼
        shot = capture.grab(rect)
        if keep:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            shot.save(OUT_DIR / f"e2e_{direction}.png")

        # 2) 走完整流程（内部会重新截图）
        cfg.data["direction"] = direction
        job = pipeline.run_region(rect, cfg.data)
    finally:
        root.destroy()
        time.sleep(0.2)

    print(f"\n--- {label} ---")
    print(f"  截图尺寸   : {shot.width}x{shot.height}")
    if job.error:
        print(f"  [失败] {job.error}")
        return False

    print(f"  识别结果   : {job.source_text!r}  ({job.ocr_engine}/{job.ocr_lang}, "
          f"{job.timings.get('ocr', 0) * 1000:.0f}ms)")
    for note in job.notes:
        print(f"  ! {note}")
    ratio = similarity(job.source_text, text)
    print(f"  与期望相似度: {ratio:.2f}")
    print(f"  译文       : {job.target_text!r}  ({job.provider}, "
          f"{job.timings.get('translate', 0) * 1000:.0f}ms)")

    ok = ratio > 0.8 and bool(job.target_text)
    print("  [通过]" if ok else "  [失败]")
    return ok


def test_selector() -> bool:
    """用合成鼠标事件驱动框选遮罩，验证拖出来的矩形坐标是对的。

    真实使用中是用户拿鼠标拖，这里用 event_generate 模拟按下 -> 拖动 -> 松开。
    """
    from st_core.overlay import RegionSelector

    vs = capture.virtual_screen()
    start, end = (120, 90), (500, 300)
    expect = Rect(vs.left + start[0], vs.top + start[1], vs.left + end[0], vs.top + end[1])

    root = tk.Tk()
    root.withdraw()

    def drive() -> None:
        tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        if not tops:
            print("  [失败] 遮罩窗口没建起来")
            return
        canvas = tops[0].winfo_children()[0]
        for event, x, y in (("<Button-1>", start[0], start[1]),
                            ("<B1-Motion>", end[0], end[1]),
                            ("<ButtonRelease-1>", end[0], end[1])):
            canvas.event_generate(event, x=x, y=y,
                                  rootx=vs.left + x, rooty=vs.top + y)

    root.after(500, drive)
    rect = RegionSelector(root).select()
    root.destroy()

    print(f"\n--- 框选遮罩 ---")
    print(f"  模拟拖拽     : {start} -> {end}")
    print(f"  期望矩形     : {expect.as_bbox()}")
    print(f"  实际矩形     : {rect.as_bbox() if rect else None}")
    ok = rect is not None and rect.as_bbox() == expect.as_bbox()
    print("  [通过]" if ok else "  [失败]")
    return ok


def main(argv: list[str] | None = None) -> int:
    setup_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="保留截图")
    ap.add_argument("--no-translate", action="store_true", help="只测截图+识别，不联网翻译")
    ap.add_argument("--skip-selector", action="store_true")
    args = ap.parse_args(argv)

    print("=" * 62)
    print("端到端测试：真实窗口 -> 真实截图 -> 识别 -> 翻译")
    print("=" * 62)

    enable_dpi_awareness()
    vs = capture.virtual_screen()
    print(f"虚拟桌面 {vs.width}x{vs.height}，测试窗口放在 ({WIN_X},{WIN_Y}) "
          f"{WIN_W}x{WIN_H}")
    if WIN_X + WIN_W > vs.width or WIN_Y + WIN_H > vs.height:
        print("[失败] 测试窗口超出屏幕范围")
        return 1

    cfg = Config()
    if args.no_translate:
        cfg.data["translator"] = "youdao"

    ok = True
    if not args.skip_selector:
        ok &= test_selector()
    ok &= check_case("英文截图 -> 中文", EN_TEXT, ("Arial", 22), False, cfg, "en2zh", args.keep)
    if not args.no_translate:
        ok &= check_case("中文截图 -> 英文", ZH_TEXT, ("Microsoft YaHei UI", 22), True,
                         cfg, "zh2en", args.keep)

    print("\n" + "=" * 62)
    print("端到端测试：" + ("通过" if ok else "有失败项"))
    print("=" * 62)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
