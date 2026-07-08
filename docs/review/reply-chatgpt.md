# 总体判断

你的方向是对的：**Anime Whisper + SakuraLLM + 本地 Ollama + 模块化流水线**很适合“个人本地生成动漫中文字幕”这个目标。附件里的方案已经覆盖了 ASR、翻译、说话人分离、术语表、翻译记忆、OP/ED 检测、多 Agent 审查、TQE 等关键方向，我下面以它作为基线评审。

我建议做三处较大调整：

1. **ASR 不要只押 Anime Whisper，而是做“主模型 + 可疑片段复核模型”的级联。** Anime Whisper 作为主力合理，因为它确实是面向日语动漫风格语音微调的模型，训练数据约 5300 小时、约 373 万个 Galgame/动漫风格语音文件。([Hugging Face][1])
2. **翻译主线用 Sakura 没问题，但必须保留许可证友好的 Qwen 备用通道。** SakuraLLM 明确采用 CC BY-NC-SA 4.0，项目方也强调 Sakura 及其衍生模型禁止商业用途；个人本地非商业使用通常问题不大，但只要未来想公开服务、收费、商业化，就必须切换方案。([GitHub][2])
3. **说话人分离/角色颜色不要放太前。** 目前没看到真正“动漫专用、角色级”的公开 diarization 模型。pyannote、DiariZen、Sortformer 都更偏通用会议/对话场景；动漫里有 BGM、音效、夸张声线、重叠说话、同声优多角色，这个功能很容易做成“看起来高级但经常错”。([Hugging Face][3])

---

# 任务 1：项目方案评审

## 1. ASR：Anime Whisper 作为主力合理，但建议做级联

### 我的判断

**Anime Whisper 可以作为默认主力。**
原因很简单：它的训练域和你的任务高度重合。普通 Whisper、ReazonSpeech、Qwen3-ASR、SenseVoice 都更偏通用语音，而 Anime Whisper 明确针对日语动漫/游戏风格台词。对于动漫字幕，领域匹配有时比通用榜单更重要，因为常见错误往往不是普通发音，而是角色名、语气词、夸张演技、非标准语速和背景音乐下的台词。([Hugging Face][1])

但我不建议把它写死成唯一核心。更稳的设计是：

| 场景                  | 推荐模型                                        | 为什么                                                                                           |
| ------------------- | ------------------------------------------- | --------------------------------------------------------------------------------------------- |
| 默认整集 ASR            | **Anime Whisper**                           | 动漫域匹配最好，适合做第一版结果。([Hugging Face][1])                                                          |
| 快速草稿 / 低显存 / 音频事件检测 | **SenseVoice Small**                        | SenseVoice 不只是 ASR，还支持语种、情感和音频事件检测，后面做 BGM/笑声/掌声/哭声识别很有用。([GitHub][4])                        |
| 可疑片段复核              | **Qwen3-ASR-1.7B 或日语微调版 Qwen3-ASR-1.7B-JA** | Qwen3-ASR 支持 52 种语言/方言，日语微调版还专门提到改善专有名词识别，适合复核角色名/招式名。([Hugging Face][5])                     |
| 时间戳优化               | **WhisperX / stable-ts**                    | WhisperX 提供 VAD、词级时间戳和 pyannote 说话人分离集成；stable-ts 重点解决 Whisper 时间戳稳定性、静音抑制、字幕重组。([GitHub][6]) |
| 性能优化                | **faster-whisper**                          | CTranslate2 推理通常更快、更省显存，支持 int8 量化，适合批量处理。([GitHub][7])                                       |

### 建议改法

不要做“选择一个 ASR 模型”，而是做：

> Anime Whisper 生成主 transcript → 用规则找可疑片段 → 对可疑片段用 Qwen3-ASR-JA / SenseVoice 复核 → 只替换高置信度修正。

可疑片段可以包括：

* ASR 输出过短、过长、重复；
* 出现明显 Whisper 幻觉；
* 片段位于 BGM/OP/ED/爆炸音效附近；
* 中文翻译模型认为日文不通顺；
* 术语表中的角色名附近识别异常；
* 同一句日语被翻译成多种角色名。

这样比全量多模型投票更省时间，也更容易控制质量。

---

## 2. 翻译：SakuraLLM 是好选择，但许可证和备用模型必须前置设计

### SakuraLLM 是否适合？

**适合你的个人本地项目，尤其适合 ACGN 日中翻译。** SakuraLLM 系列就是为轻小说、Galgame、ACGN 文本优化的，和动漫字幕的语言风格很接近。你方案里把 Sakura-14B / Sakura-7B 作为主力，是合理的。([GitHub][2])

### 许可证是否影响个人使用？

一般来说，**个人本地非商业使用影响不大**。但注意三点：

1. **不能商用。** SakuraLLM 明确是 CC BY-NC-SA 4.0，并强调 Sakura 及衍生模型禁止任何商业用途。([GitHub][2])
2. **如果你发布衍生模型、服务或商业翻译结果，风险会明显上升。** CC BY-NC-SA 还包含署名和相同方式共享要求。([Creative Commons][8])
3. **如果未来想做公开工具，最好把 Sakura 设计成“非商业插件”，而不是唯一核心。**

