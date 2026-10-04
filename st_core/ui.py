"""图形界面：主窗口 + 选区旁的译文浮窗 + 设置窗口。"""

from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import ocr as ocr_mod, pipeline, selection as sel_mod, translator as tr_mod
from .capture import Rect, virtual_screen
from .config import Config, load_history, save_history
from .hotkey import HotkeyManager
from .mousehook import MouseHook, cursor_pos
from .overlay import RegionSelector

WINDOW_TITLE = "屏幕翻译器 · 划词即译"
FONT = "Microsoft YaHei UI"
UI_FONT = (FONT, 10)
TEXT_FONT = (FONT, 11)
MONO = "Consolas"

DARK_BG = "#1f2430"
DARK_FG = "#e8eaf0"
DARK_SUB = "#9aa4b8"


# ==========================================================================
# 选区旁边的译文浮窗
# ==========================================================================
class ResultPopup:
    """框选结束后，在选区下方弹出的无边框小窗。Esc 或点击别处关闭。"""

    def __init__(self, root: tk.Misc):
        self.root = root
        self.top: tk.Toplevel | None = None
        self.text = ""
        self._focus_armed = False

    def show(self, text: str, rect: Rect | None, meta: str = "") -> None:
        self.hide()
        self.text = text
        top = tk.Toplevel(self.root)
        self.top = top
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        try:
            top.attributes("-alpha", 0.97)
        except tk.TclError:
            pass

        outer = tk.Frame(top, bg="#4c566a")
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=DARK_BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        body = tk.Label(
            inner, text=text, justify="left", anchor="nw", wraplength=430,
            bg=DARK_BG, fg=DARK_FG, font=(FONT, 12), padx=14, pady=12,
        )
        body.pack(fill="both", expand=True)
        body.bind("<Button-1>", lambda _e: self._copy())

        foot = tk.Frame(inner, bg=DARK_BG)
        foot.pack(fill="x", padx=14, pady=(0, 10))
        tk.Label(foot, text=meta, bg=DARK_BG, fg=DARK_SUB, font=(FONT, 9)).pack(side="left")
        tk.Label(foot, text="点击译文复制 · Esc 关闭", bg=DARK_BG, fg=DARK_SUB,
                 font=(FONT, 9)).pack(side="right")

        top.update_idletasks()
        w = max(280, min(top.winfo_reqwidth(), 470))
        h = min(top.winfo_reqheight(), 420)
        vs = virtual_screen()
        if rect is not None:
            x, y = rect.left, rect.bottom + 8
            if y + h > vs.bottom:
                y = max(vs.top + 4, rect.top - h - 8)
        else:
            x, y = vs.left + 60, vs.top + 60
        x = min(max(x, vs.left + 2), vs.right - w - 2)
        y = min(max(y, vs.top + 2), vs.bottom - h - 2)
        top.geometry(f"{w}x{h}+{x}+{y}")

        top.bind("<Escape>", lambda _e: self.hide())
        top.bind("<Button-3>", lambda _e: self.hide())
        top.after(400, self._arm_focus)
        top.bind("<FocusOut>", self._on_focus_out)
        top.focus_force()

    def _arm_focus(self) -> None:
        self._focus_armed = True

    def _on_focus_out(self, _event=None) -> None:
        if self._focus_armed:
            self.hide()

    def _copy(self) -> None:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.text)
        except tk.TclError:
            pass
        self.hide()

    def hide(self) -> None:
        self._focus_armed = False
        if self.top is not None:
            try:
                self.top.destroy()
            except tk.TclError:
                pass
            self.top = None


