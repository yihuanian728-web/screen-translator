"""屏幕翻译器核心包。

模块划分：
    capture    屏幕截图 / DPI 处理
    overlay    鼠标框选区域的半透明遮罩层
    ocr        文字识别（Windows 自带 OCR / Tesseract / RapidOCR）
    translator 翻译（必应 / 谷歌 / 有道 / MyMemory / DeepSeek / Argos 离线）
    hotkey     全局快捷键
    pipeline   把「截图 -> 识别 -> 翻译」串起来
    config     配置读写
    ui         图形界面
"""

__version__ = "1.0.0"
__all__ = ["capture", "overlay", "ocr", "translator", "hotkey", "pipeline", "config", "ui"]