### 备用方案建议

| 方案                                 | 优势                                        | 劣势                                | 建议定位          |
| ---------------------------------- | ----------------------------------------- | --------------------------------- | ------------- |
| **Sakura-14B / 7B**                | ACGN 风格强，角色名、人称、语气更适合                     | 非商业许可证                            | 个人本地主力        |
| **Qwen2.5 / Qwen3 Instruct**       | Qwen2.5 多数模型 Apache 2.0，许可证更友好，Ollama 支持好 | ACGN 风格不如 Sakura，需要强 prompt + 术语表 | 商业/开源发布备用     |
| **GalTransl / Sakura-GalTransl**   | 视觉小说/对话文本强，和动漫台词接近                        | 同样偏非商业许可证                         | Sakura 备选风格模型 |
| **MADLAD / NLLB / OPUS-MT 类传统 MT** | 可作为离线低成本 fallback                         | 风格、上下文、人称处理通常弱                    | 兜底，不建议主力      |

Qwen2.5 系列模型许可证更适合长期工程化和潜在发布，所以我会把翻译接口做成：

```text
TranslatorAdapter
  ├── SakuraTranslator      # 默认，个人非商业
  ├── QwenTranslator        # 许可证友好 fallback
  ├── GalTranslTranslator   # ACGN 备选
  └── ExternalAPITranslator # 可选，不作为默认
```

---

## 3. 说话人分离：不要过早承诺“角色识别”

### pyannote 在动漫场景是否合适？

**可以用，但只能当“说话人片段提示”，不要当“角色识别”。** pyannote community-1 的优点是工程成熟，并且有 exclusive diarization 输出，能更方便和转录时间戳对齐。([Hugging Face][3])

但动漫场景的问题是：

* 声优会刻意变声；
* 同一角色在哭、喊、耳语时声纹变化很大；
* 不同角色可能同声优；
* BGM 和音效长期覆盖语音；
* 台词经常短到不足以稳定聚类；
* OP/ED、旁白、群像对话会干扰分离。

DiariZen 和 Sortformer 值得关注。DiariZen 是 EEND 系路线，基于 WavLM Large + Conformer，并在多个公开说话人分离数据集上训练；Sortformer 是 NVIDIA 的端到端 diarization 方案，支持 offline/online 版本。([Hugging Face][9])

### 建议定位

我建议把功能拆成三层：

| 层级     | 功能                   | 是否推荐进早期版本  |
| ------ | -------------------- | ---------- |
| 说话人分段  | 这句和上一句是不是同一个人说的      | 可以做，但作为辅助  |
| 角色名映射  | 把 speaker_01 映射为“千束” | 推迟，需要人工确认  |
| 角色颜色字幕 | 不同角色不同颜色             | 推迟，否则错了很显眼 |

更稳的 MVP 是：**先输出 speaker_01 / speaker_02 作为隐藏元数据，不直接显示在字幕里。** 后面人工校对时，让用户把 speaker_01 映射成角色名，再用于全剧一致性。

---

# 架构设计优化

## 1. 工作流阶段建议重排

你现在的阶段划分是“基础管道 → 管道完善 → 体验完善 → 高级功能”。方向没问题，但具体优先级需要调整。

我建议工程阶段改成：

```text
A. Ingest / Preprocess
   - 视频探测、音轨提取、采样率统一、VAD、OP/ED 标记

B. ASR / Alignment
   - Anime Whisper 主识别
   - 可疑片段复核
   - 时间戳修正

C. Translation
   - 术语表
   - 上下文窗口
   - 翻译记忆
   - JSON 输出校验

D. Subtitle Postprocess
   - 断句、合并、CPS 阅读速度控制
   - ASS/SRT 输出
   - 双语字幕
   - 样式模板

E. QC / Review
   - 规则检查
   - LLM 审查
   - 可疑行标记
   - 人工校对导出

F. Render / Mux
   - 软字幕封装
   - 硬字幕压制
   - 字体检查
```

为什么这么拆？因为动漫字幕的质量不只取决于 ASR 和翻译，**时间轴、断句、阅读速度、术语一致性**对观看体验影响非常大。很多自动字幕项目不是死在模型上，而是死在“字幕不好看、不好读、时间轴怪”。

---

## 2. JSONL checkpoint 不够可靠，建议 SQLite + 文件产物

JSONL 适合做 append-only 日志、翻译记忆、审查记录，但不适合作为唯一 checkpoint。原因是：

* 中途写入失败可能出现半行 JSON；
* 多进程/多线程写入需要额外锁；
* 查询某一集、某一段、某一阶段状态很麻烦；
* 后期做 Web UI、批处理、失败重试会越来越难维护。

我建议：

