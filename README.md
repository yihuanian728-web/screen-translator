# 屏幕翻译器 · 划词即译

**用鼠标选中一段文字，松手就出译文。** 英文自动译成中文，中文自动译成英文，方向不用手动切。

Windows 10 / 11 · Python 3.9+ · 全离线 OCR · 不联网也能识别

```
你：用鼠标把网页上那句英文划一下
它：0.3 秒后，鼠标旁边弹出「敏捷的棕色狐狸跳过了懒惰的狗。」
```

---

## 一、30 秒上手

```
1. 双击   install.bat         （创建 .venv 装依赖，约 1 分钟）
2. 双击   install_ocr.bat     （强烈建议，见第六节；约 100-200MB）
3. 双击   start.bat           （启动后可以最小化，程序常驻后台）
4. 去任何程序里用鼠标选中文字 —— 译文自动弹出来
```

> 脚本名统一用英文（`install`=装依赖，`install_ocr`=装离线 OCR，`start`=启动，`doctor`=自检，`test`=跑测试，`debug`=带控制台启动），方便英文用户也能直接上手。

启动后**不需要按任何键**，选中即翻译。如果不想自动弹，把主界面上的「鼠标选中就翻译」取消勾选，改用快捷键。

---

## 二、四种用法

| 操作 | 说明 |
|---|---|
| **鼠标划词**（默认开启） | 在任意程序里用鼠标拖选文字，松开即翻译，译文浮窗出现在鼠标旁边 |
| `Ctrl + Alt + Z` | 手动翻译「当前选中的文字」（自动模式关掉后用这个，或 UIA 没读到时补一刀） |
| `Ctrl + Alt + A` | 框选屏幕区域 → 截图 → OCR → 翻译（对付图片、视频字幕、游戏画面这类选不中文字的场景） |
| `Ctrl + Alt + X` | 翻译剪贴板里的文字 |

译文浮窗：点一下复制译文，`Esc` 或点别处关掉。所有记录都进主界面的历史列表，双击可重新载入。

---

## 三、它是怎么「读到」你选中的文字的

这是整个项目的核心，两条路：

```
  你在 Chrome / Word / 记事本里拖选一段文字
              │
              ▼
  ┌───────────────────────┐
  │  mousehook.py         │  SetWindowsHookEx(WH_MOUSE_LL) 全局低级鼠标钩子
  │  低级鼠标钩子          │  监听：按下 → 拖动 → 松开；位移 > 12px 且耗时 > 60ms
  └──────────┬────────────┘  才判定为「划词」，否则只是普通点击
             ▼
  ┌───────────────────────┐
  │  selection.py         │  路径 A（首选）：UI Automation
  │  读取选中的文字        │     问系统「当前焦点控件里选中了什么」
  └──────────┬────────────┘     只读，不碰剪贴板、不模拟按键，16ms 出结果
             │                  路径 B（兜底）：模拟 Ctrl+C 读剪贴板
             │                     读完把剪贴板恢复原样；资源管理器里禁用（见下）
             ▼
  ┌───────────────────────┐
  │  translator.py        │  含汉字 → 中译英，否则 → 英译中（自动判方向）
  │  自动选翻译源          │  按顺序试：DeepSeek → 有道 → MyMemory → 谷歌 → 必应 → Argos
  └──────────┬────────────┘
             ▼
     鼠标旁边弹出译文浮窗 + 写进历史记录
```

**为什么优先用 UIA 而不是 Ctrl+C？**
模拟 Ctrl+C 虽然兼容性最好，但它会动用户的剪贴板。最难受的场景是在资源管理器里拖选几个文件 —— 一按 Ctrl+C 就变成「复制文件」，又吓人又危险。
所以默认策略是：先问 UIA（记事本实测 16ms 拿到选区），UIA 读不到时才用 Ctrl+C 兜底，而且**在 explorer.exe 里直接禁用兜底**（`selection.py` 里的 `SKIP_COPY_PROCESSES`）。
兜底开关在主界面上有复选框，叫「读不到时用复制兜底」，随时可以关掉。

