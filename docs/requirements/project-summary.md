# Anime Accurate Sub — 项目背景与调研总结

> 本文档用于向外部大模型提供完整的项目上下文，以便获得优化建议、功能补充和遗漏项目调研。

---

## 1. 项目背景

### 1.1 为什么做这个项目

我经常看日语动漫，但很多番剧没有中文字幕。现有解决方案：

| 方案 | 问题 |
|------|------|
| 浏览器自动字幕翻译（如 YouTube） | 翻译错误率高，尤其是动漫角色名、语气词、专有名词 |
| 找现成字幕 | 冷门番剧/新番根本没人做字幕 |
| 手动做字幕 | 太费时间 |

所以想做一个**本地运行的工具**：输入日语动漫视频 → 自动生成并嵌入精准的中文字幕。

### 1.2 核心原则

1. **翻译准确性第一** — 不是"能看就行"，而是要尽可能准确
2. **本地运行优先** — 通过 Ollama 跑本地模型，数据不出本机
3. **尽量复用，不重复造轮子** — 能找到现成方案就拿来用
4. **模块化设计** — ASR / 翻译 / 字幕引擎解耦，每个模块可独立替换

---

## 2. 技术栈选型

### 2.1 ASR（语音识别）

经过两轮调研，确定了以下方案：

| 模型 | 动漫领域准确率 | 速度 | 显存 | 推荐度 |
|------|--------------|------|------|-------|
| **Anime Whisper** ⭐ | CER 13.0% | 快 | ~4GB | **主力** |
| Kotoba-Whisper v2.2 | CER 18.8% | 极快 | ~3GB | 备选（内置说话人分离） |
| SenseVoice Small | CER 11.96% | 极快 | ~2GB | 快速备选 |
| Qwen3-ASR 1.7B | WER 0.185 | 中等 | ~6GB | 最高准确率备选 |

**结论**: `litagin/anime-whisper` 是目前最适合动漫语音识别的模型，基于 kotoba-whisper-v2.0 微调，5300 小时动漫语音数据训练，幻觉极低。

### 2.2 翻译（日语→中文）

| 模型 | 说明 | 显存 | 许可证 | 推荐度 |
|------|------|------|--------|-------|
| **Sakura-14B-Qwen2.5-v1.0** ⭐ | 专为 ACGN 日中翻译微调 | ~12GB | CC BY-NC-SA 4.0 | **主力** |
| **Sakura-7B-Qwen2.5-v1.0** | 轻量版 | ~6GB | CC BY-NC-SA 4.0 | **轻量主力** |
| GalTransl-7B-v2.6 | 视觉小说专项 | ~6GB | CC BY-NC-SA 4.0 | 备选 |
| Qwen2.5 系列 | 通用翻译 | 6-20GB | Apache 2.0 | 通用备选 |

**结论**: SakuraLLM 系列是目前 ACGN 翻译的最优解，支持术语表（GPT 字典），人称代词处理准确。

### 2.3 说话人分离（进阶功能）

| 方案 | DER | 速度 | 说明 |
|------|-----|------|------|
| pyannote.audio community-1 | ~20% | 快 | 开源首选 |
| Kotoba-Whisper v2.2 内置 | — | 极快 | 最简单 |
| DiariZen | 13.3% | 中等 | 开源最佳日语表现 |

**结论**: 作为进阶功能，先使用 Kotoba-Whisper v2.2 内置方案，不够再加 pyannote.audio。

### 2.4 Ollama 模型支持

本地翻译全部通过 Ollama 运行，支持的模型：

| Ollama 模型 | 说明 |
|-------------|------|
| `crosery/sakura-14b-qwen2.5-v1.0-q6k` | Sakura-14B（推荐，12GB 显存） |
| `crosery/sakura-7b-qwen2.5-v1.0` | Sakura-7B（6-8GB 显存） |
| `crosery/GalTransl-7B-v2.6` | GalTransl 视觉小说专用 |
| `qwen2.5:7b` / `qwen2.5:14b` | 通用翻译备选 |

---

## 3. 功能列表（完整路线图）

### 阶段 0：基础管道（首发）

- [ ] 视频 → 音频提取
- [ ] ASR 识别（Anime Whisper）→ 日语文本 + 时间戳
- [ ] 翻译（SakuraLLM + Ollama）→ 中文翻译
- [ ] 字幕生成（SRT/ASS，pysubs2）
- [ ] 字幕嵌入视频（FFmpeg）

