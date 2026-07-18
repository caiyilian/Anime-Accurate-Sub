# Anime Accurate Sub — 详细开发方案

> 本文档将整个项目拆解为 10 个 Sprint、40+ 个子阶段，每个阶段包含验收目标和测试方法。
> 所有三个 LLM 推荐的项目都分配了对应的评估阶段。

---

## 一、需要本地评估的项目清单

以下是从三个大模型回复中提取的所有推荐项目，按类别整理。

### 1.1 端到端全流程项目（可作为底座参考）

| 项目 | 推荐来源 | 说明 |
|------|---------|------|
| **pyVideoTrans** | 豆包 | 视频→ASR→翻译→字幕→嵌入全流程，有 GUI、断点续传、批量处理 |
| **VideoLingo** | Gemini | Netflix 级字幕，三步翻译-反思-适配机制 |
| **WhisperJAV** | 我们已调研 | 最成熟的日语字幕流水线，有 anime pipeline |
| **JAVTrans** | 我们已调研 | Qwen3-ASR 动漫微调版，SpeechBoundary-JA 边界检测 |
| **AnimeTranslator** | 我们已调研 | SenseVoice + Whisper + DeepSeek，四层幻觉防御 |
| **SubForge** | ChatGPT | Rust CLI，翻译记忆 + GEMBA-MQM 质量评估 |
| **N46Whisper** | 豆包+ChatGPT | 日语字幕生成 notebook，参考流程设计 |
| **SubFlow** | ChatGPT | 提取 MKV 字幕 → 翻译 → remux |
| **Voice-Pro** | ChatGPT | Gradio Web App，集成下载/分离/识别/翻译/配音 |
| **KrillinAI** | ChatGPT | 视频本地化全流程（含配音） |

### 1.2 ASR 相关

| 项目 | 推荐来源 | 说明 |
|------|---------|------|
| **Anime Whisper** | 已定主力 | litagin/anime-whisper，5300 小时动漫数据微调 |
| **Faster-Whisper** | 已定 | CTranslate2 推理引擎，4x 加速 |
| **SenseVoice Small** | 三家都提 | 非自回归架构，极快，自带音频事件检测 |
| **Qwen3-ASR-1.7B-JA** | ChatGPT | 日语专有名词识别优化，适合做复核模型 |
| **efwkjn/whisper-ja-anime-v0.3** | ChatGPT | 另一个动漫 Whisper 微调版，需要对比 |
| **WhisperX** | Gemini+ChatGPT | 词级强制对齐，解决时间戳漂移 |
| **stable-ts** | ChatGPT | Whisper 时间戳稳定化 + 静音抑制 |
| **ReazonSpeech ESPnet/NeMo** | ChatGPT | 泛日语语音模型，作为 benchmark 参考 |

### 1.3 音频分离（人声/BGM）

| 项目 | 推荐来源 | 说明 |
|------|---------|------|
| **Demucs** | 豆包+Gemini+ChatGPT | Meta 开源，音源分离 SOTA 之一 |
| **UVR5** | 豆包+Gemini | 更偏人声提取，字幕组社区验证 |
| **BS-RoFormer** | Gemini | 字节跳动，频域+时域轴向注意力 |

### 1.4 OP/ED 检测 / 音频事件

| 项目 | 推荐来源 | 说明 |
|------|---------|------|
| **SenseVoice AED** | 三家都提 | ASR 模块自带音频事件分类（BGM/语音/音乐） |
| **PANNs** | ChatGPT | 527 类音频事件分类，基于 AudioSet |
| **YAMNet** | ChatGPT | 521 类音频事件，轻量 |
| **AniChapters** | 我们已调研 | 动漫 OP/ED 专用检测，音频指纹匹配 |
| **needle** | 我们已调研 | Rust 实现，相似片段搜索检测 intro/ending |
| **open-anime-timestamps** | ChatGPT | 动漫 OP/ED 时间戳数据库项目 |

### 1.5 翻译

| 项目 | 推荐来源 | 说明 |
|------|---------|------|
| **Sakura-14B-Qwen2.5-v1.0** | 已定主力 | ACGN 日中翻译最优 |
| **Sakura-7B-Qwen2.5-v1.0** | 已定 | 轻量版 |
| **GalTransl-7B-v3.7** | ChatGPT | 视觉小说对话优化 |
| **Qwen2.5/Qwen3 Instruct** | 已定备选 | Apache 2.0 许可证友好 |
| **LinguaGacha** | 豆包 | 原生支持 SakuraLLM 的字幕翻译工具 |
| **GalTransl 项目** | ChatGPT | 视觉小说翻译工作流参考 |

### 1.6 字幕处理

| 项目 | 推荐来源 | 说明 |
|------|---------|------|
| **pysubs2** | 已定 | Python 字幕操作库 |
| **ffsubsync** | 豆包+ChatGPT | 基于音频特征的自动字幕对齐 |
| **SubtitleEdit** | 豆包+ChatGPT | 最成熟的开源字幕编辑器，可调 CLI |
| **Aegisub** | ChatGPT | ASS 字幕编辑标准工具，适合人工校对出口 |
| **subcap** | 我们已调研 | 强制对齐 + 样式化 ASS 生成 |
| **VideoCaptioner** | 豆包 | LLM 语义级断句 |

