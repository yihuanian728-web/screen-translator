"""屏幕截图相关工具：DPI 感知、虚拟桌面尺寸、区域抓图。"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

# ---------------------------------------------------------------- DPI
_dpi_mode: str | None = None


def enable_dpi_awareness() -> str:
    """让本进程按物理像素工作。

    不设置的话，在 125% / 150% 缩放的屏幕上，tkinter 报的坐标和
    ImageGrab 抓到的像素会对不上，框选区域就会整体偏移。
    """
    global _dpi_mode
    if _dpi_mode is not None:
        return _dpi_mode

    mode = "none"
    try:  # Windows 10 1703+：每显示器 DPI 感知 V2
        user32 = ctypes.windll.user32
        ctx = ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if user32.SetProcessDpiAwarenessContext(ctx):
            mode = "per-monitor-v2"
    except Exception:
        pass

    if mode == "none":
        try:  # Windows 8.1+
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            mode = "per-monitor"
        except Exception:
            pass

    if mode == "none":
        try:  # Vista+
            ctypes.windll.user32.SetProcessDPIAware()
            mode = "system"
        except Exception:
            pass

    _dpi_mode = mode
    return mode


# ---------------------------------------------------------------- 矩形
@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def as_bbox(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)

    def is_valid(self, minimum: int = 4) -> bool:
        return self.width >= minimum and self.height >= minimum

    @classmethod
    def from_points(cls, x1: int, y1: int, x2: int, y2: int) -> "Rect":
        """两个拖拽点 -> 规范化矩形（自动处理从右下往左上拖）。"""
        return cls(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))


SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79


def virtual_screen() -> Rect:
    """整个虚拟桌面（多显示器时为所有屏幕的外接矩形），坐标可能为负。"""
    u = ctypes.windll.user32
    x = u.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = u.GetSystemMetrics(SM_YVIRTUALSCREEN)
    w = u.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    h = u.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    if w <= 0 or h <= 0:  # 极端兜底
        w, h = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
        x, y = 0, 0
    return Rect(x, y, x + w, y + h)


# ---------------------------------------------------------------- 抓图
def grab(rect: Rect):
    """抓取屏幕指定区域，返回 PIL.Image（RGB）。"""
    from PIL import ImageGrab

    img = ImageGrab.grab(bbox=rect.as_bbox(), all_screens=True)
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


def cursor_pos() -> tuple[int, int]:
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def clipboard_get_text() -> str:
    """读取剪贴板文本（tkinter 之外也能用的兜底实现）。"""
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        try:
            return root.clipboard_get()
        finally:
            root.destroy()
    except Exception:
        return ""