```text
project/
  jobs.sqlite
  assets/
    ep01.audio.wav
    ep01.transcript.json
    ep01.translation.json
    ep01.subtitle.ass
    ep01.output.mkv
  logs/
    ep01.asr.jsonl
    ep01.translate.jsonl
    ep01.review.jsonl
  tm/
    translation_memory.sqlite 或 translation_memory.jsonl
```

SQLite 很适合作为本地任务状态库，因为它是单文件、轻量、自包含，并且支持事务和崩溃恢复；官方文档也明确强调 SQLite 是 small/fast/self-contained/high-reliability 的嵌入式数据库，并支持 ACID 事务。([SQLite官网][10])

建议表结构不用复杂：

```text
jobs             # 每个视频/每集的任务
segments         # 每句字幕，含 start/end/asr_text/zh_text/status
stage_runs       # 每个阶段的运行状态、模型版本、prompt hash
artifacts        # 产物路径、hash、创建时间
glossary         # 术语表
translation_mem  # 翻译记忆
review_issues    # 审查问题
```

---

## 3. 多 Agent 不引入 CrewAI/LangGraph 是明智的，但要晚一点做

你的“不引入 CrewAI/LangGraph，只用 ThreadPoolExecutor 并行调 Ollama”的想法是对的。原因是：这个项目的多 Agent 本质不是复杂规划，而是**多个审稿 prompt 对同一批字幕做结构化检查**。引入框架会增加状态管理、调试、依赖和学习成本。

但我建议先不要做 5 个 Agent。早期更稳的是：

```text
规则检查器
  - 字幕时长
  - CPS 阅读速度
  - 空翻译
  - 行数过长
  - 术语不一致

LLM 审查器
  - 只看可疑行
  - 输出 JSON patch

总编修复器
  - 只接受结构化修改
  - 不允许随意重写全片
```

为什么？因为 LLM 多 Agent 最容易出现的问题是：**审查成本高、意见互相冲突、修正后反而引入新错、很难评估提升。** 对这个项目来说，“可疑行定位”比“五个 Agent 全片重写”更有价值。

---

# 功能优先级调整

## 我建议提前的功能

| 功能                            | 建议        | 为什么                                                                                           |
| ----------------------------- | --------- | --------------------------------------------------------------------------------------------- |
| **术语表 Glossary**              | 提前到 MVP   | 动漫字幕最容易错的是角色名、地名、招式名；术语表是性价比最高的质量提升。                                                          |
| **翻译记忆 TM**                   | 提前到 MVP+1 | 同一句口头禅、招式名、称呼在整季反复出现，TM 能显著提升一致性。                                                             |
| **Checkpoint/Resume**         | 提前到 MVP   | 整集处理时间长，中断后重跑非常痛苦；这是工程可用性的底座。                                                                 |
| **时间轴优化**                     | 提前到 MVP   | 字幕体验高度依赖时间轴和阅读速度，不应放到阶段 2。                                                                    |
| **双语字幕模式**                    | 提前到 MVP+1 | 便于人工校对，也便于用户信任模型结果。                                                                           |
| **导出到 Aegisub/Subtitle Edit** | 提前        | 不必一开始做完整校对 UI，先兼容成熟工具。Aegisub 本身就支持音频定时、样式、实时预览；Subtitle Edit 支持本地离线编辑和大量字幕格式。([Aegisub][11]) |

## 我建议推迟的功能

| 功能                | 建议          | 为什么                               |
| ----------------- | ----------- | --------------------------------- |
| **说话人分离 + 角色颜色**  | 推迟          | 错了会很显眼，而且动漫场景没有可靠公开专用模型。          |
| **5 Agent 全量审查**  | 推迟          | 先做规则检查 + 可疑行 LLM 审查，收益更稳定。        |
| **TQE/GEMBA-MQM** | 推迟          | 自动评分不等于用户体验，早期更该做人工小样本 benchmark。 |
| **Web UI**        | 推迟到 CLI 稳定后 | UI 会放大底层状态管理问题，先把 pipeline 跑稳。    |
| **插件系统**          | 很后面         | 过早抽象会拖慢 MVP。                      |

---

# 任务 2：补充功能建议

## 1. 我认为最有价值的新增功能

### 1. 可疑字幕行检测，这是最接近“杀手级”的功能

不要让用户从头校对 500 行字幕，而是告诉用户：

> 这一集有 37 行可能有问题，优先检查这些。

可疑行可以来自：

* ASR 低置信度；
* 音频中有 BGM/音效/多人重叠；
* 翻译 JSON 格式修复过；
* 中文过长、CPS 过高；
* 术语表命中但翻译不一致；
* 同一日文对应多个中文；
* LLM 审查器认为语义不通。

为什么它是杀手级？因为自动字幕很难 100% 正确，但如果能把人工校对量从 500 行降到 30～50 行，用户体验会直接提升一个量级。

---

### 2. 术语表自动建议

流程可以是：

```text
ASR 日文 transcript
  → LLM 提取人名/地名/组织名/招式名/口头禅
  → 生成候选术语表
  → 用户确认
  → 后续翻译强制一致
```

