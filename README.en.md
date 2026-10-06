# Screen Translator — select text with your mouse, get the translation

**Highlight a piece of text anywhere on your screen with the mouse, release, and the translation pops up next to your cursor.** English → Chinese and Chinese → English are detected automatically — no language switch to fiddle with.

Windows 10 / 11 · Python 3.9+ · fully offline OCR · works without a network connection

> 中文说明见 [README.md](README.md)（更详细，含 8 条踩坑记录）

---

## Quick start

```
1. run  install.bat          -> creates .venv and installs dependencies (~1 min)
2. run  install_ocr.bat      -> offline OCR engine (recommended, see below)
3. run  start.bat            -> launches the app, it stays in the background
4. select any text with the mouse — the translation appears by itself
```

No hotkey needed. If you'd rather trigger it manually, untick "鼠标选中就翻译" in the main window and use the shortcuts.

---

## Features

| Action | What it does |
|---|---|
| **Mouse selection** (on by default) | Drag-select text in any application; on mouse-up the translation appears next to the cursor |
| `Ctrl + Alt + Z` | Manually translate the *currently selected* text |
| `Ctrl + Alt + A` | Select a screen region → screenshot → OCR → translate (for images, video subtitles, games — anything you can't select as text) |
| `Ctrl + Alt + X` | Translate whatever is in the clipboard |

The result popup: click it to copy, `Esc` or click away to close. Everything is kept in the history list of the main window.

---

## How it reads your selection

This is the interesting part. There are two paths:

```
  you drag-select text in Chrome / Word / Notepad
              │
              ▼
  ┌───────────────────────┐
  │  mousehook.py         │  SetWindowsHookEx(WH_MOUSE_LL) — a global low-level mouse hook
  │                       │  A "selection" is: button down → moved > 12px → up, taking > 60ms.
  └──────────┬────────────┘  Shorter drags are treated as plain clicks and ignored.
             ▼
  ┌───────────────────────┐  Path A (preferred): UI Automation
  │  selection.py         │    Ask Windows "what is selected in the focused control?"
  └──────────┬────────────┘    Read-only, never touches the clipboard, ~16 ms in Notepad.
             │                Path B (fallback): synthesize Ctrl+C, read the clipboard,
             │                  then restore the previous clipboard content.
             ▼                  Disabled inside explorer.exe — see "Safety" below.
  ┌───────────────────────┐
  │  translator.py        │  Contains CJK → translate to English, otherwise → to Chinese.
  └──────────┬────────────┘  Providers are tried in order and degrade gracefully:
             ▼                 DeepSeek → Youdao → MyMemory → Google → Bing → Argos
     popup next to the cursor + entry in the history list
```

### Safety

Simulating `Ctrl+C` moves the user's clipboard, and the nastiest case is selecting a few **files** in Explorer — that would silently turn into "copy files".
So the default policy is: ask UIA first, and only fall back to `Ctrl+C` when UIA returns nothing — and **never inside `explorer.exe`** (see `SKIP_COPY_PROCESSES` in `st_core/selection.py`). The fallback can be switched off from the UI.

---

## Project layout

```
screen-translator/
├── main.py                  entry point (GUI + CLI)
├── st_core/
│   ├── mousehook.py         global low-level mouse hook (ctypes + Win32)
│   ├── selection.py         read the selected text (UIA first, clipboard fallback)
│   ├── translator.py        6 translation providers with automatic fallback
│   ├── hotkey.py            global hotkeys (pure ctypes, no dependencies)
│   ├── ui.py                main window, result popup, settings dialog
│   ├── capture.py           DPI awareness, virtual desktop metrics, screen grab
│   ├── overlay.py           region-selection overlay for screenshot translation
│   ├── ocr.py               3 OCR backends (RapidOCR / Windows / Tesseract)
│   ├── pipeline.py          glues capture → OCR → translate + environment doctor
│   └── config.py            configuration and history
└── tools/                   automated tests (see below)
```

Core logic is ~1,100 lines of Python; the rest is tests.

### Command line

```bat
python main.py                   launch the GUI
python main.py --selection       translate the currently selected text and print it
python main.py --text "hello"    translate a string
python main.py --image shot.png  OCR + translate an image
python main.py --doctor          environment report (UIA, OCR language packs, providers)
python main.py --selftest        offline test: render sample images → OCR → detect direction
python main.py --selection-test  test selection reading against Notepad
python main.py --selection-e2e   synthesize a real mouse drag and verify auto-translation
python main.py --e2e             screenshot translation end-to-end test
```

---

## Configuration

`config.json` is generated on first run and is git-ignored (it may hold your API key).

| Key | Default | Meaning |
|---|---|---|
| `auto_selection_translate` | `true` | Translate as soon as a selection is made |
| `hotkey_selection` | `ctrl+alt+z` | Translate the current selection |
| `hotkey_region` | `ctrl+alt+a` | Screenshot translation |
| `selection_mode` | `auto` | `auto` (UIA first) / `uia` / `copy` |
| `selection_copy_fallback` | `true` | Allow the Ctrl+C fallback |
| `direction` | `auto` | `auto` / `en2zh` / `zh2en` |
| `ocr_engine` | `auto` | `auto` / `rapidocr` / `windows` / `tesseract` |
| `translator` | `auto` | `auto` / `youdao` / `mymemory` / `google` / `bing` / `deepseek` / `argos` |
| `deepseek.api_key` | empty | **Leave it empty and nothing is ever billed.** Filling it in routes translations through the DeepSeek API, which is charged per token |
| `deepseek.model` | `deepseek-flash` | Current model name (the old `deepseek-chat` is no longer in the price list) |

### Does it cost anything?

**By default, no.** The free providers (Youdao / MyMemory) are public endpoints and cost nothing.

If you put a DeepSeek API key in, translations go through the paid API and are billed per token against your account balance — pay-as-you-go, not a subscription. With `deepseek-flash` a typical selection is roughly 100 input + 40 output tokens ≈ **¥0.0005 per lookup**, so about ¥0.5 per thousand lookups (half price during off-peak hours). See the [official price list](https://api-docs.deepseek.com/quick_start/pricing).

Without a key the app skips DeepSeek entirely and only uses the free providers.

---

## Why another translator?

Yes, [STranslate](https://github.com/ZGGSONG/STranslate), [POT](https://github.com/pot-app/pot-app), [eSearch](https://github.com/djun/eSearch) and the [selection translator browser extension](https://github.com/Selection-Translator/crx-selection-translate) all exist and are more polished. This one is deliberately small: ~1,100 lines you can actually read, with the OCR engine and the translation providers as pluggable functions. It was written as a course project, and the README (Chinese) documents the eight real bugs that were hit along the way — the DPI trap, the pywinrt/onnxruntime load-order crash, the 32-bit handle truncation, and so on.

---

## Testing

There is no "should work" here — everything below was actually executed:

```
[doctor]     default OCR: rapidocr; UIA: uiautomation 2.0.29 available
             Youdao ✅ 240ms   MyMemory ✅ 1.4s   Google ❌ reset   Bing ❌ 404

[selftest]   English sample similarity 1.00, direction en2zh ✅
             Chinese sample similarity 1.00, direction zh2en ✅

[smoke]      main window ✅  mouse hook registered ✅  popup ✅  settings ✅

[selection]  UIA read 16ms ✅   clipboard fallback 61ms ✅ and the clipboard was restored ✅

[selection-e2e]  synthesized mouse drag → hook fired → read 'The quick brown fox…'
                 → translated to「敏捷的棕色狐狸跳过了懒惰的狗。」(youdao, 274ms) ✅
```

> The end-to-end tests synthesize real input, so your mouse pointer will move for a second or two while they run.

---

## Known limitations

- **UIA needs the target app to support it.** Chrome/Edge may need a few seconds the first time while they enable accessibility. For stubborn apps, enable the Ctrl+C fallback.
- **Windows' built-in OCR only knows the languages installed in the system.** Most Chinese PCs have no English OCR pack, and English then comes out as `b rown (0)<`. RapidOCR ships its own Chinese+English models and scores 1.00 in our tests — that's why `install_ocr.bat` is recommended.
- **The free translation endpoints die over time.** Bing's public token endpoint now returns 404, Google is unreachable from mainland China, and every public LibreTranslate mirror we tried was down. That's why providers are a list with fallback.
- **Windows only.** The mouse hook, UI Automation and WinRT OCR are all Win32-specific.

---

## License

MIT — see [LICENSE](LICENSE).
