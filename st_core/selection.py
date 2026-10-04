"""读取「用户当前选中的文字」—— 划词翻译的核心。

两条路：

1. UIA（UI Automation，首选）
   直接问系统：当前焦点控件里选中的是什么文字。这是「只读」操作，
   不碰剪贴板、不模拟按键，所以在资源管理器里拖选文件也不会误触发复制。

2. 剪贴板（兜底）
   模拟 Ctrl+C 再读剪贴板，之后把剪贴板内容恢复回去。
   兼容性最好（连不支持 UIA 的老程序也能用），但会短暂占用剪贴板，
   所以默认只在 UIA 读不到、且用户明确允许时才用。

实测：
    Chrome / Edge / Word / 记事本 / VS Code  -> UIA 可用
    部分 PDF 阅读器、老 Win32 程序             -> 需要走剪贴板兜底
    tkinter 自己的窗口                         -> 不支持 UIA，读不到
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

_user32 = ctypes.windll.user32

# 剪贴板里超过这个长度就不当「划词」处理了
MAX_SELECTION_CHARS = 5000


class SelectionError(RuntimeError):
    pass


# ==========================================================================
# UIA
# ==========================================================================
def uia_available() -> bool:
    try:
        import uiautomation  # noqa: F401
        return True
    except Exception:
        return False


def uia_version() -> str:
    try:
        import uiautomation as auto
        return getattr(auto, "VERSION", "?")
    except Exception:
        return "未安装"


def _from_uia() -> str:
    """用 UI Automation 读当前控件里选中的文字。读不到返回空串。"""
    import uiautomation as auto

    control = auto.GetFocusedControl()
    if control is None:
        return ""
    # 焦点可能落在子控件上，往上找几层，谁有 TextPattern 就问谁
    node = control
    for _ in range(4):
        if node is None:
            break
        try:
            pattern = node.GetTextPattern()
        except Exception:
            pattern = None
        if pattern:
            try:
                ranges = pattern.GetSelection()
            except Exception:
                ranges = None
            if ranges:
                text = "\n".join(r.GetText(-1) for r in ranges if r)
                if text.strip():
                    return text
        try:
            node = node.GetParentControl()
        except Exception:
            break
    return ""


# ==========================================================================
# 剪贴板兜底
# ==========================================================================
def _clipboard_sequence() -> int:
    return int(_user32.GetClipboardSequenceNumber())


def _send_ctrl_c() -> None:
    """模拟按 Ctrl+C。用 SendInput 而不是 keybd_event，兼容性更好。"""
    import uiautomation as auto

    auto.SendKeys("{Ctrl}c", waitTime=0)


def _from_clipboard(timeout: float = 0.6) -> str:
    """模拟 Ctrl+C 读选区，读完把剪贴板恢复原样。"""
    import uiautomation as auto

    try:
        old = auto.GetClipboardText()
    except Exception:
        old = None

    before = _clipboard_sequence()
    _send_ctrl_c()

    deadline = time.time() + timeout
    while time.time() < deadline:
        if _clipboard_sequence() != before:      # 剪贴板变了 -> 复制成功
            break
        time.sleep(0.03)

    try:
        text = auto.GetClipboardText() or ""
    except Exception:
        text = ""

    if _clipboard_sequence() != before and old is not None:
        try:                                     # 还原剪贴板
            auto.SetClipboardText(old)
        except Exception:
            pass

    return text if _clipboard_sequence() != before or text else text


# ==========================================================================
# 统一入口
# ==========================================================================
def get_selected_text(mode: str = "uia", allow_copy: bool = False) -> tuple[str, str]:
    """读取当前选中的文字，返回 (文本, 来源)。

    mode:
        "uia"    只问 UIA（安全，不碰剪贴板）
        "copy"   只用剪贴板兜底
        "auto"   UIA 优先，读不到再走剪贴板
    allow_copy:
        是否允许使用剪贴板兜底。False 时即使 mode="auto" 也不会按 Ctrl+C。
    """
    if mode == "copy":
        text = _from_clipboard()
        return _clean(text), "clipboard"

    if uia_available():
        text = _from_uia()
        if text.strip():
            return _clean(text), "uia"

    if mode == "auto" and allow_copy:
        if foreground_process_name() in SKIP_COPY_PROCESSES:
            return "", ""                        # 文件管理器里不按 Ctrl+C
        text = _from_clipboard()
        return _clean(text), "clipboard"

    return "", ""


def _clean(text: str) -> str:
    """去掉首尾空白和零宽字符；太长直接截断。"""
    text = (text or "").replace("\u200b", "").replace("\ufeff", "")
    text = text.strip()
    if len(text) > MAX_SELECTION_CHARS:
        text = text[:MAX_SELECTION_CHARS]
    return text


def foreground_window_pid() -> int:
    """当前前台窗口属于哪个进程 —— 用来判断「是不是点到我们自己头上了」。"""
    hwnd = _user32.GetForegroundWindow()
    pid = ctypes.c_ulong()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


# 【安全阀】在资源管理器里拖选文件时，如果去模拟 Ctrl+C，就会把文件复制到剪贴板，
# 既吓人又危险。这些进程直接禁用复制兜底；UIA 本身读不到东西，所以什么都不会发生。
SKIP_COPY_PROCESSES = {"explorer.exe", "taskmgr.exe"}

_kernel32 = ctypes.windll.kernel32
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = ctypes.c_void_p
_kernel32.QueryFullProcessImageNameW.argtypes = [
    ctypes.c_void_p, wintypes.DWORD, ctypes.c_wchar_p, ctypes.POINTER(wintypes.DWORD)]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [ctypes.c_void_p]


def foreground_process_name() -> str:
    """前台程序的 exe 文件名（小写），拿不到返回空串。"""
    import os

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False,
                                   foreground_window_pid())
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
    finally:
        _kernel32.CloseHandle(handle)
    return ""