为什么有价值？动漫翻译最常见的灾难不是普通句子，而是专有名词反复错。尤其是“同一个名字被翻成三种中文”“招式名每次不一样”“姐姐/前辈/老师称呼不一致”。

---

### 3. 整季级一致性记忆

不要只按单集处理。应该有：

```text
series_memory.json / sqlite
  - 角色名
  - 角色关系
  - 口癖
  - 称呼方式
  - 术语
  - 上一集关键翻译决策
```

为什么？字幕组人工翻译时很重视“整季一致性”。自动工具如果每集独立跑，会出现第一集叫“星野爱”，第二集变成“星野艾”的问题。

---

### 4. 外挂字幕优先模式

很多 MKV 本身带日文字幕、英文字幕或官方字幕。建议先探测：

```text
如果视频内有日文字幕：
  直接提取日文字幕 → 翻译
否则：
  ASR
```

为什么？已有字幕的时间轴和文本通常比 ASR 更准。不要为了“自动 ASR”而浪费已有信息。

---

### 5. A/B 模型评测小工具

内置一个小 benchmark：

```text
gold/
  ep01_clip_001.wav
  ep01_clip_001.ref_ja.txt
  ep01_clip_001.ref_zh.txt
```

每次换 ASR/翻译模型，自动输出：

* CER；
* 术语命中率；
* 空翻译率；
* JSON 格式失败率；
* 平均 CPS；
* 人工标记错误数。

为什么？否则你会陷入“感觉这个模型更好”的主观判断。

---

### 6. 字幕阅读体验优化

建议内置这些规则：

* 单行不超过 18～22 个中文字；
* 双行不超过 2 行；
* 最短显示时间 0.8～1.0 秒；
* 最长显示时间按语义切分；
* CPS 过高时自动拆分或延长；
* 相邻字幕间隔过短时合并；
* 中文和日文双语模式分层显示。

这比再换一个翻译模型更容易被用户感知到。

---

# 任务 3：补充调研：可能遗漏的重要项目

下面是我认为值得补充关注的项目。不是每个都建议纳入主线，有些更适合作为 benchmark、备用模块或参考实现。

---

## 1. 日语 ASR / 动漫口语方向

| 项目                                                           | 与现有方案对比                                                                     | 为什么值得关注                                                           |
| ------------------------------------------------------------ | --------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| **Neosophie/Qwen3-ASR-1.7B-JA**                              | 相比 Anime Whisper，它不是动漫专用，但专门针对日语和专有名词做了微调；劣势是集成、时间戳和速度可能不如 Whisper 系。       | 动漫里角色名、地名、招式名非常关键，它适合作为“可疑片段复核模型”。([Neosophie][12])               |
| **NVIDIA Parakeet TDT-CTC 0.6B JA**                          | 相比 Anime Whisper，它是 NeMo 生态的日语 ASR，支持标点；劣势是字幕时间戳生态不如 WhisperX/stable-ts 方便。 | 适合做日语 ASR benchmark，尤其是你想比较非 Whisper 架构时。([Hugging Face][13])     |
| **ReazonSpeech ESPnet / NeMo models**                        | 泛日语语音数据规模大，工程生态成熟；劣势是非动漫域。                                                  | 适合作为通用日语 fallback，尤其是新闻、访谈、广播类视频。([Hugging Face][14])             |
| **japanese-asr/distil-whisper-large-v3-ja-reazonspeech-all** | Whisper 系，可能比通用 Whisper 更适合日语；劣势是仍非动漫专用。                                    | 如果能转 faster-whisper，可作为低延迟/批量处理候选。([Hugging Face][15])            |
| **efwkjn/whisper-ja-anime-v0.3**                             | 也是动漫关键词相关的 Whisper 日语模型；劣势是公开资料和评测相对少。                                      | 值得拿你自己的 10～20 分钟动漫样本和 Anime Whisper 对比，可能有惊喜。([Hugging Face][16]) |

---

## 2. 日语→中文翻译模型 / 工具

| 项目                                                        | 与现有方案对比                                                  | 为什么值得关注                                                           |
| --------------------------------------------------------- | -------------------------------------------------------- | ----------------------------------------------------------------- |
| **Sakura-GalTransl-7B-v3.7**                              | 和 Sakura 主线接近，更偏 Galgame/VN 对话文本；劣势是同样继承非商业限制。           | 动漫台词和 Galgame 台词风格相近，可作为 Sakura-7B/14B 的风格备选。([Hugging Face][17]) |
| **Qwen2.5 / Qwen3 Instruct**                              | ACGN 风格弱于 Sakura，但许可证和工程生态更友好。Qwen2.5 多数模型采用 Apache 2.0。 | 未来如果要开源、商用、做公开服务，Qwen 通道很重要。([Hugging Face][18])                  |
| **GalTransl**                                             | 偏视觉小说翻译工作流，不只是模型；劣势是不是专门字幕工具。                            | 它的术语、上下文、项目管理思路值得借鉴。([GitHub][2])                                 |
| **AiNiee / SakuraTranslator / RPGMaker_LLaMA_Translator** | 不是直接的视频字幕管道，但已支持 Sakura API 生态。                          | 可以参考它们怎么组织长文本翻译、术语表和上下文。([GitHub][2])                             |
| **MADLAD-400 / OPUS-MT 类传统 MT**                           | 稳定、轻量、可批量；劣势是 ACGN 风格、人称和上下文通常弱。                         | 不建议主力，但可作为兜底或对照组。([Hugging Face][19])                             |

