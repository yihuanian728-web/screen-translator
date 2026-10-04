"""文字识别（OCR）。

三个后端，auto 模式按下面的顺序挑第一个可用的：

1. rapidocr —— 装了 rapidocr-onnxruntime 时可用。纯离线、中英文模型都自带，
                不依赖系统语言包，实测对中英文混排最准（首次加载模型约 1 秒）。
2. windows  —— Windows 10/11 系统自带的 OCR（Windows.Media.Ocr）。
                不用装任何东西、不联网、最快（几十毫秒），
                但识别能力取决于系统里装了哪些语言的 OCR 包：
                只装了中文包时，英文会被认成 "b rown (0)<" 这种乱码。
3. tesseract—— 装了 tesseract.exe 时可用。

对外只暴露：recognize(image, lang_hint=...) -> OcrResult
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import io
import shutil
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable

from PIL import Image

ENGINES = ("rapidocr", "windows", "tesseract")


def _preload_onnxruntime() -> bool:
    """在导入任何 winrt 模块之前先把 onnxruntime 拉起来。

    【踩坑记录】实测（Python 3.12 + pywinrt 3.2 + onnxruntime 1.30）：
        import winrt.windows.media.ocr   # 先
        import onnxruntime               # 后 -> 直接 0xC0000005 访问违例，进程崩
    反过来先 import onnxruntime 就一切正常。所以这里在模块导入阶段就定好顺序，
    避免「先用了 Windows OCR、再用 RapidOCR」时随机崩溃。
    """
    try:
        if importlib.util.find_spec("rapidocr_onnxruntime") is None:
            return False
        import onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


ONNXRUNTIME_PRELOADED = _preload_onnxruntime()


class OcrError(RuntimeError):
    """OCR 不可用或识别失败。"""


@dataclass
class OcrResult:
    text: str
    engine: str = ""
    lang: str = ""
    lines: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.text.strip())


# ==========================================================================
# 语言判断
# ==========================================================================
def has_cjk(text: str, threshold: float = 0.12) -> bool:
    """文本里中日韩字符占比是否超过阈值 —— 用来判断「这段是中文还是英文」。"""
    if not text:
        return False
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    letters = sum(1 for ch in text if ch.isalpha())
    total = max(letters, 1)
    return (cjk / total) >= threshold


# ==========================================================================
# 后端 1：Windows 自带 OCR
# ==========================================================================
_winrt_cache: dict[str, Any] | None = None
_winrt_error: str = ""
_apartment_done = False


def _init_apartment() -> None:
    """WinRT 调用前初始化 COM 套间；每个线程各自初始化一次即可。"""
    global _apartment_done
    if _apartment_done:
        return
    for mod_name in ("winrt.runtime", "winrt", "winsdk"):
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        init = getattr(mod, "init_apartment", None)
        if callable(init):
            try:
                init()
            except Exception:
                pass
            break
    _apartment_done = True


def _load_winrt() -> dict[str, Any]:
    """加载 WinRT 绑定。pywinrt（winrt-*）和旧的 winsdk 两种包名都试。"""
    global _winrt_cache, _winrt_error
    if _winrt_cache is not None:
        if not _winrt_cache:
            raise OcrError(_winrt_error)
        return _winrt_cache

    last_exc: Exception | None = None
    for root in ("winrt", "winsdk"):
        try:
            ocr_mod = importlib.import_module(f"{root}.windows.media.ocr")
            glob_mod = importlib.import_module(f"{root}.windows.globalization")
            img_mod = importlib.import_module(f"{root}.windows.graphics.imaging")
            str_mod = importlib.import_module(f"{root}.windows.storage.streams")
            _winrt_cache = {
                "root": root,
                "OcrEngine": ocr_mod.OcrEngine,
                "Language": glob_mod.Language,
                "BitmapDecoder": img_mod.BitmapDecoder,
                "InMemoryRandomAccessStream": str_mod.InMemoryRandomAccessStream,
                "DataWriter": str_mod.DataWriter,
            }
            _winrt_error = ""
            return _winrt_cache
        except Exception as exc:  # noqa: PERF203
            last_exc = exc

    _winrt_cache = {}
    _winrt_error = (
        "未找到 Windows OCR 的 Python 绑定（winrt-Windows.Media.Ocr）。"
        f"请先运行 install.bat。原始错误：{last_exc}"
    )
    raise OcrError(_winrt_error)


def _wait_async(op: Any, timeout: float = 30.0) -> Any:
    """等待 WinRT 的 IAsyncOperation 完成。"""
    if op is None:
        raise OcrError("WinRT 返回了空操作")
    getter = getattr(op, "get", None)
    if callable(getter):                     # pywinrt 提供阻塞式 get()
        try:
            return getter()
        except TypeError:
            pass

    async def _coro() -> Any:                # 退路：当 awaitable 用
        return await op

    return asyncio.run(asyncio.wait_for(_coro(), timeout))


def windows_ocr_languages() -> list[str]:
    """系统里可用的 OCR 语言标签，例如 ['en-US', 'zh-Hans-CN']。"""
    try:
        _init_apartment()
        engine = _load_winrt()["OcrEngine"]
        return [lang.language_tag for lang in engine.available_recognizer_languages]
    except Exception:
        return []


def _pick_language(hint: str, available: Iterable[str], strict: bool = False) -> str | None:
    """在可用语言里挑一个最贴近 hint 的（hint 形如 'en' / 'zh' / 'en-US'）。

    strict=True 时只接受主语言相同的（缺 en-US 就返回 None，不会拿中文模型顶替）。
    """
    available = list(available)
    if not available:
        return None
    wanted = (hint or "").strip()
    for tag in available:                                  # 完全一致
        if tag.lower() == wanted.lower():
            return tag
    primary = wanted.split("-")[0].lower() or "en"
    for tag in available:                                  # 主语言一致（zh-Hans-CN ~ zh）
        if tag.split("-")[0].lower() == primary:
            return tag
    if strict:
        return None
    for tag in available:                                  # 兜底给一个能用的
        if tag.split("-")[0].lower() == "en":
            return tag
    return available[0]


def windows_ocr_language_for(kind: str) -> str | None:
    """kind: 'zh' 或 'en'。系统里没有对应的 OCR 语言包时返回 None。"""
    langs = windows_ocr_languages()
    if not langs:
        return None
    return _pick_language("zh-Hans" if kind == "zh" else "en", langs, strict=True)


def missing_windows_language(kind: str) -> str:
    """系统缺哪种语言的 OCR 模型，返回 '英文' / '中文'，不缺就返回 ''。"""
    if kind not in ("en", "zh"):
        return ""
    if not windows_ocr_languages():        # 整个 Windows OCR 都不可用，另说
        return ""
    if windows_ocr_language_for(kind):
        return ""
    return "英文" if kind == "en" else "中文"


def _windows_recognize(image: Image.Image, lang_tag: str | None) -> OcrResult:
    _init_apartment()
    api = _load_winrt()

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    data = buf.getvalue()

    stream = api["InMemoryRandomAccessStream"]()
    writer = api["DataWriter"](stream.get_output_stream_at(0))
    writer.write_bytes(data)
    _wait_async(writer.store_async())
    writer.detach_stream()
    stream.seek(0)

    decoder = _wait_async(api["BitmapDecoder"].create_async(stream))
    bitmap = _wait_async(decoder.get_software_bitmap_async())

    engine = None
    if lang_tag:
        try:
            engine = api["OcrEngine"].try_create_from_language(api["Language"](lang_tag))
        except Exception:
            engine = None
    if engine is None:                                     # 用系统默认语言
        engine = api["OcrEngine"].try_create_from_user_profile_languages()
    if engine is None:
        raise OcrError("系统没有安装任何 OCR 语言包，请到「设置 → 时间和语言 → 语言」里添加语言的 OCR 组件")

    result = _wait_async(engine.recognize_async(bitmap))
    lines = [line.text for line in result.lines]
    try:
        actual = engine.recognizer_language.language_tag
    except Exception:
        actual = lang_tag or "system-default"
    return OcrResult(text="\n".join(lines), engine="windows",
                     lang=actual, lines=lines)


# ==========================================================================
# 后端 2：RapidOCR（可选，离线）
# ==========================================================================
_rapid_engine: Any = None
_rapid_lock = threading.Lock()


def rapidocr_available() -> bool:
    return ONNXRUNTIME_PRELOADED and _spec_exists("rapidocr_onnxruntime")


def _rapidocr_recognize(image: Image.Image) -> OcrResult:
    global _rapid_engine
    with _rapid_lock:
        if _rapid_engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _rapid_engine = RapidOCR()
        engine = _rapid_engine
    import numpy as np

    result, _elapse = engine(np.array(image.convert("RGB")))
    lines = [item[1] for item in (result or [])]
    return OcrResult(text="\n".join(lines), engine="rapidocr", lang="zh+en", lines=lines)


# ==========================================================================
# 后端 3：Tesseract（可选）
# ==========================================================================
def tesseract_available() -> bool:
    if shutil.which("tesseract"):
        return True
    for path in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                 r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if shutil.which(path) or __import__("os").path.exists(path):
            return True
    try:
        importlib.import_module("pytesseract")
        return bool(shutil.which("tesseract"))
    except Exception:
        return False


def _tesseract_recognize(image: Image.Image, kind: str) -> OcrResult:
    import pytesseract

    lang = "chi_sim+eng" if kind == "zh" else "eng"
    text = pytesseract.image_to_string(image, lang=lang)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return OcrResult(text="\n".join(lines), engine="tesseract", lang=lang, lines=lines)


# ==========================================================================
# 统一入口
# ==========================================================================
def available_engines() -> dict[str, bool]:
    try:
        win_ok = bool(windows_ocr_languages())
    except Exception:
        win_ok = False
    return {
        "windows": win_ok,
        "rapidocr": rapidocr_available(),
        "tesseract": tesseract_available(),
    }


def choose_engine(preferred: str = "auto", lang_hint: str = "auto") -> str:
    """挑一个 OCR 引擎。

    auto 模式的优先级（见 ENGINES）：
        rapidocr  离线、中英文模型都自带、不依赖系统语言包，效果最好
        windows   Windows 自带，速度最快，但需要系统装了对应语言的 OCR 包
        tesseract 需要另外安装 tesseract.exe
    """
    usable = available_engines()
    if preferred != "auto":
        if usable.get(preferred):
            return preferred
        raise OcrError(f"指定的 OCR 引擎「{preferred}」不可用，可用：{_usable_text(usable)}")

    for name in ENGINES:
        if usable.get(name):
            return name
    raise OcrError(
        "没有可用的 OCR 引擎。请运行 install.bat 安装 Windows OCR 绑定，"
        "或运行 install_ocr.bat 安装 RapidOCR。"
    )


def _spec_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _usable_text(usable: dict[str, bool]) -> str:
    ready = [k for k, v in usable.items() if v]
    return "、".join(ready) if ready else "无"


def engine_note(engine: str, lang_hint: str) -> str:
    """给界面/自检用的一句话提示（没有问题就返回空串）。"""
    if engine != "windows":
        return ""
    missing = missing_windows_language(lang_hint)
    if not missing:
        return ""
    return (f"系统缺少{missing} OCR 语言包，Windows 自带 OCR 识别会明显不准；"
            f"建议改用 RapidOCR（install_ocr.bat）或补装语言包")


def warm_up(engine: str = "auto") -> bool:
    """提前把模型加载好，免得第一次框选等太久。返回是否真的预热了。"""
    global _rapid_engine
    try:
        used = choose_engine(engine, "auto")
    except Exception:
        return False
    if used != "rapidocr" or _rapid_engine is not None:
        return False
    try:
        from rapidocr_onnxruntime import RapidOCR

        _rapid_engine = RapidOCR()
        return True
    except Exception:
        return False


def _maybe_upscale(image: Image.Image, scale: float) -> Image.Image:
    """小字放大后识别率更高，但放太大反而会让文字检测器认错。

    实测（见 tools/bench_ocr.py）：截图高度 50px 以下放大 2 倍收益明显，
    正常大小的文字直接原样识别最好。
    """
    if scale <= 0:                      # 自动
        scale = 2.0 if image.height < 50 else 1.0
    if scale <= 1.01:
        return image
    w = min(int(image.width * scale), 4000)
    h = min(int(image.height * scale), 4000)
    return image.resize((w, h), Image.LANCZOS)


def recognize(
    image: Image.Image,
    lang_hint: str = "auto",          # auto / en / zh
    engine: str = "auto",
    scale: float = 0,
) -> OcrResult:
    """识别图片中的文字。

    lang_hint 只是提示优先用哪种语言模型，并不强制。
    """
    if image is None or image.width < 2 or image.height < 2:
        raise OcrError("截图区域太小")

    used = choose_engine(engine, lang_hint)
    img = _maybe_upscale(image, scale)

    if used == "windows":
        kind = "zh" if lang_hint == "zh" else ("en" if lang_hint == "en" else "auto")
        if kind == "auto":
            # 先用「中文引擎」跑：Windows 的中文模型对拉丁字母也有一定识别力
            first = _windows_recognize(img, windows_ocr_language_for("zh"))
            if first.ok and not has_cjk(first.text):
                # 认出来全是英文 -> 说明源语言是英文，换英文模型再跑一遍更准
                en_tag = windows_ocr_language_for("en")
                if en_tag and en_tag != first.lang:
                    second = _windows_recognize(img, en_tag)
                    if second.ok and len(second.text) >= len(first.text) * 0.8:
                        result = second
                    else:
                        result = first
                else:
                    result = first
            else:
                result = first
        else:
            result = _windows_recognize(img, windows_ocr_language_for(kind))
    elif used == "rapidocr":
        result = _rapidocr_recognize(img)
    else:
        result = _tesseract_recognize(img, "zh" if lang_hint == "zh" else "en")

    note = engine_note(used, lang_hint)
    if note:
        result.notes.append(note)
    return result
