"""把「截图 → 识别 → 翻译」串成一条流水线，并附带环境自检。"""

from __future__ import annotations

import platform
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from . import capture, ocr as ocr_mod, translator as tr_mod
from .capture import Rect


@dataclass
class Job:
    """一次翻译任务的完整结果。"""

    kind: str = "region"                      # region / clipboard / manual
    rect: Rect | None = None
    image: Image.Image | None = None
    source_text: str = ""
    target_text: str = ""
    ocr_engine: str = ""
    ocr_lang: str = ""
    provider: str = ""
    direction: str = "auto"
    timings: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.target_text) and not self.error


def _lang_hint(direction: str) -> str:
    return {"en2zh": "en", "zh2en": "zh"}.get(direction, "auto")


def ocr_image(image: Image.Image, cfg: dict) -> ocr_mod.OcrResult:
    return ocr_mod.recognize(
        image,
        lang_hint=_lang_hint(cfg.get("direction", "auto")),
        engine=cfg.get("ocr_engine", "auto"),
        scale=float(cfg.get("ocr_scale", 0) or 0),
    )


def translate_text(text: str, cfg: dict) -> tr_mod.Translation:
    return tr_mod.translate(
        text,
        direction=cfg.get("direction", "auto"),
        provider=cfg.get("translator", "auto"),
        cfg=cfg.get("deepseek", {}) or {},
        order=cfg.get("translator_order"),
    )


# --------------------------------------------------------------------------
# 两个入口
# --------------------------------------------------------------------------
def run_region(rect: Rect, cfg: dict, image: Image.Image | None = None) -> Job:
    job = Job(kind="region", rect=rect, direction=cfg.get("direction", "auto"))
    try:
        t0 = time.time()
        img = image if image is not None else capture.grab(rect)
        job.image = img
        job.timings["capture"] = time.time() - t0

        t0 = time.time()
        result = ocr_image(img, cfg)
        job.timings["ocr"] = time.time() - t0
        job.ocr_engine, job.ocr_lang = result.engine, result.lang
        job.source_text = result.text
        job.notes.extend(result.notes)

        if not result.ok:
            job.error = "截图区域里没有识别到文字，换个区域再试试（或者把小字放大一点）"
            return job

        t0 = time.time()
        translation = translate_text(result.text, cfg)
        job.timings["translate"] = time.time() - t0
        job.target_text, job.provider = translation.text, translation.provider
        if cfg.get("direction", "auto") == "auto":
            job.direction = f"{translation.src}2{translation.tgt}"
    except Exception as exc:
        job.error = str(exc)
    return job


def run_text(text: str, cfg: dict, kind: str = "clipboard") -> Job:
    job = Job(kind=kind, source_text=(text or "").strip(),
              direction=cfg.get("direction", "auto"))
    if not job.source_text:
        job.error = "剪贴板里没有文字"
        return job
    try:
        t0 = time.time()
        translation = translate_text(job.source_text, cfg)
        job.timings["translate"] = time.time() - t0
        job.target_text, job.provider = translation.text, translation.provider
        if cfg.get("direction", "auto") == "auto":
            job.direction = f"{translation.src}2{translation.tgt}"
    except Exception as exc:
        job.error = str(exc)
    return job


def rerun(job: Job, cfg: dict, text: str | None = None) -> Job:
    """用界面上改过的文本重新翻译。"""
    return run_text(text if text is not None else job.source_text, cfg, kind=job.kind)


# --------------------------------------------------------------------------
# 环境自检
# --------------------------------------------------------------------------
def doctor(cfg: dict, test_translate: bool = True) -> str:
    lines: list[str] = ["======== 屏幕翻译器 环境自检 ========"]
    lines.append(f"Python      : {sys.version.split()[0]}  ({platform.machine()})")
    lines.append(f"操作系统    : {platform.platform()}")
    lines.append(f"DPI 感知    : {capture.enable_dpi_awareness()}")
    vs = capture.virtual_screen()
    lines.append(f"虚拟桌面    : {vs.width} x {vs.height} (左上角 {vs.left},{vs.top})")

    # --- 依赖 ---
    for mod, tip in (("PIL", "Pillow"), ("tkinter", "Python 自带的 tkinter")):
        try:
            __import__(mod)
            lines.append(f"依赖 {mod:<10}: 已安装")
        except Exception as exc:
            lines.append(f"依赖 {mod:<10}: 缺失（{tip}） -> {exc}")

    # --- 划词翻译 ---
    from . import selection as sel_mod

    if sel_mod.uia_available():
        lines.append(f"UI Automation: 可用（uiautomation {sel_mod.uia_version()}）—— 划词走这条主路")
    else:
        lines.append("UI Automation: 不可用（没装 uiautomation）—— 划词只能靠模拟 Ctrl+C")
    lines.append(f"自动划词    : {'开（选中即翻译）' if cfg.get('auto_selection_translate') else '关（用快捷键触发）'}")
    lines.append(f"复制兜底    : {'允许（UIA 读不到时模拟 Ctrl+C，资源管理器里禁用）' if cfg.get('selection_copy_fallback') else '已关闭'}")
    lines.append(f"划词快捷键  : {cfg.get('hotkey_selection', 'ctrl+alt+z')}")

    # --- OCR ---
    langs = ocr_mod.windows_ocr_languages()
    lines.append(f"Windows OCR : {'可用，语言=' + ', '.join(langs) if langs else '不可用'}")
    if langs:
        zh = ocr_mod.windows_ocr_language_for("zh")
        en = ocr_mod.windows_ocr_language_for("en")
        lines.append(f"              中文模型: {zh or '缺少 —— 中译英会不准'}")
        lines.append(f"              英文模型: {en or '缺少 —— 英译中会不准'}")
    lines.append(f"RapidOCR    : {'可用（离线，中英文自带模型，推荐）' if ocr_mod.rapidocr_available() else '未安装（可选，建议装：install_ocr.bat）'}")
    lines.append(f"Tesseract   : {'可用' if ocr_mod.tesseract_available() else '未安装（可选）'}")
    lines.append(f"onnxruntime : {'已预加载（避免与 WinRT 的加载顺序冲突）' if ocr_mod.ONNXRUNTIME_PRELOADED else '未安装'}")
    try:
        chosen = ocr_mod.choose_engine(cfg.get("ocr_engine", "auto"), "auto")
        lines.append(f"默认 OCR    : {chosen}")
        for hint in ("en", "zh"):
            note = ocr_mod.engine_note(chosen, hint)
            if note:
                lines.append(f"              ! {note}")
    except Exception as exc:
        lines.append(f"默认 OCR    : 不可用 -> {exc}")

    # --- 翻译源 ---
    lines.append("翻译源（实测一段短文本，网络不通会显示失败原因）:")
    if test_translate:
        probe = "Hello, this is a translation test." if cfg.get("direction") != "zh2en" else "这是一句翻译测试。"
        for name in ("bing", "google", "youdao", "mymemory"):
            t0 = time.time()
            try:
                res = tr_mod.translate(probe, direction="auto", provider=name, cfg={})
                lines.append(f"  {name:<9}: 成功 ({time.time() - t0:.2f}s) -> {res.text[:28]}")
            except Exception as exc:
                lines.append(f"  {name:<9}: 失败 -> {str(exc).splitlines()[0][:80]}")
        key = (cfg.get("deepseek", {}) or {}).get("api_key")
        lines.append(f"  deepseek : {'已配置 Key' if key else '未配置（可选，填了质量更好）'}")
    else:
        lines.append("  （已跳过联网测试）")

    lines.append("====================================")
    return "\n".join(lines)