---

## 3. 字幕生成 / 处理工具

| 项目                          | 与现有方案对比                                    | 为什么值得关注                                                      |
| --------------------------- | ------------------------------------------ | ------------------------------------------------------------ |
| **stable-ts**               | 比普通 Whisper 输出更重视时间戳稳定、静音抑制、字幕 regroup。    | 你的项目最终是“字幕”，不是纯 ASR，所以时间轴质量非常重要。([GitHub][20])               |
| **WhisperX**                | 集成 VAD、词级时间戳、说话人分离；劣势是依赖更多。                | 适合参考它的 pipeline，尤其是 alignment 和 diarization 接口。([GitHub][6]) |
| **Subtitle Edit**           | 成熟的字幕编辑/同步/格式转换工具，支持本地离线编辑。                | 早期不必自己做校对 UI，可以先导出给 Subtitle Edit。([GitHub][21])             |
| **Aegisub**                 | ASS 字幕样式、音频定时、视频预览能力强。                     | 动漫字幕样式强依赖 ASS，Aegisub 是很好的人工精修出口。([Aegisub][11])             |
| **ffsubsync / AutoSubSync** | 自动字幕同步工具；AutoSubSync 整合 ffsubsync、alass 等。 | 如果用户已有字幕但时间轴不准，可以直接修时间轴，不必重新 ASR。([GitHub][22])              |
| **SubsAI**                  | 离线跨平台字幕工具，支持字幕修改和翻译模型集成。                   | 可参考它的离线工作流和 UI 思路。([GitHub][23])                             |
| **SubForge**                | Rust CLI，覆盖转录、分段、翻译、评估、mux/burn。           | 它和你的目标很接近，适合研究其工程拆分方式。([GitHub][24])                         |

---

## 4. 动漫 / 视频字幕专用工具

| 项目                                 | 与现有方案对比                                        | 为什么值得关注                                          |
| ---------------------------------- | ---------------------------------------------- | ------------------------------------------------ |
| **N46Whisper**                     | 偏日语字幕生成 notebook，支持 faster-whisper、AI 翻译、双语输出。 | 很接近你的 MVP，可以参考其“日语字幕→翻译→双语字幕”的流程。([GitHub][25])  |
| **SubFlow**                        | 自动提取 MKV 字幕、调用本地 AI 或 API 翻译、再 remux 回视频。      | 这条路线很适合“已有日文字幕”的番剧，比 ASR 更准更快。([GitHub][26])     |
| **rockbenben/subtitle-translator** | 浏览器端批量字幕翻译，支持 SRT/ASS/VTT/LRC、分块压缩、并发。         | 可以参考它的长字幕分块、上下文压缩和批量翻译设计。([GitHub][27])          |
| **LLM-Subtrans**                   | 用 LLM 翻译字幕，支持 SRT/SSA/ASS/VTT。                 | 适合参考 LLM 翻译字幕时的上下文处理和格式保持。([GitHub][28])         |
| **Voice-Pro**                      | Gradio Web App，集成下载、分离、识别、翻译、TTS/配音。           | 如果你后面做 Web UI，可以参考它的一体化交互。([GitHub][29])         |
| **KrillinAI**                      | 更偏视频本地化全流程，包括转录、字幕、翻译、TTS 配音等。                 | 如果你未来想做“字幕 + 配音 + 本地化”，它是参考对象。([GitHub][30])     |
| **Manga Image Translator**         | 漫画图像翻译、嵌字、修补；不是视频字幕。                           | 虽然不是字幕工具，但 ACGN 专有名词、排版和本地化思路值得借鉴。([GitHub][31]) |

---

## 5. 音频事件检测 / OP/ED / BGM 处理