### 1.7 说话人分离

| 项目 | 推荐来源 | 说明 |
|------|---------|------|
| **Kotoba-Whisper v2.2** | 已定入门 | ASR 内置 diarization |
| **pyannote.audio community-1** | 已调研 | 开源首选 |
| **DiariZen** | 三家都提 | EEND 路线，日语场景最优开源（DER 13.3%） |
| **NVIDIA Sortformer** | ChatGPT | 端到端 diarization，NeMo 生态 |

### 1.8 质量审查

| 项目 | 推荐来源 | 说明 |
|------|---------|------|
| **COMETKiwi** | 我们已调研 | 参考无关的翻译质量评估 |
| **GEMBA-MQM** | 我们已调研 | LLM 做翻译质量评估 |
| **SubForge QE** | 我们已调研 | 已集成 GEMBA-MQM + refine 机制 |

---

---

## 二、设计原则

### 2.1 领域分组

整个开发按 **音频域 → 文本域 → 工程域** 的顺序推进：

```
音频域（S0-S7）：   基础设施 → 参考评估 → ASR → 音频分离 → 说话人分离 → OP/ED 检测
                        ↓
文本域（S8-S11）：  翻译 → 字幕生成 → 质量审查
                        ↓
工程域（S12-S16）：  效率工具 → 集成 → 高级功能
```

### 2.2 每个 Sprint 的规模控制

- 每个 Sprint **2-4 个子阶段**
- 每个子阶段可独立验收
- 同 Sprint 内的子阶段可以并行
- 相邻 Sprint 之间共享同一个「领域上下文」，过渡平滑

### 2.3 评估先行，集成在后

每个模块都先做「评估阶段」（本地跑通推荐项目），再做「工程阶段」（集成到自己的 pipeline）。

---

## 三、开发阶段总览

```
音频域:
  S0   基础设施搭建（环境 + 模型 + 数据集）
  S1   参考项目评估 Part 1 — 全流程底座（pyVideoTrans / VideoLingo / WhisperJAV）
  S2   参考项目评估 Part 2 — 专项工具 + 底座决策
  S3   ASR 主力评估（Anime Whisper + Faster-Whisper 优化）
  S4   ASR 备选评估（SenseVoice / Qwen3 / efwkjn + 时间戳优化）
  S5   音频分离预处理（Demucs / UVR5 / BS-RoFormer）
  S6   说话人分离（Kotoba / pyannote / DiariZen / Sortformer）
  S7   OP/ED 检测（SenseVoice AED / AniChapters / needle）

文本域:
  S8   翻译模型评估（Sakura-7B/14B / GalTransl / Qwen 对比）
  S9   翻译工程实现（上下文窗口 + 术语表 + 翻译记忆）
  S10  字幕生成（pysubs2 + 时间轴优化 + 双语 + 样式模板）
  S11  质量审查（规则检查 + 可疑行检测 + 多 Agent + TQE）

工程域:
  S12  断点续传 + 批量处理
  S13  专有名词发现 + A/B 评测工具 + 外挂字幕优先
  S14  翻译 Adapter + 整季一致性记忆
  S15  全流程 CLI 集成
  S16  高级功能（角色颜色 + Web UI + 校对 + 插件）
```

---

## 四、详细阶段

---

### Sprint 0：基础设施搭建

**目标**：准备好开发环境、工具链、测试数据

**子阶段**：4 个（P0.1-P0.4）

| 子阶段 | 内容 | 工作量 | 状态 |
|--------|------|--------|------|
| P0.1 | Python 虚拟环境 + `pyproject.toml` + 核心依赖 + Torch CUDA | ~30min | ✅ 已完成 |
| P0.2 | FFmpeg 安装确认（含 libass）+ ffprobe | ~30min | ✅ 已完成 |
| P0.3 | Ollama 服务 + 模型下载（暂时搁置，改用 Sensenova API） | ~2h | ⏸️ 暂时搁置 |
| P0.4 | 测试数据集准备：HF v2 日语语音 200 条 + K-On! 视频下载 + Kitsunekko 字幕 | ~3h | ✅ 已完成 |

**过渡到 Sprint 1**：环境就绪 → 开始评估现有项目。

**验收**：
- [x] `pip install -e .` 安装成功，`import faster_whisper` 等无报错
- [x] `torch.cuda.is_available()` 返回 True
- [x] FFmpeg 可提取 16kHz mono WAV
- [ ] Ollama 至少一个模型能响应（暂时搁置，改用 Sensenova API）
- [x] 测试数据就绪（200 条 HF 语音 + K-On! 视频 + Kitsunekko 字幕）

---

### Sprint 1：参考项目评估 Part 1 — 全流程底座

**目标**：本地跑通 3 个最有可能作为底座的全流程项目

**子阶段**：3 个（S1.1-S1.3），可并行

