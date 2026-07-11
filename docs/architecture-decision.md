# 底座选型决策

> 日期: 2026-07-11
> 基于 Sprint 1 + Sprint 2 全部评估结果

---

## 1. 评估项目总览

### Sprint 1：通用底座

| 项目 | 类型 | ASR 引擎 | 评估结果 |
|------|------|----------|:--------:|
| **pyVideoTrans** | 全功能视频翻译工具 | faster-whisper / Whisper / Qwen-ASR | ✅ 完整运行 |
| **VideoLingo** | 全流程字幕管线 | WhisperX + 3-step 翻译 | ✅ 完整运行 |
| **WhisperJAV** | 动漫特化字幕管线 | faster-whisper（7 种 pipeline） | ✅ 完整运行 |

### Sprint 2：专项工具

| 项目 | 关键特性 | 评估结果 |
|------|---------|:--------:|
| **AnimeTranslator** | OP/ED 检测 + 四层幻觉防御 + SenseVoice 事件分类 | ✅ 测试通过 |
| **JAVTrans** | SpeechBoundary-JA + Pre-ASR CueQC + Qwen3-ASR 动漫微调 | ✅ 管道跑通 |
| **SubFlow** | 动漫字幕 + 歌曲逐字歌词 | ✅ 测试通过 |
| **N46Whisper** | faster-whisper Colab 应用 | ⏸️ 已停止维护 |
| **LinguaGacha** | AI 文本翻译 + Glossary 术语表 | ⏸️ 非 ASR 工具 |
| **SubForge** | Rust CLI + SaT 分割 + GEMBA-MQM | ✅ 构建成功 |

---

## 2. 核心维度对比

### ASR 质量

| 项目 | ASR 引擎 | 30s 片段耗时 | 输出质量 |
|------|---------|:-----------:|:--------:|
| pyVideoTrans | faster-whisper large-v3 | ~10s | 标准 Whisper 质量 |
| VideoLingo | WhisperX large-v3 | ~8s (WhisperX) | 词级时间戳对齐 |
| WhisperJAV | faster-whisper (7 modes) | 3.4s (faster) / 25.5s (balanced) | 多模式可调 |
| AnimeTranslator | Stable-Whisper large-v3 | 25.4s | 基本准确 |
| **JAVTrans** | **Qwen3-ASR 1.7B 动漫微调** | **1.27s (ASR 转写)** | **动漫场景最优** |
| SubFlow | OpenAI Whisper tiny | 8.9s (tiny) | 基础可用 |

**结论**: JAVTrans 的 Qwen3-ASR 1.7B 动漫微调版在 ASR 质量上最优（专为动漫/Galgame 微调），ASR 转写速度也最快（1.27s/8chunks）。

### 边界检测 / 语音分割

| 项目 | 方法 | 质量 |
|------|------|:----:|
| pyVideoTrans | VAD + 静音检测 | 基础 |
| VideoLingo | WhisperX 对齐 + 标点断句 | 中等 |
| WhisperJAV | Silero VAD / Auditok / 场景检测 | 可选多种 |
| AnimeTranslator | fsmn-vad（SenseVoice 内置） | 基础 |
| **JAVTrans** | **SpeechBoundary-JA 5 模型链** | **最优** |
| SubFlow | Whisper 自带 + 后处理合并 | 基础 |

**结论**: JAVTrans 的 SpeechBoundary-JA（SpeechIslandScorer → Outer Edge Refiner → Semantic Split → Cut Edge Refiner → Pre-ASR CueQC）是唯一使用 5 个专用模型的边界检测系统。但依赖 Mamba2 CUDA 编译，Windows 上需用 stub 绕过。

### 幻觉防御

| 项目 | 方法 | 效果 |
|------|------|:----:|
| pyVideoTrans | 无 | ❌ |
| VideoLingo | 无 | ❌ |
| WhisperJAV | 内置 hallucination filter | 基础 |
| **AnimeTranslator** | **4 层防御** | **最佳** |
| **JAVTrans** | **Pre-ASR CueQC (模型级)** | **最佳** |
| SubFlow | 无 | ❌ |

**结论**: AnimeTranslator 的四层防御（SenseVoice 标签 → OP/ED 过滤 → Whisper 质量检查 → 正则过滤）和 JAVTrans 的 Pre-ASR CueQC（基于 PTM 表征 + Mamba 时序建模的模型级过滤）各有优势。

### 翻译

| 项目 | 翻译方法 | 质量 |
|------|---------|:----:|
| pyVideoTrans | 多种 API（DeepSeek/ChatGPT/Google 等） | 可配置 |
| **VideoLingo** | **3-step 翻译（直译 → 反思 → 改编）** | **最优** |
| WhisperJAV | 内置 LLM 翻译 | 中等 |
| AnimeTranslator | DeepSeek API（5 条纠错法则） | 较好 |
| JAVTrans | 通用 LLM API（可配置） | 可配置 |
| LinguaGacha | 多种 LLM API + Glossary 术语表 | 较好 |

