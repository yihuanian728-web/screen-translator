#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""划词翻译的端到端测试 —— 合成一次真实的鼠标拖拽，看程序会不会自动翻译。

流程：
    1. 起一个记事本，写进已知的英文，挪到指定位置
    2. 起翻译器主界面（自动划词已打开），挪到不挡路的地方
    3. 用 SendInput 合成「按下左键 -> 拖动 -> 松开」的一整套动作
    4. 等几秒，检查主界面的历史记录里是不是出现了正确的译文

这是唯一能验证「鼠标钩子 -> 读选区 -> 翻译 -> 弹窗」全链路的方法。
运行期间鼠标指针会被程序挪动一两秒，属正常现象。

    python -m tools.selection_e2e
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from st_core.capture import enable_dpi_awareness      # noqa: E402
from st_core.config import Config                     # noqa: E402
from st_core.console import setup_console             # noqa: E402

user32 = ctypes.windll.user32
EN_TEXT = "The quick brown fox jumps over the lazy dog."
FILE_NAME = "st_selection_e2e.txt"

NOTEPAD_POS = (200, 200, 1200, 620)
APP_POS = (1560, 900)


def _set_window_pos(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    user32.SetWindowPos(ctypes.c_void_p(hwnd), None, x, y, w, h, 0x0040)


def _find_notepad(timeout: float = 15.0):
    import uiautomation as auto

    deadline = time.time() + timeout
    while time.time() < deadline:
        for win in auto.GetRootControl().GetChildren():
            try:
                if FILE_NAME in (win.Name or ""):
                    return win
            except Exception:
                continue
        time.sleep(0.3)
    return None


def _synth_drag(x1: int, y1: int, x2: int, y2: int, steps: int = 12) -> None:
    """合成一次鼠标拖拽。要够长、够慢，才会被鼠标钩子判定成「划词」。"""
    user32.SetCursorPos(x1, y1)
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)          # LEFTDOWN
    time.sleep(0.08)
    for i in range(1, steps + 1):
        user32.SetCursorPos(x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps)
        time.sleep(0.03)
    time.sleep(0.08)
    user32.mouse_event(0x0004, 0, 0, 0, 0)          # LEFTUP


def main(argv: list[str] | None = None) -> int:
    setup_console()
    print("=" * 62)
    print("划词翻译端到端测试（会合成真实鼠标拖拽）")
    print("=" * 62)

    enable_dpi_awareness()
    tmp = Path(tempfile.gettempdir()) / FILE_NAME
    tmp.write_text(EN_TEXT, encoding="utf-8")
    proc = subprocess.Popen(["notepad.exe", str(tmp)])
    win = _find_notepad()
    if win is None:
        print("[失败] 记事本没起来")
        proc.terminate()
        return 1

    hwnd = int(win.NativeWindowHandle)
    _set_window_pos(hwnd, *NOTEPAD_POS)
    time.sleep(0.6)
    win.SetActive()
    time.sleep(0.5)

    # 找到记事本的文本区域，算出要拖的坐标
    import uiautomation as auto

    doc = win.DocumentControl(searchDepth=6)
    rect = doc.BoundingRectangle
    x1, y1 = rect.left + 8, rect.top + 12
    x2 = min(rect.left + rect.width() - 20, x1 + 700)
    print(f"\n记事本窗口 {NOTEPAD_POS}，文本区 {rect}，将拖拽 ({x1},{y1}) -> ({x2},{y1})")

    # 起翻译器主界面
    from st_core.ui import TranslatorApp

    root = tk.Tk()
    root.geometry(f"900x600+{APP_POS[0]}+{APP_POS[1]}")
    app = TranslatorApp(root, Config.load())
    app.var_auto.set(True)
    app._apply_auto_select()
    for _ in range(20):
        root.update()
        time.sleep(0.03)
    print(f"自动划词: {'开' if app.mouse_on else '关'}  鼠标钩子: {app.mouse.error or '已注册'}")

    win.SetActive()
    time.sleep(0.4)

    print("\n>>> 合成鼠标拖拽（选中记事本里的第一行文字）")
    _synth_drag(x1, y1, x2, y1)

    print(">>> 等待钩子触发 + 翻译 ...")
    deadline = time.time() + 12
    while time.time() < deadline:
        root.update()
        time.sleep(0.05)
        if app.history:
            break

    ok = False
    if app.history:
        item = app.history[0]
        got = "".join(item.get("source_text", "").split())
        want = "".join(EN_TEXT.split())
        same = want in got
        print(f"\n  读到的原文: {item.get('source_text', '')!r}")
        print(f"  译文      : {item.get('target_text', '')!r}")
        print(f"  翻译源    : {item.get('provider')} / 方向 {item.get('direction')}")
        print(f"  [{'通过' if same else '失败'}] 钩子读到的确实是选中的那句英文")
        ok = same and bool(item.get("target_text"))
    else:
        print("\n  [失败] 历史记录是空的 —— 鼠标钩子没有触发翻译")
        print(f"  钩子状态: {app.mouse.error or '已注册'}，自动划词={app.var_auto.get()}")
        print(f"  状态栏: {app.status.get()}")

    try:
        root.destroy()
    except Exception:
        pass
    try:
        win.GetWindowPattern().Close()
    except Exception:
        proc.terminate()
    time.sleep(0.3)

    print("\n" + "=" * 62)
    print("划词端到端测试：" + ("通过" if ok else "有失败项"))
    print("=" * 62)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