| 子阶段 | 项目 | 耗时 | 可并行？| 状态 |
|--------|------|------|---------|:----:|
| S1.1 | **pyVideoTrans** — 安装 + 跑通全流程 + 评估替换 ASR/翻译的可行性 | 1 天 | ✅ | ✅ |
| S1.2 | **VideoLingo** — 安装 + 跑通 + 评估三步翻译机制 | 1 天 | ✅ | ✅ |
| S1.3 | **WhisperJAV** — anime pipeline 跑通 + VAD/分段逻辑评估 | 0.5 天 | ✅ | ✅ |

**Sprint 1 验收总览**：S1.1、S1.2、S1.3 全部完成，三个项目评估报告已归档。详见 `docs/evaluation/` 目录。

**过渡到 Sprint 2**：对底座项目有初步判断 → 继续评估专项工具补充信息。

**S1.1 验收**：
- [x] pyVideoTrans CLI 可运行，跑通 K-On! 14 集全流程
- [x] 记录：可复用模块清单 + 需修改模块清单 + 缺失功能清单（详见 `docs/evaluation/S1.1_pyVideoTrans.md`）

**S1.2 验收**：
- [x] VideoLingo 全流程跑通（ASR → 分割 → 三步翻译 → 字幕嵌入）
- [x] 文档化：三步翻译机制、时间轴对齐、断句逻辑（详见 `docs/evaluation/S1.2_VideoLingo.md`）

**S1.3 验收**：
- [x] `whisperjav video.mp4 --mode faster/balanced` 跑通
- [x] 文档化：管线架构、场景检测、VAD 分段、幻觉过滤（详见 `docs/evaluation/S1.3_WhisperJAV.md`）

---

### Sprint 2：参考项目评估 Part 2 — 专项工具 + 底座决策

**目标**：评估专项工具，汇总所有信息做底座选型决策

**子阶段**：4 个（S2.1-S2.3），可并行

| 子阶段 | 内容 | 耗时 | 状态 |
|--------|------|------|:----:|
| S2.1 | **JAVTrans + AnimeTranslator** 快速评估（边界检测/四层防御） | 0.5 天 | ✅ |
| **S2.1.1** | **统一环境升级**：所有项目 venv 升级到 Python 3.13 + torch 2.11.0+cu128 | 0.3 天 | ✅ |
| S2.2 | **SubForge + N46Whisper + SubFlow + LinguaGacha** 快速扫描 | 0.5 天 | ✅ |
| S2.3 | 底座选型决策：汇总 Sprint 1+2 评估结果，产出 `docs/architecture-decision.md` | 0.5 天 | ✅ |

**过渡到 Sprint 3**：知道了哪个项目可作底座 → 开始评估核心 ASR 模块。

**S2.1 验收**：
- [x] 记录 JAVTrans SpeechBoundary 和 AnimeTranslator 四层防御是否可以独立复用
- JAVTrans: 完整管道跑通（39.1s 处理 30s 片段），Qwen3-ASR 1.7B 动漫微调版输出 7 句日语字幕。
  SpeechBoundary-JA 5 模型边界检测与 Mamba2/CUDA 深度绑定，难以独立复用。
- AnimeTranslator: 25.4s 处理 30s 片段，OP/ED 检测逻辑可独立提取

**S2.2 验收**：
- [x] 每个项目至少运行一次，记录关键可复用点
- SubFlow: ✅ Python 3.13 测试通过（OpenAI Whisper + 智能切分），歌曲逐字歌词模式独特
- N46Whisper: ⏸️ Colab 笔记本，代码分析完成，核心仅为 faster-whisper + VAD
- LinguaGacha: ⏸️ Electron 文本翻译器（非 ASR），术语表功能值得参考
- SubForge: ✅ Rust 构建成功（68s），SaT 分割 + GEMBA-MQM 质量评估

**S2.3 验收**：
- [x] 明确的底座选型结论：基于某个项目二次开发 / 从零搭建
- 选定方案 A：基于 **JAVTrans** 二次开发，整合 VideoLingo（3-step 翻译）+ AnimeTranslator（OP/ED 检测 + 幻觉防御）+ LinguaGacha（Glossary）
- 详见 `docs/architecture-decision.md`
- [x] 各项目可复用模块清单

---

### Sprint 3：ASR 主力评估

**目标**：确定核心 ASR 方案（Anime Whisper + faster-whisper 推理优化）

**子阶段**：2 个（S3.1-S3.2）

| 子阶段 | 内容 |
|--------|------|
| S3.1 | **Anime Whisper** — faster-whisper 加载 + gold standard CER 测试 + 与 large-v3-turbo 对比 |
| S3.2 | **Faster-Whisper 推理优化** — int8 量化 / batch_size 调优 / VAD 集成 |

**过渡到 Sprint 4**：主力 ASR 已定 → 评估备选模型和复核模型。

