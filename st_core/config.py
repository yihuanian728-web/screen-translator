"""配置读写：config.json 与本程序同目录，删掉就会恢复默认值。"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"
HISTORY_PATH = APP_DIR / "history.json"

DEFAULTS: dict[str, Any] = {
    # ---- 快捷键（改完重启生效）----
    "hotkey_selection": "ctrl+alt+z",   # 翻译「鼠标当前选中的文字」（主功能）
    "hotkey_region": "ctrl+alt+a",      # 框选屏幕区域再 OCR 翻译
    "hotkey_clipboard": "ctrl+alt+x",   # 翻译剪贴板里的文字
    # ---- 划词翻译 ----
    "auto_selection_translate": True,   # 鼠标划完词自动翻译，不用按快捷键
    "selection_mode": "auto",           # auto = UIA 优先 / uia = 只问 UIA / copy = 只用剪贴板
    "selection_copy_fallback": True,    # UIA 读不到时，允许模拟 Ctrl+C 兜底
    "selection_min_chars": 2,           # 短于这个长度不翻（免得选中一个字母就弹窗）
    "selection_max_chars": 2000,        # 超过就不翻（多半是整页全选）
    # ---- 翻译方向：auto / en2zh / zh2en ----
    "direction": "auto",
    # ---- OCR ----
    "ocr_engine": "auto",               # auto / windows / tesseract / rapidocr
    "ocr_lang_en": "en-US",
    "ocr_lang_zh": "zh-Hans-CN",
    "ocr_scale": 0,                     # 0 = 自动；>0 表示截图放大倍数（小字识别更准）
    # ---- 翻译源 ----
    "translator": "auto",               # auto / youdao / mymemory / google / bing / deepseek / argos
    "translator_order": ["deepseek", "youdao", "mymemory", "google", "bing", "argos"],
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "",                  # 填了就用大模型翻译，质量最好；留空则自动用免费接口
    },
    # ---- 界面行为 ----
    "popup": True,                      # 翻译后在鼠标旁边弹出译文小窗
    "copy_after_translate": False,      # 翻译完自动把译文放进剪贴板
    "history_size": 30,
    "font_size": 11,
}


def _deep_update(base: dict, patch: dict) -> dict:
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


class Config:
    """极简配置对象：cfg["dict_key"] 取值，cfg.set(key, value) 修改。"""

    def __init__(self, data: dict | None = None):
        self.data: dict[str, Any] = deepcopy(DEFAULTS)
        if data:
            _deep_update(self.data, data)

    # ---------- 读写 ----------
    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Config":
        if path.exists():
            try:
                return cls(json.loads(path.read_text(encoding="utf-8")))
            except Exception as exc:  # 配置坏了不该让程序起不来
                print(f"[config] 读取 {path.name} 失败，使用默认配置：{exc}")
        return cls()

    def save(self, path: Path = CONFIG_PATH) -> None:
        try:
            path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"[config] 保存失败：{exc}")

    # ---------- 访问 ----------
    def __getitem__(self, key: str) -> Any:
        return self.data.get(key, DEFAULTS.get(key))

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any, save: bool = True) -> None:
        self.data[key] = value
        if save:
            self.save()


# --------------------------------------------------------------------------
# 历史记录（简单的 json 列表）
# --------------------------------------------------------------------------
def load_history(limit: int = 30) -> list[dict]:
    if HISTORY_PATH.exists():
        try:
            data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data[:limit]
        except Exception:
            pass
    return []


def save_history(items: list[dict], limit: int = 30) -> None:
    try:
        HISTORY_PATH.write_text(
            json.dumps(items[:limit], ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass
