"""框选遮罩层：全屏半透明窗口 + 鼠标拖拽画框。

用法：
    sel = RegionSelector(root)          # root 是已有的 tkinter 根窗口
    rect = sel.select()                 # 阻塞直到用户松开鼠标；返回 Rect 或 None（取消）
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from .capture import Rect, virtual_screen

HINT_TEXT = "拖动鼠标框选要翻译的文字      ·      Esc / 右键 取消"


class RegionSelector:
    def __init__(self, root: tk.Misc, hint: str = HINT_TEXT):
        self.root = root
        self.hint = hint
        self.result: Optional[Rect] = None
        self._start: Optional[tuple[int, int]] = None
        self._rect_id: Optional[int] = None
        self._size_id: Optional[int] = None
        self._name_id: Optional[int] = None
        self._vs = virtual_screen()

    # ------------------------------------------------------------ 公开接口
    def select(self) -> Optional[Rect]:
        vs = self._vs
        top = tk.Toplevel(self.root)
        top.overrideredirect(True)          # 去掉标题栏
        top.attributes("-topmost", True)
        try:
            top.attributes("-alpha", 0.35)  # 半透明，能看清底下的内容
        except tk.TclError:
            pass
        top.configure(bg="black")
        top.geometry(f"{vs.width}x{vs.height}+{vs.left}+{vs.top}")
        top.lift()

        canvas = tk.Canvas(top, bg="black", highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)

        # 顶部提示
        canvas.create_text(
            vs.width // 2, 46, text=self.hint, fill="#ffe680",
            font=("Microsoft YaHei UI", 13), anchor="center",
        )

        canvas.bind("<Button-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_drag)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        canvas.bind("<Button-3>", lambda _e: self._cancel(top))
        top.bind("<Escape>", lambda _e: self._cancel(top))
        top.focus_force()                   # 让 Esc 能被接住
        canvas.focus_set()

        try:
            self.root.wait_window(top)
        except tk.TclError:
            pass
        return self.result

    # ------------------------------------------------------------ 事件
    def _on_press(self, event: tk.Event) -> None:
        self._start = (event.x, event.y)
        if self._rect_id:
            self._canvas_delete()
        canvas = event.widget
        self._rect_id = canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="#ff4d4f", width=2
        )
        self._size_id = canvas.create_text(
            event.x, event.y, text="", fill="#ffffff", anchor="nw",
            font=("Consolas", 11),
        )

    def _on_drag(self, event: tk.Event) -> None:
        if not self._start or self._rect_id is None:
            return
        canvas = event.widget
        x0, y0 = self._start
        canvas.coords(self._rect_id, x0, y0, event.x, event.y)
        canvas.coords(self._size_id, event.x + 8, event.y + 8)
        canvas.itemconfigure(
            self._size_id, text=f"{abs(event.x - x0)} × {abs(event.y - y0)}"
        )

    def _on_release(self, event: tk.Event) -> None:
        if not self._start:
            self._destroy(event.widget)
            return
        # 用 x_root / y_root（真实屏幕坐标）来抓图，比窗口内坐标可靠
        rect = Rect.from_points(
            event.x_root, event.y_root,
            event.x_root - (event.x - self._start[0]),
            event.y_root - (event.y - self._start[1]),
        )
        self.result = rect if rect.is_valid(6) else None
        self._destroy(event.widget)

    def _cancel(self, top: tk.Toplevel) -> None:
        self.result = None
        self._destroy_top(top)

    # ------------------------------------------------------------ 收尾
    def _canvas_delete(self) -> None:
        self._rect_id = None
        self._size_id = None

    def _destroy(self, widget: tk.Misc) -> None:
        self._destroy_top(widget.winfo_toplevel())

    def _destroy_top(self, top: tk.Toplevel) -> None:
        try:
            top.grab_release()
        except tk.TclError:
            pass
        try:
            top.destroy()
        except tk.TclError:
            pass


def pick_region(root: tk.Misc, before: Optional[Callable[[], None]] = None,
                after: Optional[Callable[[], None]] = None) -> Optional[Rect]:
    """便捷函数：隐藏主窗口 -> 框选 -> 恢复主窗口。"""
    if before:
        before()
    try:
        return RegionSelector(root).select()
    finally:
        if after:
            after()