**S3.1 验收**：
- [x] faster-whisper 成功加载 large-v3（CTranslate2 格式）
- [x] 记录 large-v3 CER 基线：平均 0.3848，中位数 0.2344，P90 1.0（200 条测试集）
- [x] 成功加载 Anime Whisper（quantumcookie/anime-whisper-ct2-fp16）
- [x] 记录 Anime Whisper CER：平均 0.2989，中位数 0.1111，P90 1.0
- [x] 对比结论：Anime Whisper 中位数 CER 降低 53%（0.2344 → 0.1111），RTF 快 51%
- [x] 选定 Anime Whisper 作为主力 ASR 模型
- [x] 产出评估报告 docs/evaluation/S3.1_ASR_Evaluation.md

**S3.2 验收**：
- [x] 确定最优 batch_size 和量化级别：int8_float16 + batch_size=8
- [x] 确定是否启用 VAD：**关闭 VAD**（短片段场景下 VAD 漏语音，CER 翻倍）
- [x] 记录各配置下的 RTF
- [x] 最终推荐配置：int8_float16 + batch_size=8 + VAD=OFF → CER=0.1299, RTF=0.1022（~10 倍实时）

**S3 汇总**：
- ASR 主力选定: Anime Whisper (quantumcookie/anime-whisper-ct2-fp16)
- 最优推理配置: int8_float16, batch_size=8, VAD=OFF
- 最终 RTF: ~0.10（10 倍实时）, CER: ~0.13（中位数 ~0.06）
- 报告: docs/evaluation/S3.1_ASR_Evaluation.md + S3.2_Inference_Optimization.md

---

### Sprint 4：ASR 备选评估 + 时间戳优化

**目标**：评估 SenseVoice 快速通道、Qwen3 复核模型、时间戳对齐方案

**子阶段**：3 个（S4.1-S4.3），可并行

| 子阶段 | 内容 | 可并行？|
|--------|------|---------|
| S4.1 | **SenseVoice Small + efwkjn/whisper-ja-anime-v0.3** — ASR 对比 + AED 音频事件测试 | ✅ |
| S4.2 | **Qwen3-ASR-1.7B-JA** — 日语专有名词识别 + 复核能力测试 | ✅ |
| S4.3 | **WhisperX + stable-ts** — 时间戳对齐精度对比，选择最终方案 | ✅ |

**过渡到 Sprint 5**：ASR 全方案确定 → 现在做音频分离（ASR 前置优化）。

**S4.1 验收**：
- [x] SenseVoice 的 CER 和速度数据：CER=0.3307, RTF=0.017, 速度快但精度不足
- [x] whisper-ja-anime-v0.3 的 CER 对比：CER=0.2778, Med=0.1056, RTF=0.089, 不如 Anime Whisper
- [x] SenseVoice AED 可用于 OP/ED 检测：输出含 Speech/Cry/BGM 标签，可区分语音与非语音
- [x] 结论：Anime Whisper 保持主力，SenseVoice 可做辅助 AED 分类

**S4.2 验收**：
- [x] Qwen3 vs Anime Whisper 在专有名词上的准确率差异：Qwen3 CER=0.2176 不如 AW CER=0.1299
- [x] 不推荐作为复核模型：精度不如 AW，额外资源消耗不划算

**S4.3 验收**：
- [x] 决策：不启用 WhisperX / stable-ts。faster-whisper word_timestamps 已足够，后续集成 JAVTrans Boundary

---

### Sprint 5：音频分离预处理

**目标**：评估三种人声/BGM 分离方案，确定是否以及如何集成

**子阶段**：3 个（S5.1-S5.3），可并行

| 子阶段 | 内容 | 可并行？|
|--------|------|---------|
| S5.1 | **Demucs** — 部署 + 分离测试 + 分离前后 ASR CER 对比 | ✅ |
| S5.2 | **UVR5** — 部署 + 分离测试 + 与 Demucs 对比 | ✅ |
| S5.3 | **BS-RoFormer** — 部署 + 分离测试 + 三方案综合对比 | ✅ |

**过渡到 Sprint 6**：音频预处理方案确定 → 进入说话人分离（同属音频域，使用分离后的人声）。

**S5.1-S5.3 统一验收**：
- [x] S5.1 Demucs: RTF ~29x (5s), VRAM ~4.5GB, CER 无改善甚至恶化
- [x] S5.2 UVR5: RTF ~1x, VRAM <1GB, CER 无改善甚至恶化 (sample_0004: 0.18->0.45)
- [x] S5.3 BS-RoFormer: RTF ~1x, VRAM ~2GB, CER 部分改善 (sample_0004: 0.18->0.09)
- [x] 分离前后 ASR CER 对比表（日常对话 / 普通BGM / 纯对话）
- [x] 最终结论：音频分离**不加入默认 pipeline**。BS-RoFormer 是唯一能改善 CER 的方案，但改善有限。未来需要时可启用 BS-RoFormer

---

### Sprint 6：说话人分离

**目标**：评估四种方案，确定集成程度

**子阶段**：2 个（S6.1-S6.2）

| 子阶段 | 内容 |
|--------|------|
| S6.1 | **Kotoba-Whisper v2.2 内置 diarization + pyannote.audio** 快速评估 |
| S6.2 | **DiariZen + Sortformer** 对比评估 + 模块定型 |

