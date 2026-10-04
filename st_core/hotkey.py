"""全局快捷键：直接用 Win32 的 RegisterHotKey，不依赖第三方库。

原理：RegisterHotKey 必须和消息循环在同一个线程里，所以这里单开一个后台线程
注册按键 + 跑 GetMessageW 循环，收到 WM_HOTKEY 就塞进队列，主界面定时取。
"""

from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x0008, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

_MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL,
         "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN, "super": MOD_WIN}

_KEYS = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20,
    "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "insert": 0x2D, "delete": 0x2E,
}


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


def parse_hotkey(spec: str) -> tuple[int, int]:
    """'ctrl+alt+z' -> (修饰键掩码, 虚拟键码)。解析失败抛 ValueError。"""
    parts = [p.strip().lower() for p in (spec or "").split("+") if p.strip()]
    if not parts:
        raise ValueError("快捷键为空")

    mods, key = 0, None
    for part in parts:
        if part in _MODS:
            mods |= _MODS[part]
            continue
        key = part

    if key is None:
        raise ValueError(f"快捷键 {spec!r} 里没有主键")
    if key in _KEYS:
        vk = _KEYS[key]
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    elif len(key) == 1:
        scan = user32.VkKeyScanW(ctypes.c_wchar(key))
        if scan == -1:
            raise ValueError(f"无法识别的按键：{key}")
        vk = scan & 0xFF
    else:
        raise ValueError(f"无法识别的按键：{key}")
    return mods, vk


class HotkeyManager:
    """注册若干个全局快捷键，事件通过 poll() 取。"""

    def __init__(self) -> None:
        self._bindings: dict[str, tuple[int, int]] = {}
        self._specs: dict[str, str] = {}
        self._ids: dict[str, int] = {}
        self._names: dict[int, str] = {}
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._tid: int = 0
        self._ready = threading.Event()
        self.errors: list[str] = []

    # ------------------------------------------------------------ 注册
    def add(self, name: str, spec: str) -> None:
        self._bindings[name] = parse_hotkey(spec)
        self._specs[name] = spec

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3)

    # ------------------------------------------------------------ 取事件
    def poll(self) -> list[str]:
        out = []
        while True:
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                return out

    # ------------------------------------------------------------ 线程
    def _run(self) -> None:
        self._tid = kernel32.GetCurrentThreadId()
        for index, (name, (mods, vk)) in enumerate(self._bindings.items(), start=1):
            hotkey_id = 0xA000 + index
            self._ids[name] = hotkey_id
            self._names[hotkey_id] = name
            if not user32.RegisterHotKey(None, hotkey_id, mods | MOD_NOREPEAT, vk):
                err = ctypes.get_last_error()
                self.errors.append(
                    f"快捷键 {self._specs.get(name, name)} 注册失败"
                    f"（错误码 {err}，可能被其它软件占用了，改 config.json 换一个）"
                )
                self._names.pop(hotkey_id, None)
        self._ready.set()

        msg = MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret in (0, -1):
                break
            if msg.message == WM_HOTKEY:
                name = self._names.get(int(msg.wParam))
                if name:
                    self._queue.put(name)

        for name, hotkey_id in self._ids.items():
            if hotkey_id in self._names:
                user32.UnregisterHotKey(None, hotkey_id)

    def stop(self) -> None:
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        self._thread = None
