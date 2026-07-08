# 新增功能调研报告（第二阶段）

> 调研日期：2026-07-08
> 目标：为 Anime Accurate Sub 的进阶功能寻找可参考的开源方案

---

## 目录

1. [术语表系统（Glossary）](#1-术语表系统glossary)
2. [翻译记忆库（Translation Memory）](#2-翻译记忆库translation-memory)
3. [OP/ED 自动检测与跳过](#3-oped-自动检测与跳过)
4. [多 Agent 脚本审查](#4-多-agent-脚本审查)
5. [断点续传（Checkpoint/Resume）](#5-断点续传checkpointresume)
6. [字幕时间轴优化](#6-字幕时间轴优化)
7. [翻译质量评估（TQE）](#7-翻译质量评估tqe)
8. [推荐实现方案汇总](#8-推荐实现方案汇总)

---

## 1. 术语表系统（Glossary）

### 1.1 SakuraLLM GPT 字典（⭐ 推荐参考）

**项目**: https://github.com/SakuraLLM/SakuraLLM

SakuraLLM 的术语表（GPT 字典）是当前最成熟的动漫/ACGN 翻译术语表方案。

**数据结构**（JSON）：
```json
[
  {
    "src": "カカシ",
    "dst": "卡卡西",
    "info": "角色名，木叶村上忍"
  },
  {
    "src": "螺旋丸",
    "dst": "螺旋丸",
    "info": "忍术，查克拉旋转"
  }
]
```

**注入方式** — 翻译时拼入 prompt：
```
system: 你是一个轻小说翻译模型，可以流畅通顺地使用给定的术语表...
user: 根据以下术语表（可以为空）：
カカシ->卡卡西 #角色名，木叶村上忍
螺旋丸->螺旋丸 #忍术

将下面的日文文本根据上述术语表的对应关系和备注翻译成中文：{原文}
```

**关键要点**：
- 字典为空时使用简化 prompt（不传术语表）
- v1.0 版本开始支持，兼容 OpenAI API 格式（Ollama 也兼容）
- 支持 info 字段作为备注，帮助模型理解使用场景

### 1.2 SakuraDict 社区字典库

**项目**: https://github.com/Frzgunr1/SakuraDict

基于 SakuraLLM 的社区字典集合，包含：
- 通用字典（日常用语）
- 游戏操作界面字典
- 人名字典（常见日本名字和昵称）
- 专有名词字典

**工具**: 附带 `txt_json_converter.py` 格式转换工具

### 1.3 推荐方案

**直接采用 SakuraLLM 的 GPT 字典格式**，原因：
- 与 SakuraLLM 翻译模型天然兼容
- 格式简单（JSON），易于编辑和管理
- 社区已有大量字典资源可直接使用
- 通用 LLM（如 Qwen2.5）也能理解这个格式

**实现方式**：只需在翻译 prompt 前拼接术语表即可，无需额外框架。

---

## 2. 翻译记忆库（Translation Memory）

### 2.1 SubForge MAPS + Translation Memory（⭐ 推荐参考）

**项目**: https://github.com/JSKDLF/subforge

SubForge 的翻译记忆系统是最完整的开源实现：

**两层结构**：
```
.subforge-tm/
  glossary.jsonl    # 术语表（从原文提取的术语）
  memory.jsonl      # 翻译记忆（原文→译文对的缓存）
  .lock             # 并发锁文件
```

**工作流程**：
```
source SRT → terminology extraction → glossary.jsonl
           → 翻译 → GEMBA-MQM 质量评估 → 低分段落 refine
           → memory.jsonl（缓存翻译结果）
```

**memory.jsonl 格式** — 每行一个 JSON 对象：
```json
{"src": "...", "tgt": "...", "model": "qwen2.5:7b", "timestamp": "..."}
```

**关键特性**：
- 使用 advisory lock 防止并发写入冲突
- 跨项目/跨会话复用
- 精确匹配，简单高效

### 2.2 JAVTrans 三层缓存（⭐ 推荐参考）

**项目**: https://github.com/jaykwok/jav-trans

JAVTrans 的缓存机制更精细化：

| 缓存层 | 文件 | 作用 |
|--------|------|------|
| Batch Cache | `translation_cache.jsonl` | 完全相同的 cue + timing + prompt 精确复跑 |
| Translation Memory | `translation_cache.memory.jsonl` | 按日文文本、目标语言、词汇表、模型族复用译文 |
| Provider Prompt Cache | 无（API 端） | 通过稳定 system prompt 降低 API 成本 |

### 2.3 推荐方案

**两层缓存**：
1. **精确匹配缓存**（JAVTrans 的 batch cache）：key = 日文原文 + 翻译模型，value = 译文
2. **翻译记忆**（SubForge 的 memory.jsonl）：跨会话持久化，用于后续翻译前先查缓存

**为什么不推荐模糊匹配**：动漫字幕翻译的场景中，精确匹配率已经很高（"へへ…"、"そうか"这类台词反复出现），模糊匹配带来的复杂度不值得。

---

## 3. OP/ED 自动检测与跳过

### 3.1 方案对比

| 方案 | 方法 | 速度 | 准确性 | 离线 | 复杂度 |
|------|------|------|--------|------|--------|
| **SenseVoice 音频分类** | 神经网络音频事件检测 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ✅ | 低 |
| **AniChapters** | 音频指纹 + anime-themes.moe | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ✅ | 中 |
| **needle** | 音频指纹（Chromaprint） | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ✅ | 低 |
| **anatro-rs** | Chromaprint + FFT 卷积 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ✅ | 中 |
| **skip-intro-credits** | Chromaprint + 滑动窗口 | ⭐⭐⭐ | ⭐⭐⭐⭐ | ✅ | 低 |
| **ani-skip** | 调用 aniskip API（在线） | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ❌ | 低 |

### 3.2 SenseVoice 音频事件分类（⭐ 推荐首选）

**模型**: `FunAudioLLM/SenseVoiceSmall`

SenseVoice 除了 ASR 功能外，还能输出**音频事件标签**：
- `speech` — 语音
- `music` — 音乐
- `bgm` — 背景音乐

**优势**：
- 已经在 ASR 模块中使用了 SenseVoice（如果选它做 ASR）
- 额外输出几乎没有计算开销
- 可以精确识别哪段是音乐（OP/ED 通常 = 音乐 +  vocals）

**检测策略**：如果连续 60-90 秒的音频被标记为 `music` 且出现在视频的前 5 分钟或最后 5 分钟，大概率是 OP/ED。

### 3.3 AniChapters（⭐ 推荐备选）

**项目**: https://github.com/56cla/AniChapters

专门为动漫 OP/ED 检测设计的工具：
- 从 [animethemes.moe](https://animethemes.moe) 获取主题曲信息
- 音频指纹匹配定位 OP/ED 时间戳
- 生成 MKV chapter 文件
- 支持批量处理多集

**优势**：准确率极高，因为用了已知的主题曲音频做指纹匹配
**劣势**：需要网络获取主题曲信息，对新番可能没有数据

### 3.4 needle（Rust 实现，轻量）

**项目**: https://github.com/aksiksi/needle

- 基于 Chromaprint 音频指纹
- 分析 + 搜索两步：先预计算音频指纹，再搜索匹配
- M1 Mac 上分析 10s，搜索 <1s
- 支持批量处理

### 3.5 推荐方案

**首选：SenseVoice 音频事件分类**
- 零额外依赖（如果已经用了 SenseVoice）
- 纯离线，无需网络
- 可以在 VAD 阶段同时完成

**备选：AniChapters**
- 更精确，但需要网络
- 适用于已知番剧

---

## 4. 多 Agent 脚本审查

### 4.1 多 Agent 框架对比

| 框架 | 核心理念 | 学习曲线 | 适用场景 | 开源协议 |
|------|---------|---------|---------|---------|
| **CrewAI** | 角色（Role）+ 任务（Task） | 低 | 快速原型，角色协作 | MIT |
| **LangGraph** | 有向图（StateGraph） | 高 | 复杂工作流，生产系统 | MIT |
| **AutoGen** | 对话式 Agent | 中 | 代码生成，迭代推理 | CC 4.0 |

**关键结论**：对于我们的脚本审查场景，**不需要引入任何框架**。

### 4.2 实际推荐方案：无框架的 Agent 协作

**理由**：我们的 5 个 Agent 各自独立，不需要复杂的通信机制。每个 Agent 只是：
1. 接收一段文本（字幕内容）
2. 用 Ollama 调用同一个 LLM，但带不同的 prompt
3. 输出审查结果（JSON 格式）

**实现方式** — 不到 100 行代码：
```python
# 每个 Agent 就是一个函数
def consistency_agent(subtitles: list[dict]) -> list[Issue]:
    prompt = f"检查以下字幕文本中角色名、术语是否前后一致...\n{subtitle_text}"
    response = ollama.chat(model="sakura-14b", messages=[{"role": "user", "content": prompt}])
    return parse_issues(response)

def logic_agent(subtitles: list[dict]) -> list[Issue]:
    prompt = f"以下是一段动漫对话，检查逻辑是否通顺...\n{dialogue_text}"
    response = ollama.chat(...)
    return parse_issues(response)

# 总编 Agent 汇总
def editor_agent(all_issues: list[Issue]) -> list[Correction]:
    prompt = f"汇总以下审查意见，去重，排优先级，生成修正方案...\n{issues_text}"
    response = ollama.chat(...)
    return parse_corrections(response)
```

**并行执行**：每个 Agent 互相独立，直接用 `concurrent.futures.ThreadPoolExecutor` 并行调用 Ollama。

### 4.3 参考项目：TransAgents（学术论文）

**论文**: "Perhaps Beyond Human Translation: Harnessing Multi-Agent Collaboration for Translating Ultra-Long Literary Texts"

**角色设计**：CEO、Senior Editor、Junior Editor、Translator、Localization Specialist、Proofreader

**协作策略**：
- **Addition-by-Subtraction**: 一个 Agent 加内容，另一个减冗余
- **Trilateral Collaboration**: Action（行动）+ Critique（批评）+ Judgment（裁决）

**启示**：总编 Agent 的裁决角色是关键，可以防止各 Agent 的意见冲突死循环。

---

## 5. 断点续传（Checkpoint/Resume）

### 5.1 方案对比

| 方案 | 持久化方式 | 额外依赖 | 复杂度 | 适用场景 |
|------|-----------|---------|--------|---------|
| **agent-resume** | JSONL 文件 | 零依赖 | ⭐ | 按 item 处理的任务 |
| **python-durable** | SQLite/Redis | 少 | ⭐⭐ | 异步工作流 |
| **dagpipe** | JSON 文件 | 零依赖 | ⭐⭐ | DAG 流水线 |
| **LangGraph checkpoint** | 多种后端 | 多 | ⭐⭐⭐⭐ | 复杂 Agent 系统 |
| **JAVTrans 缓存** | JSONL 文件 | 零依赖 | ⭐ | 翻译阶段 |

### 5.2 agent-resume（⭐ 推荐首选）

**项目**: https://github.com/MukundaKatta/agent-resume

最轻量的断点续传方案，只有标准库依赖。

```python
from agent_resume import JsonlStore, resume_or_start

store = JsonlStore("my_pipeline.ckpt")
run = resume_or_start(store=store, initial_state={}, work_items=episode_list)

for episode in run:
    result = process_episode(episode, run.state)
    run.checkpoint({"completed": episode, "result": result})
```

**核心特性**：
- 每次 checkpoint 追加一行 JSONL，`fsync` 确保写入完成
- 重启后自动跳过已完成的 item
- 零依赖，纯标准库

### 5.3 python-durable（备选）

**项目**: https://github.com/WillemDeGroef/python-durable

```python
@wf.workflow(id="pipeline-{video_id}")
async def process_video(video_id: str) -> None:
    audio = await extract_audio(video_id)       # checkpoint 1
    transcript = await transcribe(audio)         # checkpoint 2
    translation = await translate(transcript)    # checkpoint 3
    subtitle = await generate_subtitle(translation)  # checkpoint 4
```

### 5.4 推荐方案

**按阶段 checkpoint**，每个阶段独立缓存：

| 阶段 | Checkpoint 内容 | 存储 |
|------|----------------|------|
| 音频提取 | 输出 WAV 路径 | 文件系统 |
| ASR 识别 | 日语文本 + 时间戳 (JSON) | JSONL |
| 说话人分离 | 说话人标签 (JSON) | JSONL |
| 翻译 | 中日对照字幕 (JSON) | JSONL |
| 字幕生成 | SRT/ASS 文件路径 | 文件系统 |

**实现**：直接用 `agent-resume` 或自行实现 JSONL 写入。每个阶段完成后写一行 checkpoint，重启时先读 checkpoint 决定跳过哪些阶段。

---

## 6. 字幕时间轴优化

### 6.1 常见问题

| 问题 | 表现 | 原因 |
|------|------|------|
| **字幕重叠** | 两条字幕同时出现在画面上 | ASR 分段错误 |
| **显示时间过短** | 字幕一闪而过，来不及读 | 单句时间戳过短 |
| **显示时间过长** | 字幕长时间停留在画面上 | 静音段未分割 |
| **阅读速度过快** | 中文字幕太多字，时间太短 | 中文字数/时间比不合适 |

### 6.2 时间轴优化参考实现

#### subcap（⭐ 推荐参考）

**项目**: https://github.com/bighippoman/subcap

subcap 的 subtitle segmentation 逻辑是最完整的参考实现：

```python
# subcap 的分段策略：
# 1. 按句子边界断句
# 2. 过长的行自动换行（max_chars=42）
# 3. 最短显示时间 ≥ 1s，最长 ≤ 8s
# 4. 行间插入最小间隙（gap）
# 5. 阅读速度控制（chars/sec）
```

#### WhisperX SubtitlesProcessor

**文件**: `whisperx/SubtitlesProcessor.py`

WhisperX 内置了分段逻辑，处理：
- 中日文等复杂文字使用 30 字符/行的限制（而非英文的 45）
- 以逗号和连词为分割点
- 缺失时间戳的插值估算

#### anchor-sub-sync 的 Zipper 算法

**项目**: https://github.com/ellite/anchor-sub-sync

"Zipper" 算法专门解决字幕重叠问题：
1. 检测重叠事件
2. 动态调整起止时间
3. 确保一条结束 → 下一条开始

### 6.3 推荐方案

**自研轻量级时间轴优化器**，核心逻辑：
```python
def optimize_timeline(cues: list[Cue]) -> list[Cue]:
    # 1. 修复重叠
    for i in range(len(cues)-1):
        if cues[i].end > cues[i+1].start:
            cues[i].end = cues[i+1].start - 0.1  # 100ms gap
    
    # 2. 最短时长保护
    for cue in cues:
        if cue.duration < 1.0:
            cue.end = cue.start + 1.0
    
    # 3. 最长时长分割
    for cue in cues:
        if cue.duration > 8.0:
            split_cue(cue)  # 超过 8 秒的拆分为多条
    
    # 4. 阅读速度检查
    for cue in cues:
        chinese_chars = len(cue.text_cn)
        if chinese_chars / cue.duration > 5:  # 超过 5 字/秒
            cue.end = cue.start + chinese_chars / 4  # 调整到 4 字/秒
```

---

## 7. 翻译质量评估（TQE）

### 7.1 方案对比

| 方案 | 是否需要参考译文 | 本地运行 | 复杂度 | 准确性 |
|------|----------------|---------|--------|--------|
| **GEMBA-MQM**（LLM 评估） | 否 | ✅（Ollama） | 低 | ⭐⭐⭐⭐⭐ |
| **COMETKiwi** | 否 | ✅（PyTorch） | 中 | ⭐⭐⭐⭐ |
| **XCOMET** | 可选 | ✅（PyTorch） | 高 | ⭐⭐⭐⭐⭐ |
| **MetricX** | 是 | ❌（Google） | 高 | ⭐⭐⭐⭐⭐ |

### 7.2 GEMBA-MQM（⭐ 推荐首选）

**论文**: GEMBA-MQM (Kocmi & Federmann, 2023)

GEMBA-MQM 使用 LLM 来评估翻译质量，按照 MQM（Multidimensional Quality Metrics）框架对翻译错误进行分类和严重性打分。

**错误类型**：
- Accuracy（准确率）：添加/遗漏/误译
- Fluency（流畅度）：语法/拼写/标点
- Terminology（术语）：术语不一致
- Style（风格）：不合语域
- Locale（本地化）：格式/文化适配

**严重性等级**：
- Critical（严重）: 25 分
- Major（主要）: 5 分
- Minor（次要）: 1 分
- Minor Punctuation: 0.1 分

**实现方式**（用 Ollama 本地模型）：
```python
prompt = f"""评估以下日语→中文翻译的质量。

源语言（日语）：{source_text}
译文（中文）：{target_text}

请按 MQM 框架标注错误：
- 错误类型：Accuracy / Fluency / Terminology / Style / Locale
- 严重程度：Critical / Major / Minor
- 位置：在译文中标注

输出 JSON 格式。"""
```

**SubForge 已集成** GEMBA-MQM 并配合 refine 机制：
```
翻译 → GEMBA-MQM 评分 → 低分段落 → 重新翻译 → 再次评分 → 通过
```

### 7.3 COMETKiwi（参考）

**项目**: https://github.com/Unbabel/COMET

**模型**: `Unbabel/wmt22-cometkiwi-da`（参考无关）

```python
from comet import download_model, load_from_checkpoint

model = load_from_checkpoint(download_model("Unbabel/wmt22-cometkiwi-da"))
data = [{"src": "日本語原文", "mt": "中文翻译"}]
scores = model.predict(data)
```

**劣势**：需要下载 PyTorch 模型（~1.5GB），且对动漫领域可能不如 GEMBA-MQM 准确。

### 7.4 推荐方案

**直接使用 GEMBA-MQM + 同一个 Ollama 模型**：
- 零额外依赖（不需要下载新模型）
- 与翻译模型共享同一个 Ollama 实例
- 错误分类可操作性强（能知道具体哪里错了）
- 评分结果可以直接用于 refine 机制

---

## 8. 推荐实现方案汇总

### 8.1 各功能实现路径

| 功能 | 推荐方案 | 额外依赖 | 预计代码量 |
|------|---------|---------|-----------|
| **术语表系统** | SakuraLLM GPT 字典格式 → prompt 拼接 | 无 | ~50 行 |
| **翻译记忆库** | 两层 JSONL 缓存（精确匹配 + TM） | 无 | ~100 行 |
| **OP/ED 检测** | SenseVoice 音频事件分类（首选）/ AniChapters（备选） | SenseVoice（可选） | ~80 行 |
| **多 Agent 审查** | 5 个独立函数 + ThreadPoolExecutor + 总编聚合 | 无 | ~200 行 |
| **断点续传** | agent-resume 或自行实现 JSONL checkpoint | 无 | ~50 行 |
| **时间轴优化** | 自研轻量级优化器（重叠+时长+阅读速度） | 无 | ~150 行 |
| **翻译质量评估** | GEMBA-MQM + Ollama 同一模型 | 无 | ~80 行 |

### 8.2 关键设计原则

1. **零额外依赖优先**：术语表、翻译记忆、多 Agent 审查、时间轴优化、断点续传 都不需要额外安装任何库
2. **JSONL 是统一的持久化格式**：checkpoint、翻译记忆、审查结果都用 JSONL
3. **所有 AI 能力共享同一个 Ollama 实例**：翻译、审查、质量评估都走同一个模型
4. **阶段间解耦**：每个阶段只依赖前一个阶段的输出文件，不共享内存状态

### 8.3 Pipeline 完整架构

```
视频文件
  │
  ├─ [阶段 1] 音频提取
  │     checkpoint → audio.wav
  │
  ├─ [阶段 2] ASR 识别（Anime Whisper）
  │     checkpoint → transcript.json（日语文本 + 词级时间戳）
  │
  ├─ [阶段 2.5] OP/ED 检测（SenseVoice 可选）
  │     → 跳过标记
  │
  ├─ [阶段 3] 说话人分离（可选）
  │     checkpoint → diarization.json
  │
  ├─ [阶段 4] 翻译（SakuraLLM + 术语表 + 翻译记忆）
  │     checkpoint → translated.json
  │     translation_memory.jsonl ← 更新
  │
  ├─ [阶段 5] 字幕生成 + 时间轴优化
  │     → subtitles.srt / subtitles.ass
  │
  ├─ [阶段 6] 多 Agent 脚本审查
  │     ├─ 一致性 Agent → 角色名/术语一致性
  │     ├─ 逻辑 Agent    → 对话逻辑通顺性
  │     ├─ 翻译自然度 Agent → 中文自然度
  │     ├─ ASR 纠错 Agent  → ASR 误听检测
  │     └─ 总编 Agent     → 汇总 → 修正
  │     → 修正后的 subtitles_fixed.srt
  │
  ├─ [阶段 7] 翻译质量评估（GEMBA-MQM）
  │     → quality_report.json
  │
  └─ [阶段 8] 嵌入视频
        → output.mp4（带字幕）
```

### 8.4 各阶段的可选性

| 阶段 | 必需？ | 说明 |
|------|-------|------|
| 音频提取 | ✅ 必需 | |
| ASR 识别 | ✅ 必需 | |
| OP/ED 检测 | ❌ 可选 | 节省 ASR 资源 |
| 说话人分离 | ❌ 可选 | 进阶功能 |
| 翻译 | ✅ 必需 | |
| 字幕生成 | ✅ 必需 | |
| 时间轴优化 | ⚠️ 推荐 | 改善观感 |
| 多 Agent 审查 | ⚠️ 推荐 | 提升翻译质量 |
| 质量评估 | ❌ 可选 | 诊断用 |
| 嵌入视频 | ✅ 必需 | |

### 8.5 参考资源汇总

| 功能 | 资源 | 链接 |
|------|------|------|
| 术语表 | SakuraLLM GPT 字典 | https://github.com/SakuraLLM/SakuraLLM |
| 术语表 | SakuraDict 社区字典 | https://github.com/Frzgunr1/SakuraDict |
| 翻译记忆 | SubForge MAPS + TM | https://github.com/JSKDLF/subforge |
| 翻译记忆 | JAVTrans 三层缓存 | https://github.com/jaykwok/jav-trans |
| OP/ED 检测 | SenseVoice 事件分类 | https://github.com/FunAudioLLM/SenseVoice |
| OP/ED 检测 | AniChapters | https://github.com/56cla/AniChapters |
| OP/ED 检测 | needle | https://github.com/aksiksi/needle |
| OP/ED 检测 | anatro-rs | https://github.com/inphynithus/anatro-rs |
| 多 Agent | CrewAI | https://github.com/joaomdmoura/crewai |
| 多 Agent | LangGraph | https://github.com/langchain-ai/langgraph |
| 多 Agent | TransAgents 论文 | https://gonzoml.substack.com/p/perhaps-beyond-human-translation |
| 断点续传 | agent-resume | https://github.com/MukundaKatta/agent-resume |
| 断点续传 | python-durable | https://github.com/WillemDeGroef/python-durable |
| 断点续传 | dagpipe | https://github.com/devilsfave/dagpipe |
| 时间轴优化 | subcap | https://github.com/bighippoman/subcap |
| 时间轴优化 | WhisperX | https://github.com/m-bain/whisperX |
| 时间轴优化 | anchor-sub-sync | https://github.com/ellite/anchor-sub-sync |
| 质量评估 | COMET | https://github.com/Unbabel/COMET |
| 质量评估 | GEMBA-MQM | https://aclanthology.org/2025.wmt-1.67/ |
| 质量评估 | SubForge QE | https://github.com/JSKDLF/subforge |