"""翻译：多个免费/离线翻译源，自动降级。

设计要点
--------
* 只用标准库 urllib 发请求，不额外依赖 requests。
* 每个源都实现成 (text, src, tgt) -> str 的小函数，注册进 PROVIDERS。
* auto 模式下按 config 里的 translator_order 依次尝试，谁先成功用谁，
  并在结果里记录实际用的是哪个源。
* 网络不通 / 接口失效时给出明确提示，并告诉用户可以配置 DeepSeek API Key。

实测（2026-xx，国内家庭宽带，无代理）
------------------------------------
    有道 aidemo   ✅ 免 key，200-400ms，速度最快
    MyMemory      ✅ 免 key，1s 左右，长句质量略好
    谷歌 gtx      ❌ 国内直连不通（有代理时可用）
    必应 edge     ❌ 免费 auth 接口已返回 404，废弃
    腾讯 transmart❌ 需要注册 client_key
    LibreTranslate❌ 公共镜像全部失效
所以默认顺序是：DeepSeek（配了 Key 才用）-> 有道 -> MyMemory -> 谷歌 -> 必应 -> Argos。
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .ocr import has_cjk

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

PROVIDER_LABELS = {
    "deepseek": "DeepSeek（大模型，需 API Key）",
    "bing": "必应翻译（免费）",
    "google": "谷歌翻译（免费）",
    "youdao": "有道翻译（免费）",
    "mymemory": "MyMemory（免费）",
    "argos": "Argos 离线翻译",
}


class TranslateError(RuntimeError):
    pass


@dataclass
class Translation:
    text: str
    provider: str
    src: str
    tgt: str
    elapsed: float = 0.0


# ==========================================================================
# 方向
# ==========================================================================
def detect_direction(text: str) -> str:
    """返回 'en2zh' 或 'zh2en'。含中文就当中译英，否则当英译中。"""
    return "zh2en" if has_cjk(text) else "en2zh"


def resolve_languages(direction: str, text: str = "") -> tuple[str, str]:
    """把方向解析成 (源语言, 目标语言)，统一用 en / zh 表示。"""
    if direction == "auto":
        direction = detect_direction(text)
    if direction == "zh2en":
        return "zh", "en"
    return "en", "zh"


# ==========================================================================
# HTTP 小工具
# ==========================================================================
def _request(url: str, data: bytes | None = None, headers: dict | None = None,
             timeout: float = 12.0) -> bytes:
    hdrs = {"User-Agent": UA, "Accept-Encoding": "identity"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _get_json(url: str, params: dict | None = None, headers: dict | None = None,
              timeout: float = 12.0):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    return json.loads(_request(url, headers=headers, timeout=timeout).decode("utf-8", "replace"))


def _post_json(url: str, payload: dict | list, headers: dict | None = None,
               timeout: float = 30.0):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    return json.loads(_request(url, data=body, headers=hdrs, timeout=timeout).decode("utf-8", "replace"))


# ==========================================================================
# 长文本切分
# ==========================================================================
def _split_text(text: str, limit: int) -> list[str]:
    """按句子边界把长文本切成不超过 limit 字符的片段。"""
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    parts: list[str] = []
    for block in re.split(r"(?<=[。！？!?.\n])", text):
        if not block:
            continue
        while len(block) > limit:
            cut = block.rfind(" ", 0, limit)
            if cut < limit // 2:
                cut = limit
            parts.append(block[:cut])
            block = block[cut:]
        if block:
            parts.append(block)
    merged: list[str] = []
    for part in parts:
        if merged and len(merged[-1]) + len(part) <= limit:
            merged[-1] += part
        else:
            merged.append(part)
    return merged


def _translate_long(text: str, limit: int, func: Callable[[str], str]) -> str:
    chunks = _split_text(text, limit)
    return "\n".join(func(chunk).strip() for chunk in chunks if chunk.strip())


# ==========================================================================
# 各翻译源
# ==========================================================================
def _bing(text: str, src: str, tgt: str) -> str:
    """必应翻译的免费接口。

    注意：edge.microsoft.com/translate/auth 这个免费拿 token 的入口在 2025 年
    已经返回 404，这里保留实现只是为了有代理/接口恢复时还能用；默认顺序里排在最后。
    """
    global _bing_token
    code = {"zh": "zh-Hans", "en": "en"}[tgt]
    src_code = "" if src not in ("zh", "en") else {"zh": "zh-Hans", "en": "en"}[src]

    def call(token: str) -> str:
        url = (
            "https://api-edge.cognitive.microsofttranslator.com/translate"
            f"?api-version=3.0&from={src_code}&to={code}"
        )
        data = _post_json(url, [{"Text": text}],
                          headers={"Authorization": f"Bearer {token}",
                                   "X-ClientTraceId": ""})
        return data[0]["translations"][0]["text"]

    token, expire_at = _bing_token
    if token and time.time() < expire_at:
        try:
            return call(token)
        except Exception:
            pass
    raw = _request("https://edge.microsoft.com/translate/auth").decode("utf-8", "replace").strip()
    if not raw.startswith("ey"):          # JWT 一定以 ey 开头
        raise TranslateError("必应 token 获取失败")
    _bing_token = (raw, time.time() + 480)
    return call(raw)


_bing_token: tuple[str, float] = ("", 0.0)


def _google(text: str, src: str, tgt: str) -> str:
    """谷歌翻译的免费 gtx 接口（国内需要能访问谷歌）。"""
    tl = {"zh": "zh-CN", "en": "en"}[tgt]
    sl = {"zh": "zh-CN", "en": "en"}.get(src, "auto")

    def once(chunk: str) -> str:
        data = _get_json(
            "https://translate.googleapis.com/translate_a/single",
            {"client": "gtx", "sl": sl, "tl": tl, "dt": "t", "q": chunk},
        )
        return "".join(seg[0] for seg in data[0] if seg and seg[0])

    return _translate_long(text, 1500, once)


def _youdao(text: str, src: str, tgt: str) -> str:
    """有道翻译的公开演示接口，无需 key。"""
    frm = {"zh": "zh-CHS", "en": "en"}[src]
    to = {"zh": "zh-CHS", "en": "en"}[tgt]
    data = _get_json("https://aidemo.youdao.com/trans",
                     {"q": text, "from": frm, "to": to})
    if str(data.get("errorCode")) not in ("0", "None"):
        raise TranslateError(f"有道返回错误：{data.get('errorCode')}")
    out = data.get("translation")
    if isinstance(out, list):
        return "\n".join(out)
    if isinstance(out, str):
        return out
    raise TranslateError("有道返回格式异常")


def _mymemory(text: str, src: str, tgt: str) -> str:
    """MyMemory 免费翻译记忆库，单次请求有长度限制。"""
    pair = {"en2zh": "en|zh-CN", "zh2en": "zh-CN|en"}[f"{src}2{tgt}"]

    def once(chunk: str) -> str:
        data = _get_json("https://api.mymemory.translated.net/get",
                         {"q": chunk, "langpair": pair})
        if int(data.get("responseStatus", 0)) != 200:
            raise TranslateError(str(data.get("responseDetails")))
        return data["responseData"]["translatedText"]

    return _translate_long(text, 480, once)


DEEPSEEK_SYSTEM = (
    "你是一个专业的翻译引擎。把用户给出的内容翻译成{target}，"
    "只输出译文本身，不要解释、不要加引号、不要重复原文。"
    "保留原有的换行和专有名词。"
)


def _deepseek(text: str, src: str, tgt: str, cfg: dict) -> str:
    """走 OpenAI 兼容接口（DeepSeek / 通义 / OpenAI 都行），需要 API Key。"""
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        raise TranslateError("未配置 API Key")
    base = (cfg.get("base_url") or "https://api.deepseek.com/v1").rstrip("/")
    model = cfg.get("model") or "deepseek-chat"
    target = "简体中文" if tgt == "zh" else "英文"
    payload = {
        "model": model,
        "temperature": 0.2,
        "stream": False,
        "messages": [
            {"role": "system", "content": DEEPSEEK_SYSTEM.format(target=target)},
            {"role": "user", "content": text},
        ],
    }
    data = _post_json(f"{base}/chat/completions", payload,
                      headers={"Authorization": f"Bearer {api_key}"})
    return data["choices"][0]["message"]["content"].strip()


def _argos(text: str, src: str, tgt: str) -> str:
    """Argos Translate：完全离线的翻译模型（可选安装）。"""
    import argostranslate.translate as at

    code = {"zh": "zh", "en": "en"}[tgt]
    from_code = {"zh": "zh", "en": "en"}[src]
    return at.translate(text, from_code, code)


# ==========================================================================
# 调度
# ==========================================================================
PROVIDERS: dict[str, Callable[..., str]] = {
    "bing": _bing,
    "google": _google,
    "youdao": _youdao,
    "mymemory": _mymemory,
    "argos": _argos,
}

# 单次可发送的最大长度
LIMITS = {"bing": 1800, "google": 1500, "youdao": 1800, "mymemory": 480, "argos": 4000}


def _call(name: str, text: str, src: str, tgt: str, cfg: dict) -> str:
    if name == "deepseek":
        return _deepseek(text, src, tgt, cfg)
    func = PROVIDERS[name]
    limit = LIMITS.get(name, 1000)
    return _translate_long(text, limit, lambda chunk: func(chunk, src, tgt))


def translate(text: str, direction: str = "auto", provider: str = "auto",
              cfg: dict | None = None, order: list[str] | None = None) -> Translation:
    """翻译一段文本。

    direction : auto / en2zh / zh2en
    provider  : auto / bing / google / youdao / mymemory / deepseek / argos
    """
    text = (text or "").strip()
    if not text:
        raise TranslateError("没有拿到任何文字（截图里可能没有可识别的文本）")

    cfg = cfg or {}
    src, tgt = resolve_languages(direction, text)
    started = time.time()

    if provider != "auto":
        candidates = [provider]
    else:
        candidates = list(order or ["deepseek", "bing", "google", "youdao", "mymemory", "argos"])
        # 没填 key 就别浪费时间试大模型
        if not (cfg.get("api_key") or "").strip() and "deepseek" in candidates:
            candidates = [c for c in candidates if c != "deepseek"]

    errors: list[str] = []
    for name in candidates:
        if name not in PROVIDERS and name != "deepseek":
            continue
        if name == "argos" and not _argos_available():
            continue
        try:
            out = _call(name, text, src, tgt, cfg)
            if out and out.strip():
                return Translation(text=out.strip(), provider=name, src=src, tgt=tgt,
                                   elapsed=time.time() - started)
            errors.append(f"{name} 返回空结果")
        except Exception as exc:
            errors.append(f"{name} 失败（{type(exc).__name__}: {exc}）")

    raise TranslateError(
        f"翻译失败，{len(errors)} 个翻译源都没成功 —— " + "；".join(errors)
        + "。可以检查网络，或在 config.json 里填入 DeepSeek API Key 后重试。"
    )


def _argos_available() -> bool:
    try:
        import argostranslate.translate  # noqa: F401
        return True
    except Exception:
        return False
