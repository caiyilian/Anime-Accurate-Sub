# Anime Accurate Sub 桌面版完整使用教程

本文说明如何用 Electron 桌面版处理一个完全没有现成中文字幕的动漫 MP4，也说明如何使用日文外挂字幕、系列记忆、术语表、多 Agent 审查、MQM 和断点续传。桌面版只是现有 Python CLI 的安全图形外壳；翻译、ASR、审查和字幕生成仍由 scripts/anime_sub.py 完成。

## 先说结论：不需要字幕组译文

生产流程只需要视频。可选的日文 SRT/ASS/VTT 只负责提供更可靠的日语时间轴；没有日文字幕时，程序会提取音频并使用 Anime Whisper ASR。人工中文字幕组文件只用于离线评测、抽样比对和发现差异，绝不能作为未知作品生成字幕的前置依赖。

~~~text
MP4
  ├─ 日文外挂/内嵌字幕（有则优先）
  └─ 没有字幕 → FFmpeg → Anime Whisper 日语 ASR
       ↓
远程 Sakura-14B（上下文、系列记忆、术语表、翻译记忆）
       ↓
五角色多 Agent 审查 + 保守总编
       ↓
Flash Lite + DeepSeek 双裁判 GEMBA-MQM
       ↓
SRT/ASS → 规则质量检查 → libass 烧录 MP4
~~~

## 一、准备运行环境

### 1. Python 和 FFmpeg

Windows 10/11 x64 上准备 Python 3.11 或更高版本、带 ass/subtitles 滤镜的 FFmpeg，以及项目 Python 依赖：

~~~powershell
Set-Location E:\projects\Anime-Accurate-Sub
Test-Path .venv\Scripts\python.exe
ffmpeg -hide_banner -filters | Select-String ass
~~~

如果要建立独立环境：

~~~powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
~~~

没有带 libass 的 FFmpeg 仍可以生成 SRT/ASS，但不能生成硬字幕 MP4。可优先使用仓库已验证的 .omo\ffmpeg-libass 构建，或者把对应目录加入 PATH。

### 2. Sakura 和 SenseNova

默认质量优先配置使用：

- 翻译：172.31.102.189 的 crosery/sakura-14b-qwen2.5-v1.0-q6k:latest；
- 翻译格式异常时：同服务器的 crosery/GalTransl-7B-v2.6:Q6_k；
- 五 Agent/MQM：SenseNova Flash Lite 与 DeepSeek 双裁判。

检查 Sakura 服务：

~~~powershell
Invoke-RestMethod http://172.31.102.189:11434/api/tags -TimeoutSec 30
~~~

将 SenseNova API Key 放入项目根目录的 config\sensenova_apikeys，每行一个 Key。本机当前配置是 6 行，程序会轮询账号；不要在命令行、教程、日志、Issue 或 Git 中粘贴真实 Key。该文件已被 Git 忽略，NSIS 安装包也会明确排除它。

### 3. 可选的系列资料

完全新作品可以不提供系列记忆和术语表，但质量优先时建议建立系列记忆 JSON、术语表 JSON 和翻译记忆 JSONL。格式可参考 data\series_memory\k-on_s1.json 和 data\glossary\k-on_glossary.json。

## 二、安装桌面版

仓库内已经生成的安装器位于：

~~~text
E:\projects\Anime-Accurate-Sub\desktop\release\Anime Accurate Sub-Setup-0.1.0-x64.exe
~~~

双击安装器并选择一个有写权限的用户目录。安装器是 per-user NSIS 安装，不需要把密钥打进安装包；卸载默认保留用户设置和输出，避免误删成品。卸载时从 Windows“应用和功能”或安装目录中的 Uninstall Anime Accurate Sub.exe 执行。

安装包带有安全的 resources\backend：核心 Python 脚本、无密钥配置模板和 pyproject.toml。它不带 GitHub token、SenseNova Key、模型、视频或既有输出。要使用完整项目能力，建议在设置中把“项目根目录”指向本仓库；这样可以复用 .venv、.omo 模型和仓库配置，同时安装版仍会优先找到自身的后端资源作为回退。

## 三、第一次启动与设置