**过渡到 Sprint 7**：说话人分离方案确定 → 进入 OP/ED 检测（同属音频分析）。

**S6.1 验收**：
- [x] Kotoba 内置方案由于 gated 模型不可用，改为 VAD+ECAPA-TDNN 聚类方案
- [x] VAD+ECAPA-TDNN 在动漫场景可检出 4 个说话人（multi_01/multi_03）
- [x] 能量 VAD 阈值不鲁棒（multi_02 仅检出 1 人），建议替换为 Silero-VAD
- [x] 评估报告：`docs/evaluation/S6.1_Diarization_Evaluation.md`

**S6.2 验收**：
- [x] 四方案 DER 对比表（VAD+ECAPA / DiariZen / Sortformer / pyannote）
- [x] 最终方案决策：选择 VAD + ECAPA-TDNN + 聚类（改进 VAD 为 Silero-VAD）
- [x] 接口定义：输入 WAV → 输出 speaker 时间戳列表
- [x] 评估报告：`docs/evaluation/S6.2_Diarization_Final.md`
- [x] DiariZen 因 pyannote API 版本不兼容不可用
- [x] NeMo Sortformer 因 Windows 构建工具链缺失不可用

---

### Sprint 7：OP/ED 检测

**目标**：确定 OP/ED 检测方案，集成到 pipeline

**子阶段**：2 个（S7.1-S7.2）

| 子阶段 | 内容 |
|--------|------|
| S7.1 | **SenseVoice AED + PANNs + YAMNet** 音频事件分类对比 |
| S7.2 | **AniChapters + needle** OP/ED 专用工具评估 + 模块定型 |

**过渡到 Sprint 8**：音频域全部完成（ASR → 分离 → 说话人 → OP/ED）→ 进入文本域（翻译）。

**S7.1 验收**：
- [x] SenseVoice AED 因 funasr→editdistance 编译依赖不可安装
- [x] PANNs CNN14 评估：33% 准确率，无法识别动漫 J-pop 音乐
- [x] 能量特征法评估：67% 准确率（最佳基线），但对话带 BGM 时误报
- [x] YAMNet 因 torchaudio 2.11.0 不再内置
- [x] 评估报告：`docs/evaluation/S7.1_OPED_Detection.md`
- [x] 结论：现有音频事件分类方案效果有限，S7.2 评估专有工具

**S7.2 验收**：
- [x] AniChapters 在 K-On! EP01/EP02 上实测通过
- [x] EP01: OP=01:55.140, ED=23:30.750  |  EP02: OP=00:52.150, ED=23:30.790
- [x] 跨集 ED 位置差仅 0.04s，时长完全一致
- [x] 首次需网络下载主题曲，后续缓存离线可用
- [x] 最终方案决策：AniChapters（音频指纹 + animethemes.moe）
- [x] 接口定义：输入 video_path + series_name → 输出 OP/ED 章节列表
- [x] 评估报告：`docs/evaluation/S7.2_OPED_Final.md`

---

### Sprint 8：翻译模型评估与对比

**目标**：确定最终翻译方案（主力 + 备用 + 风格备选）

**子阶段**：2 个（S8.1-S8.2）

| 子阶段 | 内容 |
|--------|------|
| S8.1 | **Sakura-7B vs Sakura-14B** — 显存/速度/翻译质量/角色名一致性对比 |
| S8.2 | **GalTransl-7B + Qwen2.5:7b 对比** — 风格差异 + 备用通道评估 |

**过渡到 Sprint 9**：选定了翻译模型 → 开始实现上下文窗口和术语表。

**S8.1 验收**：
- [x] Sakura-7B vs GalTransl-7B vs Qwen2.5:7b 翻译质量/速度/VRAM 对比
- [x] Sakura-7B 最优（0.35s/句，翻译质量高），但 VRAM 占用 9.5GB
- [x] GalTransl-7B 风格备选（萌系翻译风格）
- [x] Qwen2.5:7b 不适合 ACGN 翻译（解释性输出、误译多）
- [x] Sakura-14B 需服务器环境（本机网络不可达）
- [x] 确定本机方案：Sakura-7B 主力 + GalTransl-7B 备选
- [x] 评估报告：`docs/evaluation/S8.1_Sakura_Evaluation.md`

**S8.2 验收**：
- [x] GalTransl-7B vs Qwen2.5:7b/14b 风格差异对比
- [x] GalTransl-7B 风格偏萌系（"呼喵呼喵"），适合作为风格备选
- [x] Qwen2.5:7b/14b 均不适合 ACGN 翻译（解释性输出、误译）
- [x] 最终备用通道方案：GalTransl-7B 可选切换
- [x] 评估报告：`docs/evaluation/S8.2_Style_Comparison.md`
- [ ] Qwen2.5 vs Sakura 质量差距数据
- [ ] 是否保留为备用通道的结论

---

### Sprint 9：翻译工程实现

**目标**：实现上下文窗口翻译、术语表系统、翻译记忆库