| 项目                           | 与现有方案对比                          | 为什么值得关注                                                              |
| ---------------------------- | -------------------------------- | -------------------------------------------------------------------- |
| **SenseVoice AED**           | 已在你方案中出现，但它的音频事件能力应该前置使用。        | 可识别 BGM、笑声、掌声、哭声、咳嗽等事件，对跳过 OP/ED 和标记可疑 ASR 片段有价值。([FunAudioLLM][32]) |
| **PANNs**                    | 基于 AudioSet 大规模音频事件分类，527 类音频标签。 | 可作为通用 BGM/音效检测 baseline。([GitHub][33])                               |
| **YAMNet**                   | AudioSet 预训练，输出 521 类音频事件。       | 轻量、通用，适合做简单音频事件标签。([TensorFlow][34])                                 |
| **ATST-SED / PretrainedSED** | 更新的音频事件检测方向。                     | 如果你后面认真做 BGM/语音分类，可作为进阶研究对象。([GitHub][35])                           |
| **Demucs**                   | 音源分离，可分离 vocals/accompaniment 等。 | 对 BGM 很重的片段，可以尝试语音增强后再 ASR；但会增加耗时和伪影。([GitHub][36])                  |
| **AniChapters**              | 检测本地动漫剧集 OP/ED 并生成章节。            | 比纯音频分类更适合“整季 OP/ED 跳过”。([GitHub][37])                                |
| **needle**                   | 用相似片段搜索检测剧集 intro/ending。        | 对整季批量处理非常实用，因为 OP/ED 往往重复。([GitHub][38])                             |
| **open-anime-timestamps**    | 动漫 OP/ED 时间戳数据库/抓取项目。            | 可以作为外部时间戳参考，但覆盖率和准确性要验证。([GitHub][39])                               |

---

## 6. 说话人分离 / 日语场景

| 项目                                     | 与现有方案对比                                         | 为什么值得关注                                                     |
| -------------------------------------- | ----------------------------------------------- | ----------------------------------------------------------- |
| **pyannote.audio community-1**         | 工程成熟，exclusive diarization 方便和 ASR 对齐；劣势是非动漫专用。 | 适合作为默认 diarization baseline，但不要直接等同角色识别。([Hugging Face][3]) |
| **DiariZen**                           | EEND 路线，支持重叠说话，基于 WavLM Large + Conformer。      | 动漫经常重叠/插话，DiariZen 值得和 pyannote 对比。([Hugging Face][40])     |
| **NVIDIA Sortformer**                  | 端到端 diarization，NeMo 生态，支持 offline/online。      | 如果你未来愿意引入 NeMo，它是强候选。([Hugging Face][41])                   |
| **Kotoba-Whisper v2.2 内置 diarization** | 集成简单，适合快速出结果。                                   | 适合 MVP 后快速验证“说话人分离是否值得继续投入”。([Hugging Face][42])            |
| **WhisperX diarization pipeline**      | 把 ASR、alignment、pyannote diarization 组合好。       | 适合参考接口，不一定直接作为主系统。([GitHub][6])                             |

---

# 任务 4：如果由我主导，我会这样选技术栈

## 推荐技术栈

```text
核心语言：
  Python

视频/音频：
  FFmpeg / ffprobe

ASR：
  主力：Anime Whisper
  快速/AED：SenseVoice Small
  复核：Qwen3-ASR-1.7B-JA 或 Qwen3-ASR-1.7B
  时间戳：stable-ts 或 WhisperX 思路

翻译：
  主力：Sakura-7B/14B via Ollama
  许可证友好备用：Qwen2.5/Qwen3 Instruct via Ollama
  风格备选：GalTransl / Sakura-GalTransl

字幕：
  pysubs2
  ASS 优先，SRT 作为兼容输出
  Aegisub / Subtitle Edit 作为人工校对出口

状态管理：
  SQLite：job、segment、stage_run、artifact、glossary、TM
  JSONL：日志、debug、审查记录
  文件产物：wav/json/ass/mkv

质量控制：
  规则检查优先
  LLM 只审查可疑行
  不引入 CrewAI/LangGraph

后期 UI：
  先 CLI
  再 Gradio/FastAPI + Web UI
```

---

# 最短 MVP 路径

我建议 MVP 不要贪大，目标是：

> 输入一集动漫视频，输出可看的中文字幕 ASS/MKV，并且中断可恢复。

## MVP 第 1 步：做 3～5 分钟金标准样本

手工标注几段：

* 日文原文；
* 正确中文；
* 角色名/术语；
* 时间轴。

为什么？没有 gold sample，你无法判断 Anime Whisper、SenseVoice、Qwen3-ASR、Sakura-7B、Sakura-14B 到底谁更适合你的实际番剧。

---

## MVP 第 2 步：完成最小闭环

```text
video.mkv
  → ffmpeg extract audio
  → Anime Whisper ASR
  → Sakura 翻译
  → pysubs2 输出 ASS/SRT
  → ffmpeg mux 到 MKV
```

只做这条，不做 diarization，不做多 Agent，不做 Web UI。

---

## MVP 第 3 步：加入术语表和上下文翻译

翻译时不要一行一行裸翻，至少要：

```text
上文 3～5 行
当前待翻译行
下文 3～5 行
术语表
角色名表
输出 JSON 数组，数量必须一致
```

为什么？日语大量省略主语，动漫台词尤其依赖上下文。一行一翻会导致人称、语气、称呼频繁错。

---

## MVP 第 4 步：SQLite checkpoint

做到：

* ASR 完成的 segment 不重跑；
* 翻译失败的 chunk 可单独重试；
* 模型版本、prompt hash、输入文件 hash 可追踪；
* 输出字幕可复现。

---

## MVP 第 5 步：可疑行检测 + 导出校对

先不要做复杂人工校对 UI。输出：

```text
episode.ass
episode.review.html
episode.suspicious.json
```

