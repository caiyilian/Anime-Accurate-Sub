# 新增功能调研范围（第二阶段）

> 在第一轮调研（ASR、翻译、说话人分离、字幕工具）基础上，针对新增功能进行专项调研。

## 调研目标

为 Anime Accurate Sub 项目的进阶功能寻找可参考的开源实现、库和最佳实践，避免重复造轮子。

## 调研领域

### 1. 术语表系统（Glossary）

- **目标**: 用户自定义角色名、招式名、地名等专有名词的翻译映射，确保翻译一致性
- **候选**: SakuraLLM GPT 字典、WhisperJAV glossary、GalTransl 字典、Subtitle Edit 术语表
- **关注点**: 字典格式（JSON/CSV）、prompt 注入方式、运行时动态更新、多语言支持

### 2. 翻译记忆库（Translation Memory）

- **目标**: 缓存已翻译的句子，相同/相似台词自动复用，避免重复翻译和不一致
- **候选**: JAVTrans translation_cache / translation_memory、SubForge MAPS、通用 TM 工具
- **关注点**: 精确匹配 vs 模糊匹配、Cache 持久化、跨会话复用、过期策略

### 3. OP/ED 自动检测与跳过

- **目标**: 自动识别片头片尾，避免 ASR 在歌词上浪费资源
- **候选**: AnimeTranslator 的 OP/ED 检测、音频事件分类（SenseVoice）、ffmpeg 场景检测、Silero VAD
- **关注点**: 检测准确率、对非标准 OP/ED 时长的适应性、处理速度

### 4. 多 Agent 脚本审查

- **目标**: 多个 AI Agent 协作审查字幕文本的逻辑通顺性、一致性、翻译质量
- **候选**: 多 Agent 协作框架（AutoGen / CrewAI / LangGraph）、字幕 QA 工具、翻译质检工具
- **关注点**: Agent 间通信机制、冲突裁决策略、审查维度覆盖、性能开销

### 5. 断点续传（Checkpoint/Resume）

- **目标**: 长视频处理中断后从中断处继续，而非重新开始
- **候选**: Python 通用 checkpoint 方案、JAVTrans 的缓存机制、通用工作流引擎
- **关注点**: 序列化粒度、各阶段 checkpoint 独立、失败恢复策略

### 6. 字幕时间轴优化

- **目标**: 自动检测重叠字幕、过短/过长的显示时间，调整到舒适阅读范围
- **候选**: WhisperX 词级对齐、subcap 分段逻辑、aeneas 强制对齐、pysubs2 时间轴操作
- **关注点**: 重叠检测算法、最小/最大显示时长标准、阅读速度计算

### 7. 翻译质量评估（TQE）

- **目标**: 自动评估翻译质量，标记低置信度段落供审查
- **候选**: GEMBA-MQM（SubForge 已集成）、COMETKiwi、MetricX-24、字幕专用评估指标
- **关注点**: 是否需要参考翻译、评估速度、与开源 LLM 的兼容性、字幕场景适配

## 调研方法

1. 已有项目中的实现分析（WhisperJAV / JAVTrans / AnimeTranslator / SubForge）
2. 通用库和框架调研
3. 学术论文和行业最佳实践
4. 各方案间的集成难度评估