**子阶段**：3 个（S9.1-S9.3），S9.2 依赖 S9.1

| 子阶段 | 内容 |
|--------|------|
| S9.1 | **上下文窗口翻译** — Python 拼接前后 3-5 句 + Ollama 调用（本地模式）；支持模型自行读上下文（服务器模式） |
| S9.2 | **术语表系统** — GPT 字典格式 + prompt 注入 + CLI 参数加载 |
| S9.3 | **翻译记忆库** — JSONL 双层缓存（精确匹配 + 跨会话持久化）+ LinguaGacha 评估 |

**过渡到 Sprint 10**：翻译模块完备 → 进入字幕生成。

**S9.1 验收**：
- [x] 实现 translate.py 上下文窗口翻译模块（本地拼接+Ollama调用）
- [x] 带上下文 vs 不带上下文的质量对比数据（10句连续对话测试）
- [x] 上下文窗口有效提升角色名一致性和对话流畅度
- [x] 本地模式和服务器模式都支持（OLLAMA_HOST 环境变量切换）
- [x] 评估报告：`docs/evaluation/S9.1_Context_Window.md`

**S9.2 验收**：
- [x] 术语表 JSON 格式 + JAVTrans 文本格式双支持
- [x] 术语表通过 prompt 注入角色名和专有名词
- [x] 空术语表不影响翻译
- [x] CLI 参数（--glossary）和环境变量（GLOSSARY_FILE）加载
- [x] K-On! 术语表示例（28 个术语）
- [x] 评估报告：`docs/evaluation/S9.2_Glossary.md`

**S9.3 验收**：
- [x] 翻译记忆库 JSONL 格式 + 精确匹配缓存
- [x] 相同句子第二次翻译直接返回缓存
- [x] 翻译记忆跨会话可用（JSONL 文件持久化）
- [x] 集成到 translate.py（先查 TM 再调用模型）
- [x] 评估报告：`docs/evaluation/S9.3_Translation_Memory.md`

---

### Sprint 10：字幕生成

**目标**：生成高质量的字幕文件，含基础样式和双语模式

**子阶段**：3 个（S10.1-S10.3），可部分并行

| 子阶段 | 内容 | 可并行？|
|--------|------|---------|
| S10.1 | **pysubs2 基础 SRT/ASS 生成 + 时间轴规则优化**（重叠修复/最短最长时长/CPS/换行） | ✅ 内部并行 |
| S10.2 | **ffsubsync + SubtitleEdit + subcap 评估** — 对齐精度和字幕算法对比 | ✅ |
| S10.3 | **双语字幕 + ASS 样式模板 + Aegisub 校对出口** | — |

**过渡到 Sprint 11**：字幕生成可用 → 进入质量审查。

**S10.1 验收**：
- [x] SRT/ASS 文件播放器可正常加载
- [x] 时间轴优化后的字幕无重叠（重叠 3→0）、CPS 合理（平均 4.8）
- [x] 2 套 ASS 样式模板（anime / anime_bilingual）
- [x] 评估报告：`docs/evaluation/S10.1_Subtitle_Generation.md`

**S10.2 验收**：
- [x] ffsubsync 评估：无参考字幕时无法对齐（测试中偏移 5s 检测为 57s）
- [x] subcap 评估：功能已被 pysubs2 覆盖，不采用
- [x] SubtitleEdit 评估：适合人工校对但不集成到 pipeline
- [x] 评估报告：`docs/evaluation/S10.2_Alignment_Tools.md`

**S10.3 验收**：
- [x] 双语字幕可正常渲染（JA+ZH 同屏，top_ja/top_zh 布局切换）
- [x] 4 套样式模板（anime / anime_bilingual / classic / karaoke）
- [x] Aegisub 兼容导出（ASS v4.00+）
- [x] 评估报告：`docs/evaluation/S10.3_Bilingual_Styles.md`

---

### Sprint 11：质量审查

**目标**：实现从规则检查到多 Agent 审查的完整质量保障体系

**子阶段**：3 个（S11.1-S11.3），需顺序推进

| 子阶段 | 内容 |
|--------|------|
| S11.1 | **规则检查器**（时长/CPS/空翻译/行数/术语不一致）+ **可疑行检测**（ASR 置信度/BGM 干扰段标记） |
| S11.2 | **多 Agent 脚本审查** — 5 角色并行调用 Ollama / OpenAI-compatible API + 总编安全门禁 + 可审计自动修正 |
| S11.3 | **GEMBA-MQM 翻译质量评估** — MQM 框架 prompt + refine 机制 |

**过渡到 Sprint 12**：质量体系搭好 → 开始做工程效率优化。

**S11.1 验收**：
- [x] 规则检查器输出 JSON 问题列表（时长/CPS/空翻译/行数/术语/可疑模式）
- [x] 可疑行检测输出 suspicious.json + review.html
- [x] 评估报告：`docs/evaluation/S11.1_Quality_Check.md`