`review.html` 里列出可疑行、原文、译文、原因。用户可以用 Aegisub/Subtitle Edit 修改 ASS。

---

# 最容易翻车的坑

## 1. 只看 ASR CER，不看字幕可用性

CER 低不代表字幕好。字幕还要看：

* 是否断句自然；
* 时间轴是否舒服；
* 翻译是否符合上下文；
* 角色名是否一致；
* 阅读速度是否合理。

---

## 2. 把 diarization 当角色识别

speaker_01 不是“某个角色”。说话人聚类只是声音相似性，不理解剧情、画面和角色身份。动漫角色识别最好做成“人工确认 + 后续自动一致化”。

---

## 3. 一行一翻

日语动漫台词省略太多，一行一翻会造成：

* 他/她/我/你混乱；
* 敬语关系错；
* 角色语气丢失；
* 前后术语不一致。

必须 chunk 翻译，并带上下文和术语表。

---

## 4. 过早做 Web UI

底层状态、缓存、失败重试没做好时，Web UI 会让问题更难调。先 CLI，稳定后再 UI。

---

## 5. LLM 输出不稳定

翻译模型必须强制结构化输出，并做校验：

* 输入 N 行，输出必须 N 行；
* 不允许合并、删除、增加字幕；
* JSON parse 失败要自动修复；
* 每行保留 segment_id；
* 修复前后要保存日志。

---

## 6. 字体和 ASS 渲染问题

中文字幕硬压最常见坑：

* 用户机器没有指定字体；
* Windows/Linux 字体名不一致；
* FFmpeg libass 找不到字体；
* 描边太细导致复杂画面看不清；
* 双语字幕遮挡画面。

建议随项目提供字体配置说明，但不要直接分发有版权风险的字体文件。

---

## 7. 模型加载/卸载拖慢批处理

批量处理多集时，不要每集重新加载 ASR 和翻译模型。应该：

```text
启动 worker
  → 加载 ASR
  → 连续处理多集 ASR
  → 释放 ASR
  → 加载翻译模型
  → 连续翻译多集
```

否则显存抖动和加载时间会非常浪费。

---

# 最终优先级建议

## 马上该做

1. **完成 CLI 最小闭环：视频 → ASR → 翻译 → ASS/SRT → mux。**
2. **引入 SQLite checkpoint，而不是只靠 JSONL。**
3. **把术语表提前到 MVP。**
4. **做 3～5 分钟人工 gold sample，用真实动漫片段评测 Anime Whisper / SenseVoice / Qwen3-ASR。**
5. **做字幕后处理：断句、两行限制、CPS、最短显示时间。**
6. **输出可疑行报告，让用户只校对高风险字幕。**

## 近期再做

1. 翻译记忆库；
2. 双语字幕；
3. 批量处理；
4. OP/ED 检测；
5. 外挂日文字幕优先模式；
6. Qwen 许可证友好备用翻译通道。

## 后面再说

1. 角色级说话人分离；
2. 多角色颜色字幕；
3. 5 Agent 全量审查；
4. TQE/GEMBA-MQM；
5. Web UI；
6. 插件系统；
7. 配音/TTS 本地化。

一句话总结：**你现在最大的问题不是模型不够多，而是要把“术语一致性、时间轴、checkpoint、可疑行校对”提前。Anime Whisper + Sakura 可以先跑通，但架构上必须保留 ASR 复核模型和许可证友好的翻译备用通道。**

