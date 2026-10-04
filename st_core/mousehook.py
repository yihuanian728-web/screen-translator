"""低级鼠标钩子：检测「按住左键拖出一段距离后松开」= 用户刚划完词。

用 SetWindowsHookEx(WH_MOUSE_LL) 实现。注意几点：
* 钩子回调必须极快，否则会拖慢整个系统的鼠标响应，所以这里只记录坐标、往队列里丢事件。
* 回调所在的线程必须有消息循环，否则收不到事件 —— 和全局热键一样单开一个线程跑 GetMessage。
* 回调参数结构体必须按 MSLLHOOKSTRUCT 定义，写错会读到垃圾数据。
"""

from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_QUIT = 0x0012


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


# 【坑】64 位下句柄是 8 字节，不声明 restype 的话 ctypes 默认按 c_int（4 字节）截断，
# SetWindowsHookEx 就会拿着一个残缺的 HMODULE 去注册，报错 126（找不到模块）。
kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
kernel32.GetModuleHandleW.restype = ctypes.c_void_p
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t


class MouseHook:
    """监听全局鼠标，划词结束时把 (起点, 终点) 丢进队列。

    用法：
        hook = MouseHook(min_distance=12)
        hook.start()
        ...
        for (x1, y1, x2, y2) in hook.poll():
            print("用户刚划完一段", (x1, y1), (x2, y2))
    """

    def __init__(self, min_distance: int = 12, min_duration_ms: int = 60):
        self.min_distance = min_distance
        self.min_duration_ms = min_duration_ms
        self._queue: "queue.Queue[tuple[int, int, int, int]]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._ready = threading.Event()
        self._hook = None
        self._proc = None          # 必须保住引用，否则回调会被回收 -> 崩溃
        self.error = ""

        self._down: tuple[int, int, int] | None = None      # (x, y, tick)
        self._moved = 0

    # ------------------------------------------------------------ 生命周期
    def start(self) -> bool:
        if self._thread is not None:
            return True
        self._thread = threading.Thread(target=self._run, name="mousehook", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3)
        return not self.error

    def stop(self) -> None:
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        self._thread = None

    def poll(self) -> list[tuple[int, int, int, int]]:
        out = []
        while True:
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                return out

    # ------------------------------------------------------------ 线程
    def _run(self) -> None:
        self._tid = kernel32.GetCurrentThreadId()
        self._proc = HOOKPROC(self._callback)
        # 低级鼠标钩子不需要注入 DLL，hMod 传当前模块句柄或 NULL 都行
        hmod = kernel32.GetModuleHandleW(None)
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, hmod, 0)
        if not self._hook:
            self.error = f"鼠标钩子注册失败（错误码 {ctypes.get_last_error()}）"
            self._ready.set()
            return
        self._ready.set()

        msg = MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret in (0, -1):
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    # ------------------------------------------------------------ 回调
    def _callback(self, n_code, w_param, l_param):
        if n_code >= 0:
            try:
                info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                x, y = int(info.pt.x), int(info.pt.y)
                if w_param == WM_LBUTTONDOWN:
                    self._down = (x, y, info.time)
                    self._moved = 0
                elif w_param == WM_MOUSEMOVE and self._down is not None:
                    dx = abs(x - self._down[0])
                    dy = abs(y - self._down[1])
                    self._moved = max(self._moved, dx + dy)
                elif w_param == WM_LBUTTONUP and self._down is not None:
                    x0, y0, t0 = self._down
                    duration = int(info.time) - int(t0)
                    distance = abs(x - x0) + abs(y - y0)
                    self._down = None
                    if (distance >= self.min_distance and duration >= self.min_duration_ms):
                        # 判定为「划词」而不是「点一下」或「拖窗口」
                        self._queue.put((x0, y0, x, y))
                elif w_param == WM_RBUTTONDOWN:
                    self._down = None
            except Exception:
                pass
        return user32.CallNextHookEx(None, n_code, w_param, l_param)


def cursor_pos() -> tuple[int, int]:
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)