**S11.2 验收**：
- [x] 5 个角色并行调用成功，支持按角色配置模型与 SenseNova 多账号轮询
- [x] 总编能合并冲突，严格 JSON 解析，不从提示词回显猜测结论
- [x] 修正方案接入主流程；仅在全员成功、票数和置信度达标时自动应用
- [x] JSONL 断点续传、完整审计、`--dry-run` 与 Web UI 开关
- [x] 评估报告：`docs/evaluation/S11.2_Multi_Agent_Review.md`

**S11.3 验收**：
- [x] 翻译质量评分输出（四维 MQM 评分 + 总分）
- [x] 低分段落可重新翻译（阈值可配置，自动重译+重评）
- [x] 评估报告：`docs/evaluation/S11.3_GEMBA_MQM.md`

---

### Sprint 12：断点续传 + 批量处理

**目标**：解决工程可用性的核心痛点

**子阶段**：2 个（S12.1-S12.2）

| 子阶段 | 内容 |
|--------|------|
| S12.1 | **断点续传** — JSONL 原子写入 + 阶段标记 + 重启恢复 |
| S12.2 | **批量处理** — 目录遍历 + 模型复用（ASR/翻译只加载一次） |

**过渡到 Sprint 13**：核心工程能力完备 → 增加配套工具。

**S12.1 验收**：
- [x] 中断重启自动跳过已完成阶段（5 项测试全部通过）
- [x] 原子写入防止文件损坏（tmp + rename 策略）
- [x] 评估报告：`docs/evaluation/S12.1_Checkpoint.md`

**S12.2 验收**：
- [x] 处理 12 集不需要手动干预（4 视频批量测试通过 + 断点续传 + 模型复用）
- [x] 评估报告：`docs/evaluation/S12.2_Batch_Process.md`

---

### Sprint 13：专有名词发现 + 评测工具 + 外挂字幕

**目标**：自动化辅助工具，降低用户手动操作成本

**子阶段**：3 个（S13.1-S13.3），可并行

| 子阶段 | 内容 | 可并行？|
|--------|------|---------|
| S13.1 | **专有名词自动发现** — 从 ASR 文本提取高频词 + LLM 标注 → 生成候选术语表 | ✅ |
| S13.2 | **A/B 模型评测小工具** — 基于公开字幕+视频，自动对比 ASR/翻译模型的 CER/术语命中率 | ✅ |
| S13.3 | **外挂字幕优先模式** — 日文 sidecar/内嵌文本轨验证后替代 ASR，支持整季匹配与源变更失效 | ✅ |

**S13.1 验收**：
- [x] 专有名词自动发现工具可用（高频词提取 + LLM 标注 + 术语表生成）
- [x] 评估报告：`docs/evaluation/S13.1_Term_Discovery.md`

**S13.2 验收**：
- [x] A/B 模型评测工具可用（CER + 术语命中率对比）
- [x] 评估报告：`docs/evaluation/S13.2_AB_Eval.md`

**S13.3 验收**：
- [x] 日文 sidecar、整季目录和内嵌文本轨均可进入主流水线并跳过 ASR
- [x] 中文源拒绝、唯一集数匹配、SHA-256 审计和下游 checkpoint 失效
- [x] CLI、批处理和 Web UI 均可用；无日文源时可安全回退 ASR
- [x] 评估报告：`docs/evaluation/S13.3_External_Subs.md`

**过渡到 Sprint 14**：工具链完善 → 增加更高级的功能。

---

### Sprint 14：翻译 Adapter + 整季一致性

**目标**：实现多翻译后端切换和跨集一致性

**子阶段**：2 个（S14.1-S14.2）

| 子阶段 | 内容 |
|--------|------|
| S14.1 | **翻译 Adapter 架构** — TranslatorAdapter 抽象基类 + Sakura/Qwen/GalTransl/ExternalAPI 实现 + 配置文件切换 |
| S14.2 | **整季级一致性记忆** — `series_memory.json`（角色名/关系/口癖/称呼方式）+ 跨集复用 |

**S14.1 验收**：
- [x] TranslatorAdapter 抽象基类 + 4 后端实现（Sakura/Qwen/GalTransl/External）
- [x] 配置文件切换后端
- [x] Sakura-14B 和 GalTransl-7B 翻译测试通过
- [x] 评估报告：`docs/evaluation/S14.1_Translator_Adapter.md`

**S14.2 验收**：
- [x] series_memory.json 格式定义 + 角色名/关系/口癖/称呼方式
- [x] 跨集复用（保存/加载/注入到翻译 prompt）
- [x] K-On! 示例记忆（6 角色 + 10 术语）
- [x] 评估报告：`docs/evaluation/S14.2_Series_Memory.md`

**过渡到 Sprint 15**：所有模块完备 → 全流程 CLI 集成。

---

### Sprint 15：全流程 CLI 集成

**目标**：所有模块串联为一条 CLI 命令

**子阶段**：3 个（S15.1-S15.3）

| 子阶段 | 内容 |
|--------|------|
| S15.1 | **CLI 接口实现** — 所有参数串联，`anime-sub video.mp4` 跑通全流程 |
| S15.2 | **智能默认值** — 自动检测硬件，推荐最优参数 |
| S15.3 | **端到端回归测试** — 全流程/断点续传/批量/各可选功能开关测试 |

