#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""屏幕翻译器 —— 程序入口。

常用命令：
    python main.py                     启动图形界面
    python main.py --doctor            环境自检（OCR 语言、翻译接口连通性）
    python main.py --selftest          离线自测（生成样图 -> OCR -> 翻译）
    python main.py --text "hello"      命令行直接翻译一段文字
    python main.py --image shot.png    识别并翻译一张图片
    python main.py --ocr-only shot.png 只识别不翻译
    python main.py --pick              手动框选一次并打印结果（不开主界面）
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from st_core import pipeline                      # noqa: E402
from st_core.config import Config                 # noqa: E402
from st_core.console import setup_console         # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="屏幕翻译器",
        description="框选屏幕任意区域，自动识别文字并做英中 / 中英互译",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--doctor", action="store_true", help="环境自检")
    p.add_argument("--selftest", action="store_true", help="运行离线自测")
    p.add_argument("--selftest-online", action="store_true", help="自测并额外测试所有翻译接口")
    p.add_argument("--e2e", action="store_true", help="端到端测试（真开窗口真截图）")
    p.add_argument("--smoke", action="store_true", help="界面冒烟测试（开一下界面就退出）")
    p.add_argument("--pick", action="store_true", help="只做一次框选识别（不开主界面）")
    p.add_argument("--selection", action="store_true",
                   help="读取当前鼠标选中的文字并翻译（划词翻译的命令行版）")
    p.add_argument("--selection-test", action="store_true", help="测试划词读取链路（会开一下记事本）")
    p.add_argument("--selection-e2e", action="store_true",
                   help="划词端到端测试：合成真实鼠标拖拽，验证自动翻译")
    p.add_argument("--text", metavar="TEXT", help="直接翻译这段文字")
    p.add_argument("--image", metavar="PATH", help="翻译这张图片里的文字")
    p.add_argument("--ocr-only", action="store_true", help="配合 --image：只识别，不翻译")
    p.add_argument("--direction", choices=["auto", "en2zh", "zh2en"], help="翻译方向")
    p.add_argument("--provider", help="指定翻译源：bing / google / youdao / mymemory / deepseek / argos")
    p.add_argument("--engine", help="指定 OCR 引擎：auto / windows / rapidocr / tesseract")
    p.add_argument("--no-online", action="store_true", help="自检时不测试网络翻译接口")
    p.add_argument("--version", action="version", version="屏幕翻译器 1.0.0")
    return p


def apply_overrides(cfg: Config, args: argparse.Namespace) -> Config:
    if args.direction:
        cfg.data["direction"] = args.direction
    if args.provider:
        cfg.data["translator"] = args.provider
    if args.engine:
        cfg.data["ocr_engine"] = args.engine
    return cfg


def raise_existing_window() -> bool:
    """如果程序已经在跑，就把它的窗口切到前台，不要再开一个。"""
    import ctypes

    from st_core.ui import WINDOW_TITLE

    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.FindWindowW.restype = ctypes.c_void_p
    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd:
        return False
    user32.ShowWindow(ctypes.c_void_p(hwnd), 9)          # SW_RESTORE
    user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
    return True


def smoke_test(cfg: Config) -> int:
    """界面冒烟测试：把主界面、译文浮窗、设置窗口都建一遍，跑两秒事件循环再退出。

    能查出「窗口能建起来吗、快捷键注册上了吗、控件有没有写错」这类问题，
    而不用人工点一遍。
    """
    import time
    import tkinter as tk

    from st_core.capture import Rect, enable_dpi_awareness
    from st_core.ui import SettingsDialog, TranslatorApp

    enable_dpi_awareness()
    root = tk.Tk()
    app = TranslatorApp(root, cfg)
    deadline = time.time() + 2.0
    while time.time() < deadline:
        root.update()
        time.sleep(0.03)

    print("主窗口        : 成功")
    print("标题          :", root.title())
    print("窗口尺寸      :", root.winfo_geometry())
    print("快捷键错误    :", app.hotkeys.errors or "无")
    print("状态栏        :", app.status.get())
    print("鼠标钩子      :", "已启动" if app.mouse_on else f"未启动 {app.mouse.error}")
    print("自动划词      :", "开" if app.var_auto.get() else "关")

    app.popup.show("这是一条测试译文。", Rect(120, 120, 520, 220), "smoke · rapidocr · 12ms")
    for _ in range(20):
        root.update()
        time.sleep(0.03)
    print("译文浮窗      :", "成功" if app.popup.top is not None else "失败")
    app.popup.hide()

    dlg = SettingsDialog(root, cfg)
    for _ in range(10):
        root.update()
        time.sleep(0.02)
    print("设置窗口      : 成功")
    dlg.top.destroy()

    root.destroy()
    print("界面冒烟测试  : 通过")
    return 0