**结论**: VideoLingo 的 3-step 翻译（Translate → Reflect → Adaptation）在翻译质量上最优，且 Netflix 单行字幕输出是其独特优势。

### 环境兼容性

| 项目 | Python | CUDA | Windows 兼容性 |
|------|:------:|:----:|:--------------:|
| pyVideoTrans | 3.10-3.11 | 12.4+ | ⚠️ 锁定 3.11 |
| VideoLingo | 3.10+ | 12.6+ | ⚠️ 需 CUDA Toolkit |
| WhisperJAV | 3.10+ | 12.4+ | ✅ 良好 |
| AnimeTranslator | 3.10+ | 12.4+ | ✅ 良好 |
| **JAVTrans** | **3.13+** | **12.8+** | ⚠️ 需 FFmpeg Shared |
| SubFlow | 3.10+ | 12.4+ | ✅ 良好 |
| SubForge | Rust | 12.8+ | ⚠️ 需 Rust 工具链 |

---

## 3. 底座选型方案

### 方案 A：基于 JAVTrans 二次开发（推荐）

**理由**:
1. Qwen3-ASR 1.7B 动漫微调版是目前评估中 ASR 质量最优的（专门针对动漫/Galgame 数据微调）
2. SpeechBoundary-JA 边界检测系统是唯一使用 5 个专用模型的方案，语义切分精度远超传统 VAD
3. Pre-ASR CueQC 能在 ASR 前过滤掉 95% 以上的非语音片段，节省计算资源
4. 管道已完整跑通（39.1s 处理 30s 片段），CUDA 显存仅 4.39GB（RTX 3060 12GB 绰绰有余）

**需要整合的模块**:
1. **VideoLingo 的 3-step 翻译** → 替换 JAVTrans 的简单 LLM 翻译
2. **AnimeTranslator 的 OP/ED 检测** → 在 Pre-ASR CueQC 前增加 OP/ED 过滤层
3. **AnimeTranslator 的四层幻觉防御** → 与 Pre-ASR CueQC 互补
4. **SubForge 的 SaT 分割** → 辅助 Semantic Split 模型的语义切分决策
5. **LinguaGacha 的 Glossary 术语表** → 翻译一致性保障

### 方案 B：基于 pyVideoTrans 二次开发

**理由**:
1. 功能最全面：GUI/CLI/Web 三种界面，支持最多 ASR/翻译/TTS 后端
2. 社区活跃，生态成熟
3. 已测试 14 集 K-On! 全流程

**缺点**:
1. Python 版本锁定在 3.10-3.11，无法使用最新的 torch 特性
2. ASR 引擎为通用 Whisper，没有动漫场景优化
3. 边界检测仅靠 VAD，没有语义切分
4. 代码体量大（~200+ 依赖），理解和修改成本高

### 方案 C：从零搭建

**不值得**——现有项目已经提供了足够的功能模块，组合使用即可。

---

## 4. 最终决策

### 选定方案 A：基于 JAVTrans 二次开发，整合其他项目模块

**架构图**:

```
视频输入
  → OP/ED 检测 [AnimeTranslator]
  → 音频提取
  → SpeechBoundary-JA 边界检测 [JAVTrans]
    → SpeechIslandScorer v8
    → Outer Edge Refiner v1
    → Semantic Split Verifier v1 (+ SaT 辅助 [SubForge])
    → Cut Edge Refiner v1
    → Pre-ASR CueQC v11 [JAVTrans] + 四层幻觉防御 [AnimeTranslator]
  → Qwen3-ASR 1.7B 动漫微调 [JAVTrans]
  → 字幕时间轴生成 [JAVTrans]
  → 3-step 翻译 (+ Glossary 术语表) [VideoLingo + LinguaGacha]
  → SRT/ASS 输出
```

### 关键技术栈

| 模块 | 方案 | 来源 |
|------|------|------|
| ASR | Qwen3-ASR 1.7B-JA-Anime-Galgame | JAVTrans |
| 边界检测 | SpeechBoundary-JA (5 模型链) | JAVTrans |
| 幻觉防御 | Pre-ASR CueQC + 四层规则 | JAVTrans + AnimeTranslator |
| OP/ED 检测 | 85-95s 连续音乐检测 | AnimeTranslator |
| 翻译 | 3-step Translate-Reflect-Adaptation | VideoLingo |
| 术语表 | Glossary 自动生成 | LinguaGacha |
| 环境 | Python 3.13 + torch 2.11.0+cu128 | 统一升级 |

### 后续 Sprint 规划

**Sprint 3**: ASR 主力评估（Qwen3-ASR vs faster-whisper 对比测试）
**Sprint 4**: 边界检测优化（SpeechBoundary-JA 与 VAD 对比）
**Sprint 5**: 翻译评估（3-step 翻译 + Glossary 术语表）
**Sprint 6**: 幻觉防御集成（Pre-ASR CueQC + 四层规则）
**Sprint 7**: 整合与验收