### 阶段 1：管道完善后添加

- [ ] **说话人分离与角色标注** — 角色映射、角色名和颜色样式已完成；动漫场景自动说话人身份识别仍需提升
- [ ] **术语表系统（Glossary）** — 用户自定义角色名/招式名/地名翻译映射。参考 SakuraLLM GPT 字典格式
- [ ] **翻译记忆库（Translation Memory）** — JSONL 双层缓存，相同台词自动复用。参考 SubForge MAPS + JAVTrans
- [ ] **OP/ED 自动检测与跳过** — 自动识别片头片尾，避免 ASR 识别歌词。参考 SenseVoice 音频事件分类 / AniChapters
- [x] **多 Agent 脚本审查** — 5 个角色并行审查字幕，总编在全员成功、达到投票和置信度门槛时才自动修正；支持 SenseNova 六账号轮询与完整审计
- [x] **外挂日文字幕优先** — 单集/整季日文 sidecar 与内嵌文本轨可直接进入翻译；拒绝中文参考误用，按源 SHA-256 管理下游失效

### 阶段 2：体验完善

- [ ] **双语字幕模式** — 日语原文 + 中文翻译同时显示
- [ ] **断点续传（Checkpoint/Resume）** — JSONL checkpoint，中断后从中断处继续
- [ ] **批量处理（Batch Processing）** — 一次性提交多集
- [ ] **字幕时间轴优化** — 自动检测重叠、调整过短/过长显示时间、阅读速度控制
- [ ] **多种字幕样式模板** — ASS 预设样式（字体/颜色/描边/位置）

### 阶段 3：高级功能

- [x] **Web UI 界面** — 图形化操作
- [x] **人工校对模式（Proofreading）** — 交互式修正翻译
- [x] **翻译质量评估（TQE）** — Flash Lite + DeepSeek 双裁判 GEMBA-MQM；总编候选必须通过双方复评、最低分和最小提升门禁
- [ ] **支持更多语言对**
- [x] **插件系统**
- [x] **视频预览**

---

## 4. 完整工作流

```
视频文件
  │
  ├── 阶段 0 — 音频提取（ffmpeg）
  │     checkpoint → audio.wav
  │
  ├── 阶段 0 — ASR（Anime Whisper）
  │     checkpoint → transcript.json（日语文本 + 词级时间戳）
  │
  ├── 阶段 1 — OP/ED 检测（SenseVoice 可选）
  │     → 跳过音乐段标记
  │
  ├── 阶段 1 — 说话人分离（可选）
  │     checkpoint → diarization.json
  │
  ├── 阶段 0 — 翻译（SakuraLLM + 术语表 + 翻译记忆）
  │     checkpoint → translated.json
  │     translation_memory.jsonl ← 更新
  │
  ├── 阶段 0 — 字幕生成 + 时间轴优化
  │     → subtitles.srt / subtitles.ass
  │
  ├── 阶段 1 — 多 Agent 脚本审查
  │     ├─ 一致性 Agent → 角色名/术语一致性
  │     ├─ 逻辑 Agent    → 对话逻辑通顺性
  │     ├─ 翻译自然度 Agent → 中文自然度
  │     ├─ ASR 纠错 Agent  → ASR 误听检测
  │     └─ 总编 Agent     → 汇总 → 自动修正
  │     → 修正后的 subtitles_fixed.srt
  │
  ├── 阶段 3 — 翻译质量评估（GEMBA-MQM 可选）
  │     → quality_report.json
  │
  └── 阶段 0 — 嵌入视频（FFmpeg）
        → output.mp4（带字幕）
```

---

## 5. 调研已覆盖的领域

### 5.1 ASR 模型（已调研 10+ 个）

| 调研过的模型 | 链接 |
|-------------|------|
| Anime Whisper | https://huggingface.co/litagin/anime-whisper |
| Kotoba-Whisper v2.0/v2.1/v2.2 | https://huggingface.co/kotoba-tech/kotoba-whisper-v2.2 |
| SenseVoice Small | https://github.com/FunAudioLLM/SenseVoice |
| Qwen3-ASR 1.7B | https://huggingface.co/Qwen/Qwen3-ASR-1.7B |
| Whisper large-v3-turbo | OpenAI |
| Faster-Whisper | https://github.com/SYSTRAN/faster-whisper |
| WhisperX | https://github.com/m-bain/whisperX |
| ReazonSpeech | https://huggingface.co/reazon-research |