def main(argv: list[str] | None = None) -> int:
    setup_console()
    args = build_parser().parse_args(argv)
    cfg = apply_overrides(Config.load(), args)

    if args.doctor:
        print(pipeline.doctor(cfg.data, test_translate=not args.no_online))
        return 0

    if args.selftest or args.selftest_online:
        from tools.selftest import run_selftest

        return run_selftest(cfg, online=args.selftest_online)

    if args.e2e:
        from tools.e2e_test import main as e2e_main

        return e2e_main([])

    if args.selection_test:
        from tools.selection_test import main as sel_main

        return sel_main([])

    if args.selection_e2e:
        from tools.selection_e2e import main as sel_e2e

        return sel_e2e([])

    if args.selection:
        from st_core import selection as sel_mod

        text, source = sel_mod.get_selected_text(
            cfg["selection_mode"], bool(cfg["selection_copy_fallback"]))
        if not (text or "").strip():
            print("没有读到选中的文字。请先用鼠标在别的程序里选中一段文字，再运行这条命令。",
                  file=sys.stderr)
            print(f"（UIA 版本 {sel_mod.uia_version()}，可用={sel_mod.uia_available()}）", file=sys.stderr)
            return 1
        print(f"[来源 {source}，{len(text)} 字符]", file=sys.stderr)
        job = pipeline.run_text(text, cfg.data, kind="selection")
        if job.error:
            print("失败：" + job.error, file=sys.stderr)
            return 1
        print("原文：\n" + job.source_text)
        print("\n译文：\n" + job.target_text)
        print(f"\n[{job.provider} · {job.direction}]", file=sys.stderr)
        return 0

    if args.smoke:
        return smoke_test(cfg)

    if args.text:
        job = pipeline.run_text(args.text, cfg.data, kind="manual")
        if job.error:
            print("失败：" + job.error, file=sys.stderr)
            return 1
        print(job.target_text)
        print(f"\n[{job.provider} · {job.direction}]", file=sys.stderr)
        return 0

    if args.image:
        from PIL import Image

        path = Path(args.image)
        if not path.exists():
            print(f"找不到图片：{path}", file=sys.stderr)
            return 2
        img = Image.open(path)
        if args.ocr_only:
            from st_core.ocr import recognize

            result = recognize(img, engine=cfg["ocr_engine"])
            print(result.text)
            print(f"\n[engine={result.engine} lang={result.lang}]", file=sys.stderr)
            return 0
        job = pipeline.run_region(None, cfg.data, image=img)  # type: ignore[arg-type]
        if job.error:
            print("失败：" + job.error, file=sys.stderr)
            return 1
        print("原文：\n" + job.source_text)
        print("\n译文：\n" + job.target_text)
        print(f"\n[{job.provider} · {job.ocr_engine}]", file=sys.stderr)
        return 0

    if args.pick:
        import tkinter as tk

        from st_core.capture import enable_dpi_awareness
        from st_core.overlay import RegionSelector

        enable_dpi_awareness()
        root = tk.Tk()
        root.withdraw()
        rect = RegionSelector(root).select()
        root.destroy()
        if rect is None:
            print("已取消")
            return 1
        job = pipeline.run_region(rect, cfg.data)
        if job.error:
            print("失败：" + job.error, file=sys.stderr)
            return 1
        print("原文：\n" + job.source_text)
        print("\n译文：\n" + job.target_text)
        return 0

    # 默认：图形界面
    try:
        import tkinter  # noqa: F401
    except Exception:
        print("当前 Python 没有 tkinter，无法启动界面。", file=sys.stderr)
        return 3
    if raise_existing_window():
        print("程序已经在运行了，已把窗口切到前台。")
        return 0
    from st_core.ui import run

    run(cfg)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main())
