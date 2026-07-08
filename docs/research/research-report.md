# 综合调研报告 — Anime Accurate Sub

> 调研日期：2026-07-08
> 目标：为日语动漫视频自动生成精准中文字幕，寻找最优开源方案组合

---

## 目录

1. [ASR 语音识别](#1-asr-语音识别)
2. [说话人分离（Speaker Diarization）](#2-说话人分离speaker-diarization)
3. [翻译（日语→中文）](#3-翻译日语中文)
4. [字幕生成与嵌入](#4-字幕生成与嵌入)
5. [端到端 Pipeline 项目](#5-端到端-pipeline-项目)
6. [已有项目分析：可借鉴的流水线](#6-已有项目分析可借鉴的流水线)
7. [推荐方案](#7-推荐方案)
8. [参考资源汇总](#8-参考资源汇总)

---

## 1. ASR 语音识别

### 1.1 Anime Whisper ⭐⭐⭐⭐⭐（强烈推荐）

| 属性 | 内容 |
|------|------|
| 模型 | `litagin/anime-whisper` |
| 基础 | kotoba-whisper-v2.0 微调 |
| 训练数据 | 5,300 小时、373 万文件的动漫/Galgame 语音数据集 |
| 许可证 | AGPL-3.0 |
| HuggingFace | https://huggingface.co/litagin/anime-whisper |

**优势：**
- 动漫领域 CER **13.0%**，远超 Whisper-large-v3（16.5%）和 kotoba-whisper-v2.0（18.8%）
- **幻觉极低**，对非语言发声（笑声、喊叫、叹息、喘息）也能忠实转写
- 自然添加标点（。、!?…），贴合语音节奏和情感
- 基于蒸馏模型（kotoba-whisper），轻量快速
- NSFW 音频也能正常转写

**劣势：**
- **非动漫领域**表现可能不如通用 Whisper
- 不支持 initial prompt（会降低质量），需要特殊处理
- AGPL-3.0 许可证

**结论：这是目前最适合动漫语音识别的模型，没有之一。**

---

### 1.2 Kotoba-Whisper v2.x（推荐作为备选）

| 属性 | 内容 |
|------|------|
| 模型 | `kotoba-tech/kotoba-whisper-v2.0` / v2.1 / v2.2 |
| 基础 | Whisper large-v3 蒸馏，日语专用 |
| 速度 | 比 large-v3 快 6.3 倍 |
| 许可证 | MIT |
| HuggingFace | https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0 |

**各版本差异：**
- **v2.0**: 基础版日语 ASR
- **v2.1**: 增加了标点恢复（punctuators）
- **v2.2**: 增加了说话人分离（speaker diarization）功能！

**优势：**
- 日语专用，CER 与 large-v3 相当
- 轻量（756M 参数），速度快
- **v2.2 内置说话人分离**，一个模型搞定两件事
- 有 faster-whisper 和 whisper.cpp 权重可用

**劣势：**
- 通用日语 ASR，没有专门针对动漫优化
- 在自然对话场景的基准测试中 WER 偏高

---

### 1.3 SenseVoice Small（推荐作为快速备选）

| 属性 | 内容 |
|------|------|
| 模型 | `FunAudioLLM/SenseVoiceSmall` |
| 架构 | 非自回归（NAR），极快 |
| 支持语言 | 中文、英语、日语、韩语、粤语 |
| 速度 | 比 Whisper-large-v3 快 15 倍以上 |
| GitHub | https://github.com/FunAudioLLM/SenseVoice |

**优势：**
- 速度极快（非自回归架构，70ms 处理 10s 音频）
- 日语 CER 11.96%（不错，但略逊于 Whisper 的 10.34%）
- 自带情感识别和音频事件检测（BGM / 语音分类）
- 与 FunASR 生态集成良好

**劣势：**
- **日语准确率略低于 Whisper large-v3**（10.34% vs 11.96% CER）
- 仅支持 5 种语言
- 更适合中文/粤语场景

---

### 1.4 Qwen3-ASR（新星）

| 属性 | 内容 |
|------|------|
| 模型 | `qwen/qwen3-asr-1.7b` |
| 评分 | 2026 年最新日语 ASR 基准测试中排名第一 |
| WER | 0.185（优于 Whisper 的 0.218） |

**优势：**
- 日语识别准确率当前最高
- 嘈杂环境和多人场景下稳定

**劣势：**
- 1.7B 参数，比 kotoba-whisper 大
- 自回归架构，速度不算最快
- 无动漫专用微调版本
- 已有社区微调版本 `jaykwok/Qwen3-ASR-0.6B-JA-Anime-Galgame`（用于 JAVTrans 项目）

---

### 1.5 Faster-Whisper（推荐作为推理引擎）

| 属性 | 内容 |
|------|------|
| 项目 | `SYSTRAN/faster-whisper` |
| 核心 | CTranslate2 重新实现 Whisper |
| 速度 | 比 openai/whisper 快 4 倍 |
| 许可证 | MIT |
| GitHub | https://github.com/SYSTRAN/faster-whisper |

**优势：**
- 可直接加载 Anime Whisper 和 Kotoba-Whisper 的 faster-whisper 权重
- int8 量化进一步降低显存占用
- 批量推理（batch_size=8）速度提升 8 倍+
- 大量项目以此为基础（WhisperX、Whisper-Streaming 等）

---

### 1.6 ASR 总结

| 模型 | 动漫准确率 | 速度 | 显存 | 推荐场景 |
|------|-----------|------|------|---------|
| **Anime Whisper** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ~4GB | **主力 — 动漫语音** |
| Kotoba-Whisper v2.2 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ~3GB | 备选 + 内置说话人分离 |
| SenseVoice Small | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ~2GB | 快速处理场景 |
| Qwen3-ASR 1.7B | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ~6GB | 最高准确率需求 |
| Whisper large-v3-turbo | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ~6GB | 通用备选 |

**推荐策略：Anime Whisper 为主，Kotoba-Whisper v2.2 作为带说话人分离的备选。**

---

## 2. 说话人分离（Speaker Diarization）

### 2.1 pyannote.audio（首选）

| 属性 | 内容 |
|------|------|
| 项目 | `pyannote/pyannote-audio` |
| 许可证 | MIT |
| GitHub | https://github.com/pyannote/pyannote-audio |
| 模型 | `pyannote/speaker-diarization-community-1` |

**优势：**
- 最流行的开源说话人分离工具，社区活跃
- community-1 管道开源免费（需接受 HuggingFace 条款）
- 处理速度：31s 处理 1 小时音频
- Python 原生 API，易于集成
- 支持预知说话人数或自动检测

**劣势：**
- 对于声音极其相似的角色可能无法区分（已知 issue）
- 需要 HuggingFace token
- 日语场景性能一般（DER 28.8% in community-1）

---

### 2.2 NVIDIA NeMo（备选）

| 属性 | 内容 |
|------|------|
| 框架 | NVIDIA NeMo + Sortformer |
| 优势 | 2 人对话场景 DER 低 9%，重叠语音处理更好 |
| 劣势 | 速度慢 2 倍，配置复杂，显存需求高 |

---

### 2.3 DiariZen（开源新秀）

| 属性 | 内容 |
|------|------|
| 模型 | BUT-FIT/diarizen-wavlm-large-s80-md |
| 整体 DER | 13.3%（开源最佳之一） |
| 日语 DER | 15.6% |
| 优势 | 多说话人场景表现好（5+人 DER 7.1%） |

---

### 2.4 Kotoba-Whisper v2.2（内置方案）

| 属性 | 内容 |
|------|------|
| 模型 | `kotoba-tech/kotoba-whisper-v2.2` |
| 说明 | ASR 管道中直接集成了 `diarizers` 说话人分离 |

**优势：**
- 一个模型同时做 ASR + 说话人分离
- 简化流水线架构

---

### 2.5 说话人分离总结

对于动漫来说，说话人分离是一个**锦上添花**的功能（不是必须的）。如果只是做字幕，没有说话人标签也完全可以。

**推荐：先用 Kotoba-Whisper v2.2 的内置方案（最简单），如果效果不够再加入 pyannote.audio。**

---

## 3. 翻译（日语→中文）

### 3.1 SakuraLLM 系列 ⭐⭐⭐⭐⭐（强烈推荐）

| 属性 | Sakura-14B-Qwen2.5-v1.0 | Sakura-7B-Qwen2.5-v1.0 | GalTransl-7B-v2.6 |
|------|------------------------|-----------------------|------------------|
| 参数 | 14B | 7B | 7B |
| 领域 | 轻小说/动漫/Galgame ACGN | 轻小说/动漫 | 视觉小说专项优化 |
| 最低显存 | ~12GB (Q6_K) | ~6GB (IQ4_XS) | ~6GB (IQ4_XS) |
| 上下文 | 128K | 128K | 32K |
| Ollama 可用 | ✅ `crosery/sakura-14b-qwen2.5-v1.0-q6k` | ✅ `crosery/sakura-7b-qwen2.5-v1.0` | ✅ `crosery/GalTransl-7B-v2.6` |
| 许可证 | CC BY-NC-SA 4.0（非商用） | CC BY-NC-SA 4.0 | CC BY-NC-SA 4.0 |
| 术语表 | ✅ GPT 字典 | ✅ GPT 字典 | ✅ GPT 字典 |
| 角色名一致性 | ✅ | ✅ | ✅ |

**核心优势：**
- **专门为日语→中文 ACGN 内容翻译微调**，这是普通 LLM 做不到的
- 支持**术语表（GPT 字典）**，可以固定角色名、专有名词的翻译
- 人称代词处理准确（区分「私」「君」「お前」等）
- 文风贴近动漫/轻小说风格
- 可以通过 Ollama 一键使用，完全本地运行

**劣势：**
- CC BY-NC-SA 许可证，禁止商用
- Sakura-14B 需要 ~12GB 显存
- 翻译质量高度依赖术语表配置

**示例 prompt：**
```python
system = "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"
user = f"根据以下术语表（可以为空）：\n{gpt_dict_text}\n将下面的日文文本根据对应关系和备注翻译成中文：{japanese_text}"
```

---

### 3.2 Qwen2.5 系列（通用备选）

| 模型 | 显存 | Ollama | 说明 |
|------|------|--------|------|
| qwen2.5:7b | ~6GB | ✅ | 轻量，适合 8GB 显存 |
| qwen2.5:14b | ~10GB | ✅ | 质量较好 |
| qwen2.5:32b | ~20GB | ✅ | 高质量翻译 |
| qwen3.5:27b | ~18GB | ✅ | 最新版，推荐 |

**优势：**
- Ollama 原生支持，配置最简单
- 128K 上下文窗口
- CJK 语言能力强
- Apache 2.0 许可证（可商用）

**劣势：**
- 没有针对动漫/ACGN 内容优化
- 角色名、专有名词可能翻译不一致
- 需要写合适的 prompt 引导

---

### 3.3 云端 API 备选

| 服务 | 日语→中文质量 | 成本 | 说明 |
|------|-------------|------|------|
| DeepSeek | ⭐⭐⭐⭐⭐ | 很便宜 | 性价比极高，被多个项目推荐 |
| OpenAI GPT | ⭐⭐⭐⭐ | 中等 | 质量稳定 |
| Claude | ⭐⭐⭐⭐ | 中等 | 日语流畅但可能偏离原意（有 benchmark 指出问题） |
| Google Gemini | ⭐⭐⭐⭐ | 中等 | TranslateGemma 变体表现好 |

---

### 3.4 翻译总结

| 方案 | 动漫翻译质量 | 显存 | 成本 | 推荐度 |
|------|-----------|------|------|-------|
| **SakuraLLM 14B + Ollama** | ⭐⭐⭐⭐⭐ | ~12GB | 免费 | ⭐⭐⭐⭐⭐ |
| **SakuraLLM 7B + Ollama** | ⭐⭐⭐⭐ | ~6GB | 免费 | ⭐⭐⭐⭐⭐ |
| Qwen2.5 14B + Ollama | ⭐⭐⭐⭐ | ~10GB | 免费 | ⭐⭐⭐⭐ |
| DeepSeek API | ⭐⭐⭐⭐⭐ | — | 极低 | ⭐⭐⭐⭐ |
| Qwen2.5 7B + Ollama | ⭐⭐⭐ | ~6GB | 免费 | ⭐⭐⭐ |

**推荐策略：SakuraLLM 为主方案，Qwen2.5/Ollama 为通用备选，DeepSeek API 为质量保底。**

---

## 4. 字幕生成与嵌入

### 4.1 核心工具

| 工具 | 用途 | 说明 |
|------|------|------|
| **FFmpeg** | 音频提取 + 字幕嵌入 | 必装，核心依赖 |
| **pysubs2** | SRT/ASS 字幕生成 | Python 库，支持格式转换 |
| **aeneas** | 强制对齐（Forced Alignment） | 将文本对齐到音频时间戳 |
| **WhisperX** | 词级时间戳 + 对齐 | 基于 wav2vec2，精确到音素级 |

### 4.2 字幕样式

**ASS 格式优势：**
- 支持字体、大小、颜色、描边、位置等样式控制
- 支持双语字幕布局（上日下中或左日右中）
- 兼容主流播放器（VLC，mpv，PotPlayer 等）

**推荐的 ASS 样式配置：**
```ass
[V4+ Styles]
Style: Default,Microsoft YaHei,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,1,1,2,5,5,5,1
```

### 4.3 字幕嵌入方式

| 方式 | 说明 | 优点 | 缺点 |
|------|------|------|------|
| 软字幕（Softsub） | 外挂字幕文件 | 不修改视频，可切换/关闭 | 播放器需支持 |
| 硬字幕（Hardsub） | 烧录到视频画面 | 播放器通用 | 重新编码，质量损失 |
| Mux（封装） | 内嵌到 MKV/MP4 | 视频原质量+字幕轨道 | 仅特定格式支持 |

### 4.4 字幕生成工具

| 工具 | 说明 | GitHub |
|------|------|--------|
| **pysubs2** | Python 字幕操作库，支持 SRT/ASS/SSA | https://github.com/tkarabela/pysubs2 |
| **subcap** | 强制对齐 + 样式化 ASS 生成 | https://github.com/bighippoman/subcap |
| **ai-video-captions** | 词级动画字幕 + FFmpeg 烧录 | https://github.com/nicolaigaina/ai-video-captions |

---

## 5. 端到端 Pipeline 项目

### 5.1 WhisperJAV ⭐1680（最成熟）

| 属性 | 内容 |
|------|------|
| GitHub | https://github.com/meizhong986/WhisperJAV |
| 语言 | Python |
| 许可证 | MIT |
| 最近更新 | 2026-05（活跃维护） |

**Pipeline 支持：**
| 管道 | 后端 | 适用场景 |
|------|------|---------|
| faster | Faster-Whisper (turbo) | 快速，清晰音频 |
| fast | OpenAI Whisper + Auditok | 一般用途 |
| balanced | Faster-Whisper + Silero VAD | **默认**，嘈杂/对话型 |
| fidelity | OpenAI Whisper | 最高准确率 |
| transformers | HuggingFace Kotoba | Kotoba 日语模型 |
| **qwen** | Qwen3-ASR + Forced Alignment | Qwen ASR |
| **anime** | **Anime Whisper + TEN VAD** | **动漫/JAV 对话** ✅ |

**翻译后端：**
- Ollama（推荐本地）、DeepSeek、Gemini、Claude、GPT、OpenRouter、GLM、Groq、自定义端点

**优势：**
- 最成熟的流水线项目，**已有 anime pipeline 直接使用 Anime Whisper**
- 多种管道可选，模块化设计
- 内置翻译、字幕生成、嵌入
- 活跃维护，43 个 release

**劣势：**
- 原为 JAV（日本成人视频）设计，但 anime 管道可直接用于动漫
- 配置较多，有一定学习曲线

---

### 5.2 AnimeTranslator（动漫专用）

| 属性 | 内容 |
|------|------|
| GitHub | https://github.com/misakayyds/AnimeTranslator |
| 语言 | Python |
| 许可证 | MIT |
| 最近更新 | 2026-06 |

**四阶段管线：**
1. **SenseVoice** — VAD + 音频事件分类（BGM/语音/音乐）
2. **OP/ED 自动检测** — 检测片头片尾音乐段并跳过
3. **Whisper large-v3** — 语音识别（词级时间戳）
4. **DeepSeek 翻译** — 上下文感知翻译，含角色名推断

**优势：**
- **专为动漫设计**，OP/ED 自动过滤
- 四层幻觉防御（SenseVoice 标签 → OP/ED 过滤 → Whisper 质量检查 → 正则过滤）
- 输出 ASS 双语字幕

**劣势：**
- 翻译只支持 DeepSeek API，未集成 Ollama 本地模型
- 项目较新（2 stars），成熟度有待验证

---

### 5.3 AnimeSubs（桌面应用）

| 属性 | 内容 |
|------|------|
| GitHub | https://github.com/enrell/animesubs |
| 语言 | Rust + Vue (Tauri) |
| 许可证 | AGPL-3.0 |
| 最近更新 | 2026-06 |

**功能：**
- 拖放式桌面应用
- 支持 8 种 LLM 提供商（含 Ollama、LM Studio 等本地方案）
- 翻译风格：自然、直译、本地化、正式、随意、保留敬语
- 智能过滤 OP/ED、卡拉OK、字幕
- 支持 mkvmerge/ffmpeg 嵌入字幕
- 批量处理

**优势：**
- 用户友好的桌面 GUI
- 完整的流程覆盖（提取→翻译→嵌入）
- 支持思考模型（DeepSeek R1、QwQ）

**劣势：**
- 项目较新（6 stars）
- Rust 编译环境搭建复杂
- 未深度集成动漫专用 ASR

---

### 5.4 JAVTrans（先进管道）

| 属性 | 内容 |
|------|------|
| GitHub | https://github.com/jaykwok/jav-trans |
| 语言 | Python |
| 最近更新 | 2026-07 |

**核心特性：**
- **Qwen3-ASR 动漫/Galgame 微调版**（`jaykwok/Qwen3-ASR-0.6B-JA-Anime-Galgame`）
- **SpeechBoundary-JA**: 专为日语动漫设计的语音边界检测系统
- **Qwen3-ForcedAligner**: 强制对齐确认词级时间戳
- LLM 翻译缓存 + translation memory（翻译记忆）
- 翻译质量报告

**优势：**
- **最先进的动漫专用技术栈**（SpeechBoundary-JA 是独有技术）
- 6GB 显存即可运行
- 完整的翻译缓存机制

---

### 5.5 Subs AI（通用工具）

| 属性 | 内容 |
|------|------|
| GitHub | https://github.com/absadiki/subsai |
| 说明 | 支持多个 ASR 后端（openai/whisper、faster-whisper、WhisperX、whisper.cpp） |
| 翻译 | 内置 M2M100 翻译模型（但质量有限） |

---

## 6. 已有项目分析：可借鉴的流水线

以下是从各项目中提取的最佳实践：

### 6.1 架构参考：WhisperJAV 的 anime pipeline

```
Video → Audio Extraction → [TEN VAD] → [Anime Whisper] → [Forced Alignment]
                                                                    ↓
双语 ASS ← [FFmpeg Mux] ← [pysubs2 ASS生成] ← [LLM Translation (Ollama)]
```

### 6.2 架构参考：AnimeTranslator 的四层防御

```
SenseVoice 标签（BGM/语音分类）
    → OP/ED 自动检测（跳过片头片尾歌词段）
    → Whisper no_speech_prob / compression_ratio 质量过滤
    → 语气词正则过滤
```

### 6.3 架构参考：JAVTrans 的强制对齐

```
Qwen3-ASR → ASR QC（质量检查）→ Qwen3-ForcedAligner（词级对齐）→ 时间轴归一化
```

### 6.4 翻译缓存策略（来自 JAVTrans + WhisperJAV）

```
translation_cache.jsonl: 精确复跑缓存（相同文本+prompt 直接复用）
translation_cache.memory.jsonl: 翻译记忆（按日语原文复用译文）
术语表（GPT Dictionary）：角色名/专有名词一致性保证
```

---

## 7. 推荐方案

### 7.1 最终推荐技术栈

```
┌──────────────────────────────────────────────────────────────┐
│                   Anime Accurate Sub                          │
├──────────┬──────────┬──────────┬──────────┬──────────────────┤
│  ASR     │ Diarize  │ Translate│ Subtitle │   Embedding      │
├──────────┼──────────┼──────────┼──────────┼──────────────────┤
│ Anime    │ (可选)    │ SakuraLLM│ pysubs2  │ FFmpeg           │
│ Whisper  │ pyannote │ + Ollama │ + ASS    │ (soft/hard)      │
│ (主力)   │ 或       │ (主力)   │ 样式模板 │                  │
│          │ Kotoba   │          │          │                  │
│ Kotoba-  │ v2.2     │ Qwen2.5  │ subcap   │ mkvmerge         │
│ Whisper  │ 内置     │ + Ollama │ (备选)   │ (备选)           │
│ (备选)   │          │ (备选)   │          │                  │
└──────────┴──────────┴──────────┴──────────┴──────────────────┘
```

### 7.2 方案 A（推荐 — 面向 8-12GB 显存用户）

| 模块 | 选择 | 显存 |
|------|------|------|
| ASR | Anime Whisper（通过 faster-whisper） | ~4GB |
| 说话人分离 | Kotoba-Whisper v2.2 内置（可选） | ~3GB |
| 翻译 | Sakura-7B-Qwen2.5-v1.0（Ollama，IQ4_XS 量化） | ~6GB |
| 字幕生成 | pysubs2 | — |
| 字幕嵌入 | FFmpeg soft mux | — |

**总显存峰值：~10GB（可运行在 12GB 显卡上）**

### 7.3 方案 B（轻量 — 面向 6-8GB 显存用户）

| 模块 | 选择 | 显存 |
|------|------|------|
| ASR | Anime Whisper（int8 量化） | ~3GB |
| 说话人分离 | 跳过 | — |
| 翻译 | Sakura-7B（IQ4_XS）+ Qwen2.5:7b 备选 | ~4GB |
| 字幕生成 | pysubs2 | — |
| 字幕嵌入 | FFmpeg | — |

**总显存峰值：~7GB（可运行在 8GB 显卡上）**

### 7.4 方案 C（高质量 — 面向 16-24GB 显存用户）

| 模块 | 选择 | 显存 |
|------|------|------|
| ASR | Anime Whisper + pyannote.audio 说话人分离 | ~5GB |
| 翻译 | Sakura-14B-Qwen2.5-v1.0（Ollama，Q6_K） | ~12GB |
| 字幕生成 | pysubs2 + 双语样式 | — |
| 字幕嵌入 | FFmpeg + mkvmerge | — |

**总显存峰值：~17GB**

### 7.5 关于复用已有项目的策略

**不建议直接 fork 现有项目**，而是借鉴其设计：

1. **借鉴 WhisperJAV 的 pipeline 架构**（管道模式、VAD + ASR + 对齐）
2. **借鉴 JAVTrans 的强制对齐和缓存机制**（SpeechBoundary-JA、translation memory）
3. **借鉴 AnimeTranslator 的 OP/ED 检测和幻觉防御**
4. **结合 SakuraLLM 的动漫翻译优势**

---

## 8. 参考资源汇总

### ASR 模型
| 资源 | 链接 |
|------|------|
| Anime Whisper | https://huggingface.co/litagin/anime-whisper |
| Kotoba-Whisper v2.0 | https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0 |
| Kotoba-Whisper v2.2（带说话人分离） | https://huggingface.co/kotoba-tech/kotoba-whisper-v2.2 |
| SenseVoice | https://github.com/FunAudioLLM/SenseVoice |
| Faster-Whisper | https://github.com/SYSTRAN/faster-whisper |

### 说话人分离
| 资源 | 链接 |
|------|------|
| pyannote.audio | https://github.com/pyannote/pyannote-audio |
| DiariZen | https://huggingface.co/BUT-FIT/diarizen-wavlm-large-s80-md |

### 翻译模型
| 资源 | 链接 |
|------|------|
| Sakura-14B-Qwen2.5-v1.0 (Ollama) | https://ollama.com/crosery/sakura-14b-qwen2.5-v1.0-q6k |
| Sakura-7B-Qwen2.5-v1.0 (Ollama) | https://ollama.com/crosery/sakura-7b-qwen2.5-v1.0 |
| GalTransl-7B-v2.6 (Ollama) | https://ollama.com/crosery/GalTransl-7B-v2.6 |
| SakuraLLM 项目 | https://huggingface.co/SakuraLLM |

### 端到端项目
| 资源 | 链接 | Stars |
|------|------|-------|
| WhisperJAV | https://github.com/meizhong986/WhisperJAV | ⭐1680 |
| AnimeTranslator | https://github.com/misakayyds/AnimeTranslator | ⭐2 |
| AnimeSubs | https://github.com/enrell/animesubs | ⭐6 |
| JAVTrans | https://github.com/jaykwok/jav-trans | — |
| Subs AI | https://github.com/absadiki/subsai | — |

### 字幕工具
| 资源 | 链接 |
|------|------|
| pysubs2 | https://github.com/tkarabela/pysubs2 |
| subcap | https://github.com/bighippoman/subcap |
| ai-video-captions | https://github.com/nicolaigaina/ai-video-captions |
| aeneas | https://github.com/readbeyond/aeneas |

### Ollama 翻译工具
| 资源 | 链接 |
|------|------|
| Potplayer-Ollama-Translate | https://github.com/Nuo27/Potplayer-Ollama-Translate |
| SRT-Trans2.0 | https://github.com/ccaihuixin/srt-Trans2.0 |
| faster-whisper + Qwen2.5 翻译示例 | https://gist.github.com/cxfcxf/15ffc741db388d7d8ef73c67c998e13c |