**S15.1 验收**：
- [x] `anime-sub video.mp4` 一条命令跑完全流程（5 阶段串联）
- [x] 所有可选参数生效（--backend/--memory/--quality-check/--batch）
- [x] 评估报告：`docs/evaluation/S15.1_CLI_Integration.md`

**S15.2 验收**：
- [x] 硬件自动检测（GPU/VRAM/CPU/RAM）
- [x] 智能参数推荐（翻译模型/ASR batch/并行数/质量审查）
- [x] 集成到 CLI（--auto 参数）
- [x] 评估报告：`docs/evaluation/S15.2_Smart_Defaults.md`

**S15.3 验收**：
- [x] 回归测试通过清单（已扩展到 S16，22/22 模块全部通过）
- [x] 评估报告：`docs/evaluation/S15.3_Regression_Test.md`

---

### Sprint 16：高级功能

**目标**：锦上添花的功能，优先级最低

**子阶段**：5 个（S16.1-S16.5），可并行，按需选择

| 子阶段 | 内容 | 可并行？ | 状态 |
|--------|------|---------|------|
| S16.1 | **说话人角色颜色前缀** — ASS 颜色标签 + 角色名映射 | ✅ | ✅ 完成（PR #128） |
| S16.2 | **Web UI 界面** — FastAPI | ✅ | ✅ 完成（PR #130） |
| S16.3 | **人工校对模式** — 交互式翻译修正 | ✅ | ✅ 完成（PR #132） |
| S16.4 | **插件系统架构** — 翻译后端/ASR 后端/字幕样式插件接口 | ✅ | ✅ 完成（PR #134） |
| S16.5 | **视频预览** — 快速生成准确的字幕效果预览 | ✅ | ✅ 完成（PR #136） |

**Sprint 16 验收**：
- [x] 五个子阶段均经独立分支、PR、中文 Issue 验收并合入主分支
- [x] 完整自动化测试 72/72，通过跨阶段回归 22/22
- [x] 使用《轻音少女》第 9 集真实输出校验人工修订、字幕重建、硬字幕成片和 Web 视频预览
- [x] 完成报告：`docs/evaluation/S16_Completion_Report.md`

---

## 四、项目评估的收益预估

以下表格说明了为什么值得花时间评估每个项目（即使最终不采用）。

| 项目 | 评估耗时 | 如果不采用，学到什么 | 如果采用，省多少工作 |
|------|---------|-------------------|------------------|
| pyVideoTrans | 1 天 | 成熟的 FFmpeg 封装 + GUI 架构参考 | 省 80% 基础工程 |
| VideoLingo | 1 天 | 三步翻译机制、断句逻辑 | 省翻译质量优化工作 |
| WhisperJAV | 半天 | VAD 策略、pipeline 模式设计 | 省 pipeline 架构设计 |
| JAVTrans | 半天 | SpeechBoundary、强制对齐 | 省边界检测工作 |
| Demucs | 半天 | 人声分离的实际效果数据 | 直接集成 |
| UVR5 | 半天 | 更优的分离效果（待验证） | 直接集成 |
| WhisperX | 半天 | 时间戳对齐的实际精度 | 省时间戳调优工作 |
| ffsubsync | 半天 | 对齐效果的 baseline | 直接集成 |
| SubtitleEdit | 半天 | 成熟的后处理算法 | 省字幕后处理自研工作 |

---

## 五、并行策略

以下阶段可以并行进行：

| 并行组 | 阶段 | 说明 |
|--------|------|------|
| 组 A | S1.1-S1.3 + S2.1-S2.2 | 所有参考项目评估可以一起跑 |
| 组 B | S4.1-S4.3 | ASR 备选模型和时间戳方案可并行 |
| 组 C | S5.1-S5.3 | 三种音频分离方案可并行 |
| 组 D | S6.1-S6.2 | 说话人分离方案可并行 |
| 组 E | S7.1-S7.2 | OP/ED 检测方案可并行 |
| 组 F | S8.1-S8.2 | 翻译模型对比可并行 |
| 组 G | S13.1-S13.3 | 专有名词/A-B评测/外挂字幕可并行 |
| 组 H | S16.1-S16.5 | 高级功能全部可并行 |

**注意**：并行组内部互不依赖，但组间有先后关系（如组 C 音频分离需要等组 B ASR 确定后才能做分离后 ASR 测试）。

---

## 六、风险与依赖

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 显存不足（<12GB） | 无法运行 Sakura-14B | 先测试 Sakura-7B 质量是否可接受 |
| Anime Whisper 效果不如预期 | 主力 ASR 需要更换 | 预留 SenseVoice/Qwen3 备用 |
| 说话人分离效果太差 | 无法用于动漫 | 降低预期，仅输出 speaker_01/02 |
| 多 Agent 审查质量差 | 浪费算力且引入新错误 | 先做好规则检查器兜底 |
| 本地模型翻译质量不够 | 用户不满意 | 保留 API 翻译通道作为升级路径 |