# ==========================================================================
# 主窗口
# ==========================================================================
class TranslatorApp:
    def __init__(self, root: tk.Tk, cfg: Config):
        self.root = root
        self.cfg = cfg
        self.results: "queue.Queue[pipeline.Job]" = queue.Queue()
        self.history: list[dict] = load_history(int(cfg["history_size"]))
        self.busy = False
        self.last_job: pipeline.Job | None = None
        self.popup = ResultPopup(root)
        self.hotkeys = HotkeyManager()
        self.mouse = MouseHook(min_distance=12)
        self.mouse_on = False
        self.last_selection = ""
        self.last_selection_at = 0.0
        self.last_mouse_pos: tuple[int, int] | None = None

        self._build_ui()
        self._load_history_list()
        self._apply_auto_select(save=False)
        self._setup_hotkeys()
        self._warm_up()
        self._tick()
        self.bring_to_front()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _warm_up(self) -> None:
        """后台预热 OCR 模型，免得第一次框选时干等。"""
        def worker() -> None:
            try:
                ocr_mod.warm_up(self.cfg["ocr_engine"])
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        self.root.title(WINDOW_TITLE)
        # 字体是按系统 DPI 放大的（150% 缩放下 Tk 的 scaling 是 2.0，11pt 字就有 30px 高），
        # 所以窗口尺寸得跟着屏幕走，写死 900x600 会让工具栏被挤掉。
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w = max(1020, min(1500, int(sw * 0.52)))
        h = max(700, min(980, int(sh * 0.62)))
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(980, 660)
        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        # ---- 顶部工具条：分两行，避免高 DPI 下被挤出屏幕 ----
        bar = ttk.Frame(self.root, padding=(10, 10, 10, 4))
        bar.grid(row=0, column=0, sticky="ew")

        row1 = ttk.Frame(bar)
        row1.pack(fill="x")
        self.btn_select = ttk.Button(row1, text="🖱 划词翻译", width=11,
                                     command=self.do_selection)
        self.btn_select.pack(side="left")
        self.btn_region = ttk.Button(row1, text="✂ 截图翻译", width=11, command=self.do_region)
        self.btn_region.pack(side="left", padx=(8, 0))
        ttk.Button(row1, text="📋 剪贴板", width=10,
                   command=self.do_clipboard).pack(side="left", padx=(8, 0))
        ttk.Button(row1, text="⇄ 反向", width=8, command=self.swap).pack(side="left", padx=(8, 0))
        ttk.Button(row1, text="⚙ 设置", width=8,
                   command=self.open_settings).pack(side="right")
        ttk.Button(row1, text="🩺 自检", width=8,
                   command=self.open_doctor).pack(side="right", padx=(0, 8))

        row2 = ttk.Frame(bar)
        row2.pack(fill="x", pady=(6, 0))

        ttk.Label(row2, text="方向").pack(side="left")
        self.var_dir = tk.StringVar(value=self.cfg["direction"])
        dir_box = ttk.Combobox(row2, width=8, state="readonly", textvariable=self.var_dir,
                               values=["auto", "en2zh", "zh2en"])
        dir_box.pack(side="left", padx=(4, 0))
        dir_box.bind("<<ComboboxSelected>>", lambda _e: self._on_dir_change())

        ttk.Label(row2, text="OCR").pack(side="left", padx=(12, 0))
        self.var_ocr = tk.StringVar(value=self.cfg["ocr_engine"])
        ocr_box = ttk.Combobox(row2, width=9, state="readonly", textvariable=self.var_ocr,
                               values=["auto", "rapidocr", "windows", "tesseract"])
        ocr_box.pack(side="left", padx=(4, 0))
        ocr_box.bind("<<ComboboxSelected>>",
                     lambda _e: self.cfg.set("ocr_engine", self.var_ocr.get()))

        ttk.Label(row2, text="翻译源").pack(side="left", padx=(12, 0))
        self.var_provider = tk.StringVar(value=self.cfg["translator"])
        prov_box = ttk.Combobox(row2, width=9, state="readonly", textvariable=self.var_provider,
                                values=["auto"] + list(tr_mod.PROVIDERS) + ["deepseek"])
        prov_box.pack(side="left", padx=(4, 0))
        prov_box.bind("<<ComboboxSelected>>",
                      lambda _e: self.cfg.set("translator", self.var_provider.get()))

        self.var_auto = tk.BooleanVar(value=bool(self.cfg["auto_selection_translate"]))
        ttk.Checkbutton(row2, text="鼠标选中就翻译", variable=self.var_auto,
                        command=self._apply_auto_select).pack(side="left", padx=(16, 0))

        self.var_copyfb = tk.BooleanVar(value=bool(self.cfg["selection_copy_fallback"]))
        ttk.Checkbutton(row2, text="读不到时用复制兜底", variable=self.var_copyfb,
                        command=lambda: self.cfg.set("selection_copy_fallback",
                                                     self.var_copyfb.get())
                        ).pack(side="left", padx=(10, 0))

        # ---- 中间：原文 / 译文 ----
        mid = ttk.Frame(self.root, padding=(10, 4, 10, 4))
        mid.grid(row=1, column=0, sticky="nsew")
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=1)
        mid.rowconfigure(1, weight=1)

        ttk.Label(mid, text="原文（识别结果，可直接改）", font=UI_FONT).grid(
            row=0, column=0, sticky="w")
        ttk.Label(mid, text="译文", font=UI_FONT).grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.txt_src = ScrolledText(mid, wrap="word", font=TEXT_FONT, undo=True, height=10)
        self.txt_src.grid(row=1, column=0, sticky="nsew", pady=(2, 0))
        self.txt_dst = ScrolledText(mid, wrap="word", font=TEXT_FONT, undo=True, height=10,
                                    bg="#fbfcfe")
        self.txt_dst.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(2, 0))

        tools = ttk.Frame(mid)
        tools.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(tools, text="复制译文", command=self.copy_result).pack(side="left")
        ttk.Button(tools, text="用原文重新翻译", command=self.retranslate).pack(side="left", padx=8)
        ttk.Button(tools, text="清空", command=self.clear).pack(side="left")
        self.var_popup = tk.BooleanVar(value=bool(self.cfg["popup"]))
        ttk.Checkbutton(tools, text="弹译文小窗", variable=self.var_popup,
                        command=lambda: self.cfg.set("popup", self.var_popup.get())
                        ).pack(side="right")
        self.var_autocopy = tk.BooleanVar(value=bool(self.cfg["copy_after_translate"]))
        ttk.Checkbutton(tools, text="自动复制译文", variable=self.var_autocopy,
                        command=lambda: self.cfg.set("copy_after_translate", self.var_autocopy.get())
                        ).pack(side="right", padx=10)

        # ---- 历史记录 ----
        hist = ttk.LabelFrame(self.root, text="历史记录（双击载入）", padding=(8, 4))
        hist.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 4))
        hist.columnconfigure(0, weight=1)
        self.list_hist = tk.Listbox(hist, height=4, font=UI_FONT, activestyle="none",
                                    highlightthickness=0)
        self.list_hist.grid(row=0, column=0, sticky="ew")
        self.list_hist.bind("<Double-Button-1>", self._load_history_item)
        sb = ttk.Scrollbar(hist, orient="vertical", command=self.list_hist.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.list_hist.configure(yscrollcommand=sb.set)

        # ---- 状态栏 ----
        self.status = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status, relief="sunken", anchor="w",
                  padding=(8, 3)).grid(row=3, column=0, sticky="ew")

    # ------------------------------------------------------------ 快捷键
    def _setup_hotkeys(self) -> None:
        self.hotkeys = HotkeyManager()
        try:
            self.hotkeys.add("selection", self.cfg["hotkey_selection"])
            self.hotkeys.add("region", self.cfg["hotkey_region"])
            self.hotkeys.add("clipboard", self.cfg["hotkey_clipboard"])
        except ValueError as exc:
            self.set_status(f"快捷键配置有误：{exc}")
            return
        self.hotkeys.start()
        if self.hotkeys.errors:
            self.set_status("；".join(self.hotkeys.errors))
        else:
            self.set_status(
                f"就绪 · 划词 {self.cfg['hotkey_selection'].upper()} · "
                f"截图 {self.cfg['hotkey_region'].upper()} · "
                f"剪贴板 {self.cfg['hotkey_clipboard'].upper()}"
            )

    def bring_to_front(self) -> None:
        """启动时把窗口顶到最前面。

        从批处理/快捷方式启动时，Windows 的前台窗口锁可能不让新窗口自动置顶，
        结果就是「双击了但什么都没看见」—— 窗口其实躲在浏览器后面。
        """
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(800, lambda: self.root.attributes("-topmost", False))
            self.root.focus_force()
        except tk.TclError:
            pass

    def _tick(self) -> None:
        # 1) 快捷键事件
        for name in self.hotkeys.poll():
            if name == "selection":
                self.root.after(120, self.do_selection)
            elif name == "region":
                self.root.after(150, self.do_region)
            elif name == "clipboard":
                self.root.after(150, self.do_clipboard)
        # 2) 鼠标划词事件（钩子线程 -> 队列 -> 这里）
        for pos in self.mouse.poll():
            self.last_mouse_pos = (pos[2], pos[3])
            if self.mouse_on and self.var_auto.get():
                # 稍等一下再读选区：有些程序要等鼠标松开后才更新选中状态
                self.root.after(180, self._auto_selection)
        # 3) 后台任务结果
        try:
            while True:
                job = self.results.get_nowait()
                self._handle_job(job)
        except queue.Empty:
            pass
        self.root.after(80, self._tick)

    # ------------------------------------------------------------ 划词翻译
    def _apply_auto_select(self, save: bool = True) -> None:
        """开关「鼠标选中就翻译」。"""
        want = bool(self.var_auto.get())
        if save:
            self.cfg.set("auto_selection_translate", want)
        if want and not self.mouse_on:
            if self.mouse.start():
                self.mouse_on = True
            else:
                self.var_auto.set(False)
                self.set_status(self.mouse.error or "鼠标钩子启动失败")
                return
        elif not want and self.mouse_on:
            self.mouse.stop()
            self.mouse_on = False
        if save:
            self.set_status("鼠标划词自动翻译：开" if want else "鼠标划词自动翻译：关")

    def _auto_selection(self) -> None:
        self.do_selection(auto=True)

    def _own_window_active(self) -> bool:
        """前台窗口是不是我们自己 —— 是的话别触发划词（在自家界面里选字不该弹窗）。"""
        try:
            return sel_mod.foreground_window_pid() == os.getpid()
        except Exception:
            return False

    def do_selection(self, auto: bool = False) -> None:
        """翻译鼠标当前选中的文字。auto=True 表示是划词钩子自动触发的。"""
        if self.busy:
            return
        if auto and self._own_window_active():
            return
        try:
            text, source = sel_mod.get_selected_text(
                self.cfg["selection_mode"], bool(self.cfg["selection_copy_fallback"]))
        except Exception as exc:
            if not auto:
                self.set_status(f"读取选区失败：{type(exc).__name__}: {exc}")
            return

        text = (text or "").strip()
        min_chars = int(self.cfg["selection_min_chars"] or 2)
        max_chars = int(self.cfg["selection_max_chars"] or 2000)

        if len(text) < min_chars:
            if not auto:
                self.set_status("没读到选中的文字：先用鼠标在别的程序里选中一段文字，再按快捷键")
            return
        if len(text) > max_chars:
            if not auto:
                self.set_status(f"选中的文字太长（{len(text)} 字符），已忽略")
            return

        now = time.time()
        if auto and text == self.last_selection and now - self.last_selection_at < 2.0:
            return                                   # 同一段文字短时间内不重复翻
        self.last_selection, self.last_selection_at = text, now

        self.set_status(f"读到选中文字 {len(text)} 字符（来源 {source or '无'}），正在翻译…")
        self._start(lambda: pipeline.run_text(text, self.cfg.data, kind="selection"))

    # ------------------------------------------------------------ 动作
    def do_region(self) -> None:
        if self.busy:
            return
        self.popup.hide()
        self.root.withdraw()
        self.root.update()
        time.sleep(0.15)                     # 等主窗口真的从屏幕上消失
        try:
            rect = RegionSelector(self.root).select()
        finally:
            self.root.deiconify()
            self.root.lift()
        if rect is None:
            self.set_status("已取消框选")
            return
        self.set_status(f"已框选 {rect.width}×{rect.height} 像素，正在识别…")
        self._start(lambda: pipeline.run_region(rect, self.cfg.data))

    def do_clipboard(self) -> None:
        if self.busy:
            return
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            self.set_status("剪贴板里没有文字")
            return
        self.set_status("正在翻译剪贴板内容…")
        self._start(lambda: pipeline.run_text(text, self.cfg.data, kind="clipboard"))

    def retranslate(self) -> None:
        text = self.txt_src.get("1.0", "end").strip()
        if not text:
            self.set_status("原文是空的")
            return
        self.set_status("正在重新翻译…")
        self._start(lambda: pipeline.run_text(text, self.cfg.data, kind="manual"))

    def swap(self) -> None:
        """把原文和译文对调，方向也反过来。"""
        src = self.txt_src.get("1.0", "end").strip()
        dst = self.txt_dst.get("1.0", "end").strip()
        self.txt_src.delete("1.0", "end")
        self.txt_src.insert("1.0", dst)
        self.txt_dst.delete("1.0", "end")
        self.txt_dst.insert("1.0", src)
        new_dir = {"en2zh": "zh2en", "zh2en": "en2zh"}.get(self.var_dir.get(), "auto")
        if self.var_dir.get() != "auto":
            self.var_dir.set(new_dir)
            self._on_dir_change()

    def copy_result(self) -> None:
        text = self.txt_dst.get("1.0", "end").strip()
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.set_status("译文已复制到剪贴板")

    def clear(self) -> None:
        self.txt_src.delete("1.0", "end")
        self.txt_dst.delete("1.0", "end")
        self.set_status("已清空")

    def _on_dir_change(self) -> None:
        self.cfg.set("direction", self.var_dir.get())

    # ------------------------------------------------------------ 后台任务
    def _start(self, func) -> None:
        self.busy = True
        self.btn_select.state(["disabled"])

        def worker() -> None:
            try:
                job = func()
            except Exception as exc:               # 兜底，避免线程静默死掉
                job = pipeline.Job(error=f"{type(exc).__name__}: {exc}")
            self.results.put(job)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_job(self, job: pipeline.Job) -> None:
        self.busy = False
        self.btn_select.state(["!disabled"])
        self.last_job = job

        if job.source_text:
            self.txt_src.delete("1.0", "end")
            self.txt_src.insert("1.0", job.source_text)
        self.txt_dst.delete("1.0", "end")

        if job.error:
            self.txt_dst.insert("1.0", "⚠ " + job.error)
            self.set_status("失败：" + job.error.splitlines()[0])
            return

        self.txt_dst.insert("1.0", job.target_text)

        if self.var_autocopy.get():
            self.copy_result()

        detail = " · ".join(
            f"{k} {v * 1000:.0f}ms" for k, v in job.timings.items()
        )
        meta = f"{job.provider} · {job.ocr_engine or 'clipboard'} · {detail}"
        if job.notes:
            self.set_status(f"完成（{meta}） · 提示：{job.notes[0]}")
        else:
            self.set_status(f"完成（{meta}）")

        if self.var_popup.get():
            anchor = job.rect
            if anchor is None:                       # 划词/剪贴板：弹在鼠标旁边
                x, y = self.last_mouse_pos or cursor_pos()
                anchor = Rect(x, y, x, y)
            self.popup.show(job.target_text, anchor, meta)

        self._push_history(job)

    def set_status(self, text: str) -> None:
        self.status.set(text[:200])

    # ------------------------------------------------------------ 历史
    def _push_history(self, job: pipeline.Job) -> None:
        if not job.target_text:
            return
        self.history.insert(0, {
            "time": time.strftime("%H:%M:%S"),
            "provider": job.provider,
            "direction": job.direction,
            "source_text": job.source_text[:4000],
            "target_text": job.target_text[:4000],
        })
        self.history = self.history[: int(self.cfg["history_size"])]
        save_history(self.history, int(self.cfg["history_size"]))
        self._load_history_list()

    def _load_history_list(self) -> None:
        self.list_hist.delete(0, "end")
        for item in self.history:
            src = item.get("source_text", "").replace("\n", " ")
            tgt = item.get("target_text", "").replace("\n", " ")
            self.list_hist.insert(
                "end", f"[{item.get('time', '')}] {src[:34]}  →  {tgt[:34]}"
            )

    def _load_history_item(self, _event=None) -> None:
        sel = self.list_hist.curselection()
        if not sel:
            return
        item = self.history[sel[0]]
        self.txt_src.delete("1.0", "end")
        self.txt_src.insert("1.0", item.get("source_text", ""))
        self.txt_dst.delete("1.0", "end")
        self.txt_dst.insert("1.0", item.get("target_text", ""))
        self.set_status(f"已载入历史记录（{item.get('provider', '')}）")

    # ------------------------------------------------------------ 设置 / 自检
    def open_settings(self) -> None:
        SettingsDialog(self.root, self.cfg, on_saved=self._setup_hotkeys)

    def open_doctor(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("环境自检")
        win.geometry("720x460")
        box = ScrolledText(win, wrap="word", font=(MONO, 10))
        box.pack(fill="both", expand=True)
        box.insert("1.0", "正在检测，请稍候（会实测几个翻译接口）…\n")
        box.configure(state="disabled")

        def worker() -> None:
            report = pipeline.doctor(self.cfg.data)
            def show() -> None:
                box.configure(state="normal")
                box.delete("1.0", "end")
                box.insert("1.0", report)
                box.configure(state="disabled")
            self.root.after(0, show)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------ 退出
    def on_close(self) -> None:
        try:
            self.hotkeys.stop()
        except Exception:
            pass
        try:
            self.mouse.stop()
        except Exception:
            pass
        self.root.destroy()


# ==========================================================================
# 设置窗口
# ==========================================================================
class SettingsDialog:
    def __init__(self, root: tk.Misc, cfg: Config, on_saved=None):
        self.cfg = cfg
        self.on_saved = on_saved
        self.root = root
        self.top = tk.Toplevel(root)
        self.top.title("设置")
        self.top.transient(root)
        self.top.resizable(False, False)
        self.top.grab_set()

        pad = {"padx": 10, "pady": 5}
        frame = ttk.Frame(self.top, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        row = 0

        def add_entry(label: str, value: str, width: int = 34,
                      show: str | None = None) -> tk.StringVar:
            nonlocal row
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", **pad)
            var = tk.StringVar(value=value)
            entry = ttk.Entry(frame, textvariable=var, width=width)
            if show:
                entry.configure(show=show)
            entry.grid(row=row, column=1, sticky="ew", **pad)
            row += 1
            return var

        ttk.Label(frame, text="快捷键与翻译源", font=(FONT, 10, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 2))
        row += 1

        self.v_hk_region = add_entry("框选翻译快捷键", cfg["hotkey_region"], 20)
        self.v_hk_clip = add_entry("剪贴板翻译快捷键", cfg["hotkey_clipboard"], 20)

        ttk.Label(frame, text="DeepSeek Base URL").grid(row=row, column=0, sticky="w", **pad)
        self.v_base = tk.StringVar(value=cfg["deepseek"]["base_url"])
        ttk.Entry(frame, textvariable=self.v_base, width=34).grid(row=row, column=1, sticky="ew", **pad)
        row += 1

        self.v_model = add_entry("模型名", cfg["deepseek"]["model"], 20)
        self.v_key = add_entry("API Key（留空则用免费接口）", cfg["deepseek"]["api_key"], 34, show="•")

        self.v_popup = tk.BooleanVar(value=bool(cfg["popup"]))
        ttk.Checkbutton(frame, text="框选后在选区旁弹出译文小窗",
                        variable=self.v_popup).grid(row=row, column=1, sticky="w", **pad)
        row += 1
        self.v_autocopy = tk.BooleanVar(value=bool(cfg["copy_after_translate"]))
        ttk.Checkbutton(frame, text="翻译完成后自动复制译文",
                        variable=self.v_autocopy).grid(row=row, column=1, sticky="w", **pad)
        row += 1

        ttk.Label(frame, text="常用键名：ctrl / alt / shift / win + a-z / f1-f12，例如 ctrl+alt+z",
                  foreground="#666").grid(row=row, column=0, columnspan=2, sticky="w", **pad)
        row += 1

        btns = ttk.Frame(frame)
        btns.grid(row=row, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(btns, text="保存", command=self.save).pack(side="right")
        ttk.Button(btns, text="取消", command=self.top.destroy).pack(side="right", padx=8)
        ttk.Button(btns, text="打开配置文件夹", command=self._open_dir).pack(side="left")

    def _open_dir(self) -> None:
        import os
        import subprocess

        from .config import APP_DIR

        try:
            os.startfile(APP_DIR)  # noqa: S606
        except Exception:
            subprocess.Popen(["explorer", str(APP_DIR)])

    def save(self) -> None:
        self.cfg.set("hotkey_region", self.v_hk_region.get().strip() or "ctrl+alt+z", save=False)
        self.cfg.set("hotkey_clipboard", self.v_hk_clip.get().strip() or "ctrl+alt+x", save=False)
        self.cfg.set("popup", bool(self.v_popup.get()), save=False)
        self.cfg.set("copy_after_translate", bool(self.v_autocopy.get()), save=False)
        self.cfg.data["deepseek"] = {
            "base_url": self.v_base.get().strip() or "https://api.deepseek.com/v1",
            "model": self.v_model.get().strip() or "deepseek-chat",
            "api_key": self.v_key.get().strip(),
        }
        try:
            from .hotkey import parse_hotkey
            parse_hotkey(self.cfg["hotkey_region"])
            parse_hotkey(self.cfg["hotkey_clipboard"])
        except ValueError as exc:
            messagebox.showerror("快捷键有问题", str(exc), parent=self.top)
            return

        self.cfg.save()
        if self.on_saved:
            self.on_saved()
        self.top.destroy()
        messagebox.showinfo("已保存", "设置已保存，快捷键立即生效。", parent=self.root)


def run(cfg: Config | None = None) -> None:
    """启动图形界面。"""
    from .capture import enable_dpi_awareness

    enable_dpi_awareness()
    root = tk.Tk()
    app = TranslatorApp(root, cfg or Config.load())
    root.mainloop()