---

## 四、界面

```
┌ 屏幕翻译器 · 划词即译 ────────────────────────────────────────┐
│ [🖱 划词翻译] [✂ 截图翻译] [📋 剪贴板] [⇄ 反向]  [🩺自检][⚙设置]│
│ 方向[auto▾] OCR[auto▾] 翻译源[auto▾] ☑鼠标选中就翻译 ☑复制兜底 │
├──────────────────────────┬───────────────────────────────────┤
│ 原文（可编辑）            │ 译文                               │
│ The quick brown fox...   │ 敏捷的棕色狐狸跳过了懒惰的狗。      │
├──────────────────────────┴───────────────────────────────────┤
│ [复制译文] [用原文重新翻译] [清空]      ☑弹译文小窗 ☐自动复制   │
├──────────────────────────────────────────────────────────────┤
│ 历史记录（双击载入）                                           │
├──────────────────────────────────────────────────────────────┤
│ 完成（youdao · 274ms）                                        │
└──────────────────────────────────────────────────────────────┘
```

窗口尺寸会跟着屏幕分辨率走（高 DPI 缩放下字体是成倍放大的，写死尺寸会把工具栏挤掉）。

---

## 五、先回答「有没有人做过」

有，而且不少。我把现成的看了一圈：

| 项目 | 形态 | 划词翻译 | 截图翻译 | 说明 |
|---|---|---|---|---|
| [划词翻译](https://github.com/Selection-Translator/crx-selection-translate) | 浏览器扩展 | ✅ | ❌ | 只翻网页，翻不了桌面软件、PDF 阅读器、视频字幕 |
| [STranslate](https://github.com/ZGGSONG/STranslate) | WPF 桌面端 | ✅ | ✅ | 国内口碑最好，多翻译源可插拔，功能齐全 |
| [POT](https://github.com/pot-app/pot-app) | 跨平台桌面端 | ✅ | ✅ | 插件化，UI 现代 |
| [eSearch](https://github.com/djun/eSearch) | Electron | ✅ | ✅ | 截屏 OCR + 搜索 + 翻译 + 贴图 + 录屏 |
| [欧路词典 / 有道词典](https://www.eudic.net/) | 商业软件 | ✅ | ✅ | 划词做得最成熟 |
| `Ctrl+C` + 网页翻译 | 土办法 | ✅ | ❌ | 每次都要手动复制粘贴 |

**结论：轮子确实有。** 自己写一个的理由：

1. 上面这些都装完就是几百 MB（Electron/WPF/词典全家桶）。这个项目 **核心 5 个 Python 文件、约 1100 行**，看得懂、改得动，适合当课程作品讲清楚原理。
2. 翻译源和 OCR 引擎都是可插拔的小函数，换自己的接口只要改十几行。
3. 顺手踩了一遍真正的坑（第六节），这些坑比功能本身更值得写进报告。

---

## 六、踩坑记录（建议写进报告）

### 1. 中文批处理文件会把 cmd 解析器搞崩

`start.bat` 里写了中文注释和 echo，结果双击时控制台刷出一堆：

```
'thonw.exe" (' is not recognized as an internal or external command
'1' is not recognized as an internal or external command
```

cmd.exe 是按字节读取批处理文件的，UTF-8 的中文字符（3 字节）+ 中途 `chcp 65001` 会让它读串位置，
把 `start "" "...pythonw.exe" "main.py"` 这行拆成几段乱码去执行 —— **程序自然起不来**。
后来把所有 .bat 全改成纯 ASCII 内容（文件名保留中文），问题彻底消失。

### 2. 64 位下 ctypes 不声明 restype，句柄会被截断成 32 位

```python
kernel32.GetModuleHandleW(None)          # 默认 restype = c_int（4 字节）
```
64 位下 HMODULE 是 8 字节，返回值被截断，`SetWindowsHookEx` 拿着残缺的句柄去注册，
报 **错误码 126（找不到模块）**，鼠标钩子一直起不来。
所有返回句柄的 API（`GetModuleHandleW` / `SetWindowsHookExW` / `OpenProcess`）都必须显式声明
`restype = c_void_p`，`argtypes` 也要一起写对。

### 3. 系统自带 OCR 只认装过的语言，缺英文包时英文被认成乱码

这台电脑的 Windows OCR 只有 `zh-Hans-CN`，用它认英文的结果：

```
期望：The quick brown fox jumps over the lazy dog.
实得：The quick b rown (0)<Jumps ove r the lazy dog.      ← fox 认成了 (0)<
```

实测对比（`python -m tools.bench_ocr`）：

| 引擎 | 英文相似度 | 中文相似度 | 耗时 |
|---|---|---|---|
| Windows 自带（仅中文包） | 0.90 ~ 0.99 | 1.00 | 30 ~ 100ms |
| RapidOCR（离线自带模型） | **1.00** | **1.00** | 0.6 ~ 1.5s |

所以 auto 模式默认优先 RapidOCR。虽然划词翻译用不到 OCR，但截图翻译要靠它。

### 4. pywinrt 和 onnxruntime 的加载顺序会让进程直接消失

```python
import winrt.windows.media.ocr   # 先加载 pywinrt
import onnxruntime               # 再加载 onnxruntime
→ 0xC0000005 访问违例，没有任何 Python 异常，进程直接没了
```

反过来先 `import onnxruntime` 就正常。解决办法是在 `ocr.py` 导入阶段就把 onnxruntime 拉起来，把顺序钉死。
**教训：两个带原生 DLL 的库撞车时，症状往往是没有堆栈的崩溃，只能靠二分法定位。**

### 5. 高 DPI 缩放下「写死的窗口尺寸」会被挤爆

这台机器是 2560×1600、150% 缩放，Tk 的 `scaling` 是 2.0 —— 11pt 的字实际占 30 像素高。
原来把窗口写死成 900×600，一测「内容请求宽度 **2168px**」，工具栏右边的按钮全被挤出屏幕。
现在窗口尺寸按屏幕比例算，工具栏也拆成两行。

### 6. 「双击了没反应」的三种真实原因

排查这个问题花的时间比写功能还多，结论值得记下来：
1. 批处理被中文搞崩（上面第 1 条）—— 脚本根本没执行到启动那行；
2. 程序其实启动了，但窗口被**前台窗口锁**挡住，躲在最大化的浏览器后面 —— 现在启动时会主动 `lift` + 短暂置顶；
3. 重复双击启动了第二个实例 —— 现在第二次双击会把已有窗口切到前台，不再开新进程。

### 7. 免费翻译接口是会死的

实测（国内宽带，无代理）：

| 源 | 结果 |
|---|---|
| 有道 `aidemo.youdao.com/trans` | ✅ 免 key，200-400ms，最快 |
| MyMemory | ✅ 免 key，约 1s |
| 谷歌 `translate.googleapis.com` | ❌ 国内直连被重置（有代理可用） |
| 必应 `edge.microsoft.com/translate/auth` | ❌ 返回 404，免费 token 入口已废弃 |
| 腾讯 transmart | ❌ 需要注册 client_key |
| LibreTranslate 公共镜像 | ❌ 试了三个全部失效 |

所以程序不绑定任何单一接口：翻译源做成列表逐个降级，界面上标出实际用的是哪个。
要稳定就填一个 API Key（设置里填 DeepSeek），或者装 Argos 做完全离线翻译。

### 8. 中文 Windows 控制台是 GBK，`print("✅")` 会把程序打挂

`UnicodeEncodeError: 'gbk' codec can't encode character '\u2705'`。
现在统一在启动时 `sys.stdout.reconfigure(errors="replace")`，打不出来的字符降级成 `?`，不再抛异常。

---

## 七、项目结构

```
screen-translator/
├── main.py                  入口（GUI + 命令行）
├── st_core/
│   ├── mousehook.py         全局低级鼠标钩子：判断「用户刚划完词」
│   ├── selection.py         读取选中的文字（UIA 优先 / 剪贴板兜底）
│   ├── translator.py        六个翻译源 + 自动降级 + 中英方向判断
│   ├── hotkey.py            全局快捷键（纯 ctypes 调 Win32）
│   ├── ui.py                主界面、译文浮窗、设置窗口
│   ├── capture.py           DPI 感知、虚拟桌面尺寸、屏幕抓图
│   ├── overlay.py           截图翻译用的框选遮罩
│   ├── ocr.py               三个 OCR 后端 + 自动降级
│   ├── pipeline.py          串起流水线 + 环境自检
│   ├── config.py            配置与历史记录
│   └── console.py           控制台编码兜底
├── tools/
│   ├── selection_test.py    划词读取测试（拿记事本当靶子）
│   ├── selection_e2e.py     划词端到端：合成真实鼠标拖拽，验证自动翻译
│   ├── e2e_test.py          截图端到端：真开窗口真截图
│   ├── selftest.py          离线自测：样图 → 识别 → 方向判断
│   └── bench_ocr.py         对比不同 OCR 引擎 / 放大倍数的准确率
├── requirements.txt         必需依赖（Pillow + uiautomation + Windows OCR 绑定）
├── requirements-optional.txt 可选依赖（离线 OCR / 离线翻译 / Tesseract）
├── config.example.json      配置示例
├── install.bat / install_ocr.bat / start.bat / debug.bat / doctor.bat / test.bat
├── README.en.md             英文说明
└── README.md
```

### 命令行用法

```bat
python main.py                      启动图形界面
python main.py --selection          翻译「当前鼠标选中的文字」并打印（划词翻译的命令行版）
python main.py --text "hello"       直接翻译一段文字
python main.py --pick               只框选一次，结果打到控制台
python main.py --image shot.png     翻译一张图片里的文字
python main.py --doctor             环境自检（UIA、OCR 语言包、各翻译接口连通性）
python main.py --selftest           离线自测
python main.py --selection-test     划词读取测试（会开一下记事本）
python main.py --selection-e2e      划词端到端测试（合成鼠标拖拽，指针会动一下）
python main.py --e2e                截图端到端测试
python main.py --smoke              界面冒烟测试
```

---

## 八、配置（config.json）

第一次运行自动生成，删掉就恢复默认。界面上的下拉框和复选框改的就是它。

| 字段 | 默认值 | 说明 |
|---|---|---|
| `auto_selection_translate` | `true` | 鼠标划完词自动翻译 |
| `hotkey_selection` | `ctrl+alt+z` | 手动翻译选中文字的快捷键 |
| `hotkey_region` | `ctrl+alt+a` | 截图翻译快捷键 |
| `selection_mode` | `auto` | `auto` UIA 优先 / `uia` 只问 UIA / `copy` 只用剪贴板 |
| `selection_copy_fallback` | `true` | UIA 读不到时允许模拟 Ctrl+C |
| `selection_min_chars` | `2` | 短于这个长度不翻（避免选中一个字母就弹窗） |
| `selection_max_chars` | `2000` | 超过就不翻（多半是整页全选） |
| `direction` | `auto` | `auto` 自动判方向 / `en2zh` / `zh2en` |
| `ocr_engine` | `auto` | `auto` / `rapidocr` / `windows` / `tesseract` |
| `translator` | `auto` | `auto` / `youdao` / `mymemory` / `google` / `bing` / `deepseek` / `argos` |
| `deepseek.api_key` | 空 | 填了就优先用大模型翻译（质量明显更好） |
| `popup` | `true` | 弹译文小窗 |
| `copy_after_translate` | `false` | 翻译完自动复制译文 |

---

## 九、实测结果

在作者的机器（Windows 11 26200 / Python 3.12 / 2560×1600 @150% / 无代理）上，`test.bat` 全绿：

```
[环境自检]  默认 OCR: rapidocr     UIA: uiautomation 2.0.29 可用
            有道 ✅ 240ms   MyMemory ✅ 1.4s   谷歌 ❌ 连接被重置   必应 ❌ 404

[离线自测]  英文图识别相似度 1.00，方向 en2zh ✅
            中文图识别相似度 1.00，方向 zh2en ✅

[界面冒烟]  主窗口 ✅  鼠标钩子 已启动 ✅  译文浮窗 ✅  设置窗口 ✅

[划词读取]  UIA 读选区 16ms，拿到整段中英文 ✅
            剪贴板兜底 61ms ✅ 且读完把剪贴板恢复原样 ✅

[划词端到端] 合成真实鼠标拖拽 → 钩子触发 → 读到 'The quick brown fox...'
            → 译文「敏捷的棕色狐狸跳过了懒惰的狗。」(youdao, en2zh) ✅

[截图端到端] 框选遮罩坐标与期望完全一致 ✅
            真窗口截图 760×130 → 识别相似度 1.00 → 译文「屏幕区域翻译作品。」✅
```

**耗时实测**：划词全流程约 **0.3 秒**（读选区 16ms + 翻译 220-400ms）。
截图翻译多一步 OCR，约 1 秒。

> 端到端测试会用 SendInput 合成真实的鼠标拖拽，运行期间你的鼠标指针会被程序挪动一两秒，属正常现象。

---

## 十、常见问题

**Q：选中文字了，但什么都没弹出来？**
1. 看主界面状态栏：如果写着「没读到选中的文字」，说明这个程序不支持 UIA。勾上「读不到时用复制兜底」再试。
2. 如果连状态栏都没变，说明鼠标钩子没抓到这次拖拽 —— 拖得太短（小于 12px）会被当成普通点击，多拖一点。
3. Chrome / Edge 第一次可能要给几秒开启无障碍支持，之后就好了。

**Q：会不会在我拖窗口、拖文件的时候乱翻？**
拖窗口/拖文件时 UIA 读不到文本，所以不会翻译；而且复制兜底在 `explorer.exe` 里是直接禁用的，不会把你的文件复制到剪贴板。

**Q：翻译结果很生硬？**
免费接口都是机器翻译。填一个 DeepSeek API Key（设置里），质量会明显提升。同一句 "The quick brown fox jumps over the lazy dog."，网易有道给「敏捷的棕色狐狸跳过了懒惰的狗。」

**Q：英文识别出来是 `b rown (0)<` 这种乱码？（截图翻译时）**
系统缺英文 OCR 语言包。跑 `install_ocr.bat`，或到「设置 → 时间和语言 → 语言和区域 → English (United States) → 语言选项」勾上「光学字符识别」。
`python main.py --doctor` 会告诉你缺哪个。

**Q：双击 start.bat 好像没反应？**
现在有三种情况都处理过了：脚本乱码（已修）、窗口躲在浏览器后面（启动时会置顶）、重复启动（会把已有窗口切到前台）。
如果还是不行，双击 `debug.bat`，它会保留控制台窗口，报错看得见。

**Q：能翻译图片、PDF 扫描件、视频字幕吗？**
能，用 `Ctrl+Alt+A` 框选那块区域，走截图 + OCR。

---

## 十一、还可以怎么改

- **悬停取词**：鼠标停在单词上不动 0.5 秒就查词（再挂一个定时器 + `WindowFromPoint`）。
- **翻译源插件化**：把 `PROVIDERS` 改成从 `plugins/` 目录动态加载。
- **术语表**：翻译前替换专有名词，翻完换回来，解决人名/产品名被乱翻。
- **托盘图标**：`pystray` 加个托盘菜单，彻底不留窗口在任务栏。
- **打包 exe**：`pyinstaller --noconsole` 打包，发给同学不用装 Python。
- **朗读**：接 Windows 自带语音合成，译文直接读出来。

---

## 十二、依赖与许可

- 必需：`Pillow`、`uiautomation`、`winrt-*`（Windows 自带 OCR 的 Python 绑定）
- 可选：`rapidocr-onnxruntime`（离线 OCR，**建议装**）、`pytesseract`、`argostranslate`（离线翻译）
- 本项目代码可自由用于学习、课程作业与二次开发。
- 翻译接口均为各服务方的公开接口，请遵守其使用条款，不要拿去做批量抓取。
