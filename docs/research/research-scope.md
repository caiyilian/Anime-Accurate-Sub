# 调研范围和计划

## 调研目标

为 Anime Accurate Sub 项目寻找最合适的开源方案，**尽可能复用现有项目，避免重复造轮子**。

每个领域寻找多个候选方案，分析各自优缺点，最终整合出一套取长补短的推荐技术栈。

## 调研领域

### 1. ASR（语音识别）
- **目标**: 日语动漫语音 → 日语文本 + 时间戳
- **候选**: Whisper / Faster-Whisper / SenseVoice / Kotoba-Whisper / 其他日语优化模型
- **关注点**: 日语识别准确率、动漫场景表现、推理速度、GPU 支持、说话人区分能力

### 2. 说话人分离（Speaker Diarization）
- **目标**: 区分不同角色的语音片段
- **候选**: pyannote.audio / SpeechBrain / 其他声纹嵌入方案
- **关注点**: 与 ASR 的集成方式、准确率、实时性、是否支持流式

### 3. 翻译（日语→中文）
- **目标**: 日语文本 → 准确的中文翻译
- **候选**: Ollama 本地 LLM（Qwen2.5 / Llama3 / Gemma / 其他）、专用翻译模型（M2M-100 / MADLAD-400 / NLLB）、云端 API 备用（OpenAI / Claude / DeepSeek）
- **关注点**: 动漫语境下的翻译质量、角色名一致性、专有名词处理、本地运行可行性

### 4. 字幕生成与嵌入
- **目标**: 将翻译文本 + 时间戳 → 字幕文件 → 嵌入视频
- **候选**: FFmpeg / aeneas (forced alignment) / ass 库 / pysubs2
- **关注点**: 格式支持（SRT/ASS）、样式自定义、双语字幕支持、批量处理能力

### 5. 端到端 Pipeline 项目
- **目标**: 已有完整工作流的开源项目，可直接使用或借鉴
- **候选**: whisper-subtitles / pyTranscriber / VideoSubtitleMaster / Auto-Translate-Subtitles / 其他
- **关注点**: 是否可直接用于动漫、可定制程度、本地运行能力

## 调研方法

1. 官方 GitHub 仓库（Star 数、活跃度、Issue 讨论）
2. 官方文档和论文
3. 实际开源实现中的使用案例
4. 社区评估（动漫领域用户反馈）
5. 各方案间兼容性与集成难度

## 产出

- 每个候选方案的优缺点分析
- 推荐的技术栈组合
- 各模块间的集成方案
- 可选的前/后端分离架构建议