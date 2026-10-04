#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试「读取鼠标选中的文字」这条链路。

思路：拿记事本当靶子 —— 把一段中英文写进临时文件、用记事本打开、全选，
然后分别用 UIA 和剪贴板两条路去读，看读回来的东西对不对。

    python -m tools.selection_test
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from st_core import selection as sel        # noqa: E402
from st_core.console import setup_console   # noqa: E402

EN_TEXT = "The quick brown fox jumps over the lazy dog."
ZH_TEXT = "今天天气很好，我们一起去公园散步吧。"
ALL_TEXT = EN_TEXT + "\n" + ZH_TEXT

FILE_NAME = "st_selection_test.txt"


def _find_notepad(timeout: float = 12.0):
    """等记事本窗口出现。Win11 的记事本是打包应用，不能靠 PID 找。"""
    import uiautomation as auto

    deadline = time.time() + timeout
    while time.time() < deadline:
        for win in auto.GetRootControl().GetChildren():
            try:
                name = win.Name or ""
            except Exception:
                continue
            if FILE_NAME in name:
                return win
        time.sleep(0.3)
    return None


def _check(label: str, got: str, expect: str) -> bool:
    got_n = "".join(got.split())
    ok = got_n and (got_n in "".join(expect.split()) or "".join(expect.split()) in got_n)
    print(f"  [{'通过' if ok else '失败'}] {label}")
    print(f"        读回内容：{got[:70]!r}")
    if not ok:
        print(f"        期望内容：{expect[:70]!r}")
    return bool(ok)


def main(argv: list[str] | None = None) -> int:
    setup_console()
    print("=" * 62)
    print("划词读取测试（靶子：记事本）")
    print("=" * 62)

    print(f"\n[1/4] UI Automation 可用性")
    print(f"  uiautomation 版本: {sel.uia_version()}")
    if not sel.uia_available():
        print("  [失败] 没装 uiautomation，请运行 install.bat")
        return 1
    print("  [通过] UIA 可用")

    # 准备靶子
    tmp = Path(tempfile.gettempdir()) / FILE_NAME
    tmp.write_text(ALL_TEXT, encoding="utf-8")
    print(f"\n[2/4] 打开记事本 {tmp}")
    import subprocess

    proc = subprocess.Popen(["notepad.exe", str(tmp)])
    win = _find_notepad()
    if win is None:
        print("  [失败] 没等到记事本窗口（可能被安全软件拦了）")
        proc.terminate()
        return 1
    print(f"  找到窗口：{win.Name!r}")

    ok = True
    try:
        win.SetActive()
        time.sleep(0.5)
        import uiautomation as auto

        auto.SendKeys("{Ctrl}a", waitTime=0.3)
        time.sleep(0.4)

        print("\n[3/4] 用 UIA 读选区（不碰剪贴板）")
        t0 = time.time()
        text, source = sel.get_selected_text("uia")
        print(f"  耗时 {(time.time() - t0) * 1000:.0f}ms，来源={source or '无'}")
        ok &= _check("UIA 读到选中的文字", text, ALL_TEXT)
    except Exception as exc:
        print(f"  [失败] UIA 流程异常：{type(exc).__name__}: {exc}")
        ok = False

    try:
        print("\n[4/4] 用剪贴板兜底读选区（会临时占用剪贴板，读完恢复）")
        import uiautomation as auto

        auto.SetClipboardText("原始剪贴板内容-请勿覆盖")
        time.sleep(0.2)
        t0 = time.time()
        text, source = sel.get_selected_text("copy")
        print(f"  耗时 {(time.time() - t0) * 1000:.0f}ms，来源={source}")
        ok &= _check("剪贴板兜底读到选中的文字", text, ALL_TEXT)
        restored = auto.GetClipboardText() or ""
        print(f"  [{'通过' if '原始剪贴板' in restored else '失败'}] 剪贴板已恢复：{restored[:40]!r}")
        ok &= "原始剪贴板" in restored
    except Exception as exc:
        print(f"  [失败] 剪贴板流程异常：{type(exc).__name__}: {exc}")
        ok = False
    finally:
        try:
            win.GetWindowPattern().Close()
        except Exception:
            proc.terminate()

    print("\n" + "=" * 62)
    print("划词读取测试：" + ("通过" if ok else "有失败项"))
    print("=" * 62)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