[1]: https://huggingface.co/litagin/anime-whisper?utm_source=chatgpt.com "litagin/anime-whisper"
[2]: https://github.com/SakuraLLM/SakuraLLM?utm_source=chatgpt.com "SakuraLLM/SakuraLLM: 适配轻小说/Galgame的日中翻译大 ..."
[3]: https://huggingface.co/pyannote/speaker-diarization-community-1?utm_source=chatgpt.com "pyannote/speaker-diarization-community-1"
[4]: https://github.com/FunAudioLLM/SenseVoice?utm_source=chatgpt.com "FunAudioLLM/SenseVoice: Multilingual speech ..."
[5]: https://huggingface.co/Qwen/Qwen3-ASR-1.7B?utm_source=chatgpt.com "Qwen/Qwen3-ASR-1.7B - Hugging Face"
[6]: https://github.com/m-bain/whisperx?utm_source=chatgpt.com "WhisperX: Automatic Speech Recognition with Word- ..."
[7]: https://github.com/SYSTRAN/faster-whisper?utm_source=chatgpt.com "Faster Whisper transcription with CTranslate2"
[8]: https://creativecommons.org/cc-licenses/?utm_source=chatgpt.com "Sharing Openly, Sharing Globally"
[9]: https://huggingface.co/BUT-FIT/diarizen-wavlm-large-s80-md-origin?utm_source=chatgpt.com "BUT-FIT/diarizen-wavlm-large-s80-md-origin - Hugging Face"
[10]: https://sqlite.org/?utm_source=chatgpt.com "SQLite Home Page"
[11]: https://aegisub.org/?utm_source=chatgpt.com "Aegisub - Aegisub Advanced Subtitle Editor"
[12]: https://neosophie.com/en/blog/20260427-qwen-finetuned-model?utm_source=chatgpt.com "Released the Highest-Accuracy Japanese ASR Model for Free"
[13]: https://huggingface.co/nvidia/parakeet-tdt_ctc-0.6b-ja?utm_source=chatgpt.com "nvidia/parakeet-tdt_ctc-0.6b-ja"
[14]: https://huggingface.co/reazon-research/reazonspeech-espnet-v1?utm_source=chatgpt.com "reazon-research/reazonspeech-espnet-v1"
[15]: https://huggingface.co/japanese-asr?utm_source=chatgpt.com "Japanese ASR"
[16]: https://huggingface.co/models?pipeline_tag=automatic-speech-recognition&search=ja&sort=likes&utm_source=chatgpt.com "Automatic Speech Recognition Models"
[17]: https://huggingface.co/SakuraLLM/Sakura-GalTransl-7B-v3.7?utm_source=chatgpt.com "SakuraLLM/Sakura-GalTransl-7B-v3.7"
[18]: https://huggingface.co/Qwen/Qwen2.5-7B/blob/main/LICENSE?utm_source=chatgpt.com "LICENSE · Qwen/Qwen2.5-7B at main"
[19]: https://huggingface.co/docs/transformers/en/model_doc/madlad-400?utm_source=chatgpt.com "MADLAD-400"
[20]: https://github.com/jianfch/stable-ts?utm_source=chatgpt.com "jianfch/stable-ts: Transcription, forced alignment, and audio ..."
[21]: https://github.com/SubtitleEdit/subtitleedit?utm_source=chatgpt.com "the subtitle editor"
[22]: https://github.com/smacke/ffsubsync?utm_source=chatgpt.com "smacke/ffsubsync: Automagically synchronize subtitles with ..."
[23]: https://github.com/absadiki/subsai?utm_source=chatgpt.com "absadiki/subsai: 🎞️ Subtitles generation tool (Web-UI ..."
[24]: https://github.com/deusjin/subforge?utm_source=chatgpt.com "deusjin/subforge: Rust CLI for AI subtitle workflows ..."
[25]: https://github.com/Ayanaminn/N46Whisper?utm_source=chatgpt.com "Ayanaminn/N46Whisper: Whisper based Japanese subtitle ..."
[26]: https://github.com/topics/subtitle-translator?l=python&o=asc&s=stars&utm_source=chatgpt.com "subtitle-translator"
[27]: https://github.com/rockbenben/subtitle-translator?utm_source=chatgpt.com "️ Subtitle Translator"
[28]: https://github.com/machinewrapped/llm-subtrans?utm_source=chatgpt.com "machinewrapped/llm-subtrans"
[29]: https://github.com/abus-aikorea/voice-pro?utm_source=chatgpt.com "abus-aikorea/voice-pro: Gradio WebUI ..."
[30]: https://github.com/krillinai/KrillinAI?utm_source=chatgpt.com "krillinai/KrillinAI: AI video translation & dubbing tool for ..."
[31]: https://github.com/zyddnys/manga-image-translator?utm_source=chatgpt.com "Manga/Image Translator (English Readme)"
[32]: https://funaudiollm.github.io/?utm_source=chatgpt.com "FunAudioLLM"
[33]: https://github.com/qiuqiangkong/audioset_tagging_cnn?utm_source=chatgpt.com "qiuqiangkong/audioset_tagging_cnn"
[34]: https://www.tensorflow.org/hub/tutorials/yamnet?utm_source=chatgpt.com "Sound classification with YAMNet | TensorFlow Hub"
[35]: https://github.com/fschmid56/PretrainedSED?utm_source=chatgpt.com "fschmid56/PretrainedSED"
[36]: https://github.com/facebookresearch/demucs?utm_source=chatgpt.com "facebookresearch/demucs: Code for the paper Hybrid ..."
[37]: https://github.com/56cla/AniChapters?utm_source=chatgpt.com "56cla/AniChapters: Automatic anime OP/ED detection and ..."
[38]: https://github.com/aksiksi/needle?utm_source=chatgpt.com "aksiksi/needle: A CLI tool that finds ..."
[39]: https://github.com/jonbarrow/open-anime-timestamps?utm_source=chatgpt.com "jonbarrow/open-anime-timestamps: database and scraper ..."
[40]: https://huggingface.co/BUT-FIT/diarizen-wavlm-large-s80-md-v2?utm_source=chatgpt.com "BUT-FIT/diarizen-wavlm-large-s80-md-v2 - Hugging Face"
[41]: https://huggingface.co/nvidia/diar_sortformer_4spk-v1?utm_source=chatgpt.com "nvidia/diar_sortformer_4spk-v1"
[42]: https://huggingface.co/kotoba-tech/kotoba-whisper-v2.2?utm_source=chatgpt.com "kotoba-tech/kotoba-whisper-v2.2"