1. 启动 Anime Accurate Sub，等待顶部状态变为 READY。
2. “项目根目录”选择 E:\projects\Anime-Accurate-Sub。
3. “Python 路径”选择 E:\projects\Anime-Accurate-Sub\.venv\Scripts\python.exe，或选择已经安装项目依赖的 Miniconda Python。
4. 输出目录按作品单独建立，例如 E:\projects\Anime-Accurate-Sub\output\某部作品。
5. 翻译后端选择 sakura；ASR 选择 anime_whisper；ASS 样式按需要选择。
6. 勾选“质量检查”“五 Agent 审查”“GEMBA-MQM”“优先日文字幕”。
7. “翻译配置 JSON”选择 config\translator.sakura-remote.example.json。
8. 连续剧建议同时选择系列记忆、术语表和共享翻译记忆；新作品没有这些文件时留空即可。
9. 点击“保存配置”，确认项目根目录、Python、FFmpeg 和两份 SenseNova 配置均为 OK。

桌面版只通过 Preload 白名单 IPC 与主进程通信，渲染进程没有 Node.js、文件系统或启动进程权限。实际 Python 命令始终以参数数组启动，命令预览只是显示用途，不经过 shell 拼接。

## 四、加入视频和日文字幕

可以点击视频区域选择 MP4/MKV，也可以把文件拖入队列。主进程会再次检查扩展名、绝对路径、文件存在性和常规文件类型；队列最多 100 个视频，同一视频会去重。

有可靠日文字幕时，把与当前片源严格一致的 .ja.srt、.ja.ass 或 .ja.vtt 拖入视频条目，或点击该条目的“附加日文字幕”。字幕必须来自同一个无广告/同片头版本；作品和集数相同但片源不同会导致时间轴整体偏移。

没有任何日文字幕时，不需要额外操作，保留“优先日文字幕”。程序会先检查外挂字幕和内嵌文本轨，找不到时自动走“FFmpeg 提取音频 → Anime Whisper → 日语时间轴 → Sakura 翻译”。

## 五、启动、观察和取消

点击“开始完整流程”后，桌面版会按队列顺序启动 Python，每次只运行一个视频，避免多个 ASR 或 Ollama 任务争抢 GPU。进度面板显示当前阶段、阶段百分比、总体百分比和状态；日志面板显示 stdout/stderr，并对异常高频日志限流但保留计数。

阶段通常依次为 japanese_subtitle 或 extract_audio + asr、translate、multi_agent_review、mqm_quality_review、subtitle、embed_subtitle、quality_check。

点击“取消并保留断点”会终止当前 Python/FFmpeg 进程树，但不会删除工作目录、checkpoint、翻译结果或审查进度。重新打开桌面版，保持同一个视频、项目根目录和输出目录，点击“继续未完成任务”即可复用已完成阶段。不要为了继续而换输出目录；要做模型或参数对比时建立新的输出目录。

## 六、查看结果和导出日志

任务结束后在“成品与阶段产物”面板点击“刷新结果”。每个视频卡片提供：

- SRT/ASS：通过受控 IPC 读取，文本有 2 MiB 上限并严格验证 UTF-8；
- 嵌字 MP4：通过 aas-media 安全协议在原生 video 控件播放，不把绝对路径交给渲染进程；
- 质量报告、五 Agent 报告、MQM 报告和阶段 JSON：按 artifact ID 读取；
- “打开目录”：只打开登记过的任务工作目录；
- “导出运行日志”：使用原生保存对话框写出完整运行日志。

单集工作目录通常如下：

~~~text
output\某部作品\第01集\
├─ checkpoint.json
├─ japanese_source.srt / japanese_source.json
├─ asr_results.json
├─ translated.json
├─ reviewed.json
├─ mqm_reviewed.json
├─ multi_agent_review.json
├─ mqm_quality_report.json
├─ 第01集.srt
├─ 第01集.ass
├─ 第01集_subs.mp4
└─ quality_report.json
~~~

*_subs.mp4 是已经烧录中文字幕的交付视频；SRT/ASS 是可继续校对和重新烧录的源文件。

## 七、如何处理 needs_review