### 5.2 说话人分离（已调研 4 个）

| 方案 | 链接 |
|------|------|
| pyannote.audio | https://github.com/pyannote/pyannote-audio |
| NVIDIA NeMo | NVIDIA |
| DiariZen | https://huggingface.co/BUT-FIT/diarizen-wavlm-large-s80-md |
| Sortformer | NVIDIA |

### 5.3 翻译模型（已调研 5+ 个）

| 模型 | 链接 |
|------|------|
| SakuraLLM 系列 | https://github.com/SakuraLLM/SakuraLLM |
| GalTransl | https://github.com/xd2333/GalTransl |
| Qwen2.5 系列 | Ollama |
| TranslateGemma | Google |

### 5.4 端到端 Pipeline 项目（已调研 6 个）

| 项目 | Stars | 链接 |
|------|-------|------|
| WhisperJAV | ⭐1680 | https://github.com/meizhong986/WhisperJAV |
| JAVTrans | — | https://github.com/jaykwok/jav-trans |
| AnimeTranslator | ⭐2 | https://github.com/misakayyds/AnimeTranslator |
| AnimeSubs | ⭐6 | https://github.com/enrell/animesubs |
| SubsAI | — | https://github.com/absadiki/subsai |
| SubForge | — | https://github.com/JSKDLF/subforge |

### 5.5 进阶功能（已调研 7 个方向）

| 功能 | 参考实现 |
|------|---------|
| 术语表系统 | SakuraLLM GPT 字典格式 |
| 翻译记忆库 | SubForge MAPS + JAVTrans 双层 JSONL |
| OP/ED 检测 | SenseVoice / AniChapters / needle / anatro-rs |
| 多 Agent 框架 | CrewAI / LangGraph / AutoGen（但决定用无框架方案） |
| 断点续传 | agent-resume / python-durable / dagpipe |
| 时间轴优化 | subcap / WhisperX SubtitlesProcessor / anchor-sub-sync |
| 翻译质量评估 | GEMBA-MQM / COMETKiwi / XCOMET |

---

## 6. 技术决策要点

### 6.1 多 Agent 脚本审查的实现策略

**不引入 CrewAI/LangGraph 等框架**。5 个审查角色各自独立，通过不同 prompt 调用可配置的 Ollama 或 OpenAI-compatible 模型，用 `concurrent.futures.ThreadPoolExecutor` 并行执行，总编汇总冲突。生产配置以 4:1 比例使用 SenseNova Flash Lite 与 DeepSeek Flash，并在六个账号间轮询。只有全部角色成功、修正票和置信度均达到门槛时才自动替换。

### 6.2 零额外依赖优先

术语表系统、翻译记忆库、多 Agent 审查、断点续传、时间轴优化等功能都不需要额外安装库，全部用 JSONL + Python 标准库实现。

### 6.3 统一持久化格式

- Checkpoint、翻译记忆、审查结果全部用 JSONL
- 每个阶段写入一个 JSONL checkpoint 文件
- 重启时读取 checkpoint 决定跳过哪些阶段

### 6.4 三套硬件配置

| 配置 | 显存 | ASR | 翻译 |
|------|------|-----|------|
| 轻量版 | 6-8GB | Anime Whisper (int8) | Sakura-7B (IQ4_XS) |
| 标准版 | 10-12GB | Anime Whisper | Sakura-7B (Q5_K) |
| 高配版 | 16-24GB | Anime Whisper + pyannote | Sakura-14B (Q6_K) |

---

## 7. 已知待补充调研的领域

以下领域可能需要进一步调研：

1. **音频预处理** — 降噪、音频增强（是否有必要？对动漫来说背景音乐和音效会不会影响 ASR？）
2. **说话人分离在动漫场景的实际效果** — pyannote 在日语动漫角色上的准确率如何？声音相似的 ASMR 类角色能否区分？
3. **SakuraLLM 的许可证问题** — CC BY-NC-SA 4.0 禁止商用，是否需要备选方案？
4. **是否有更轻量的翻译方案** — 6GB 以下显存能否跑出可用的翻译质量？
5. **ASS 字幕的 CJK 字体最佳实践** — 中文字幕推荐字体、字号、描边参数
6. **批量处理多集时的效率优化** — 模型加载/卸载策略
7. **多 Agent 审查的整季收益验证** — 单句错误注入已验证能拦截；仍需在启用外挂日文字幕优先后，对 14 集做盲评并量化净收益与误改率。