needs_review 是保守质量门，不是流水线失败。它表示裁判意见冲突、置信度不足或候选修订没有达到自动应用阈值。没有参考字幕的新作品同样可以完整生成；参考字幕只用于离线评测，不应被反馈给生成阶段。

先查看 mqm_quality_report.json 的上下文、日文原文、当前中文、两个裁判意见和总编建议，再决定保留当前译文或人工修改。需要系统化校对时：

~~~powershell
$work = E:\projects\Anime-Accurate-Sub\output\某部作品\第01集
python -X utf8 scripts\proofread.py export --input "$work\mqm_reviewed.json" --quality-report "$work\mqm_quality_report.json" --output "$work\proofread_sheet.json" --only-review
python -X utf8 scripts\proofread.py apply --input "$work\mqm_reviewed.json" --sheet "$work\proofread_sheet.json" --history "$work\proofread_history.jsonl" --operator 你的名字 --regenerate --subtitle-base "$work\第01集"
~~~

应用后重新检查 SRT/ASS、质量报告和烧录视频。若要保留原始候选，输出到新的文件名或新的版本目录，不要覆盖唯一副本。

## 八、从零处理未知动漫 MP4 的清单

1. 准备 Python、FFmpeg、Anime Whisper 模型、Sakura 服务和 SenseNova Key。
2. 启动桌面版，设置项目根目录、Python、输出目录和 Sakura 配置。
3. 勾选质量检查、五 Agent、MQM、优先日文字幕。
4. 有同片源日文字幕就附加；没有就直接加入 MP4。
5. 保存配置并启动。
6. 等待结果卡片出现，播放 *_subs.mp4，打开 SRT/ASS 和质量报告。
7. 逐条处理 needs_review；确认无误后交付 MP4 + SRT + ASS + 报告。

## 九、开发者重新打包

在 desktop 目录执行：

~~~powershell
$env:ELECTRON_MIRROR = https://npmmirror.com/mirrors/electron/
npm ci
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
npm run smoke
~~~

生成 NSIS：

~~~powershell
$env:ELECTRON_BUILDER_BINARIES_MIRROR = https://npmmirror.com/mirrors/electron-builder-binaries/
$env:CSC_IDENTITY_AUTO_DISCOVERY = false
npm run package
npm run verify:release
~~~

发布前必须看到 RELEASE_SECRET_SCAN_OK，并用隔离 userData 启动一次安装版 smoke；不要把 release、输出目录或任何 Key 文件提交到 Git。

## 十、常见故障

| 现象 | 处理 |
|---|---|
| READY 不是 OK | 检查项目根目录、Python、FFmpeg 和两个质量配置路径 |
| Sakura 超时/500 | 检查 172.31.102.189:11434，恢复后用同一输出目录继续 |
| SenseNova 429 | 确认 config\sensenova_apikeys 每行一个有效 Key，等待窗口恢复后继续 |
| 找不到模型 | 设置 ANIME_WHISPER_MODEL，确认 CT2 目录含 model.bin、tokenizer.json |
| SRT 有但没有嵌字视频 | 检查 FFmpeg 是否包含 ass/subtitles 滤镜 |
| 字幕整体错位 | 确认日文字幕和 MP4 是同一片源，尤其是广告、删减和 OP/ED 长度 |
| 重跑没有变化 | checkpoint 正常生效；需要参数对比时使用新输出目录 |
| 安装版找不到 Python | 在设置中指定已经安装依赖的 Python；安装包不捆绑模型和 Python 虚拟环境 |

## 十一、已验证的成品位置

《轻音少女》第一季无广告片源的完整历史成品仍在：

~~~text
E:\projects\Anime-Accurate-Sub\.omo\season_v6_quality
~~~

D7 桌面真实 60 秒验收成品在：

~~~text
E:\projects\Anime-Accurate-Sub\output\desktop-test\pipeline-run-20260801-123354\k-on-d7-60s
~~~

该目录已验证 21 条 SRT/ASS 字幕、60.083 秒且含 H.264 视频和 AAC 音频的嵌字 MP4、质量报告、五 Agent/MQM 报告和完整 checkpoint；MQM 对其中 4 条保守标记 needs_review，这是等待人工裁决的质量门，不影响管线成功或成品播放。
