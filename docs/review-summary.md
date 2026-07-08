# 三个 LLM 回复的功能建议汇总

> 对比分析豆包、Gemini、ChatGPT 三个大模型对 Anime Accurate Sub 项目的评审建议
> 重点提取：**新增功能建议**（我们调研中没提到的）

---

## 一、三份回复的共同共识

### 一致同意我们的现有决策

| 决策 | 三模型共识 |
|------|-----------|
| Anime Whisper 作为主力 ASR | ✅ 完全合理，动漫领域最优 |
| SakuraLLM 作为翻译主力 | ✅ ACGN 翻译最优解，个人使用许可证无问题 |
| 不引入 CrewAI/LangGraph 框架 | ✅ 明智，5 个独立 prompt 用 ThreadPoolExecutor 足够 |
| 模块化 JSONL 持久化 | ✅ 轻量可靠，适合线性流水线 |
| 使用 Ollama 本地运行 | ✅ 符合定位 |

### 一致建议调整的优先级

| 功能 | 原定阶段 | 建议调整到 |
|------|---------|-----------|
| 断点续传 (Checkpoint/Resume) | 阶段 2 | **阶段 0（MVP 必备）** — 三个模型都提到了 |
| 术语表系统 (Glossary) | 阶段 1 | **阶段 0 末期 / MVP** — 性价比最高的质量提升 |
| 时间轴优化 | 阶段 2 | **阶段 0 / MVP** — 字幕体验核心 |
| 多 Agent 全量审查 | 阶段 1 | **阶段 2 / 推迟** — 三个模型都认为太早了 |
| 说话人分离 + 角色颜色 | 阶段 1 | **推迟** — 动漫场景效果差，争议大 |
| 翻译质量评估 (TQE) | 阶段 3 | **阶段 3 末期** — 最不紧急 |

---

## 二、我们遗漏的新功能建议

### 2.1 人声/BGM 分离预处理（三个模型都提到了）

| 来源 | 建议 |
|------|------|
| **豆包** | 推荐集成 **Demucs**（Meta）做前置人声分离，ASR 错误率可降 15%-30% |
| **Gemini** | 推荐 **UVR5 (BS-RoFormer)** 或 Demucs 提取纯净人声再 ASR |
| **ChatGPT** | 推荐 Demucs，但指出会增加耗时和伪影，做成可选项 |

**项目链接**：
- Demucs: https://github.com/facebookresearch/demucs
- UVR5: https://github.com/Anjok07/ultimatevocalremovergui
- BS-RoFormer: https://github.com/lucidrains/BS-RoFormer

**结论**：三个模型一致推荐，作为 ASR 前置预处理，对带 BGM 的动漫场景提升显著。

---

### 2.2 硬字幕提取 + OCR 翻译（豆包、ChatGPT 提到）

| 来源 | 建议 |
|------|------|
| **豆包** | 很多老番内嵌日文字幕，用 **video-subtitle-extractor** OCR 提取再翻译，准确率远高于 ASR |
| **ChatGPT** | 如果 MKV 自带日文字幕轨道，优先提取已有字幕，而不是 ASR |

**项目链接**：
- video-subtitle-extractor: https://github.com/YaoFANGUK/video-subtitle-extractor
- SubFlow（提取 MKV 字幕 → 翻译 → remux）: 可搜索 GitHub

**结论**：对"已有字幕"的番剧，这条路比 ASR 更准更快。

---

### 2.3 可疑字幕行检测 / 人工校对降级（ChatGPT 重点提）

| 来源 | 建议 |
|------|------|
| **ChatGPT** | 不要让用户从头校对 500 行，而是标记 **30-50 行可疑行**，优先检查这些。这是最接近"杀手级"的功能 |
| 判断依据 | ASR 低置信度、BGM 干扰段、术语不一致、翻译 JSON 修复过、CPS 过高 |

**结论**：这是三个模型中唯一的"用户体验杀手级"建议，值得认真考虑。

---

### 2.4 上下文窗口翻译（三个模型都提到了）

| 来源 | 建议 |
|------|------|
| **豆包** | 不要逐句翻译，至少给模型前后 2-3 句上下文 |
| **Gemini** | 翻译第 N 句时必须带 N-3 到 N-1 句作为 context |
| **ChatGPT** | 日语省略主语，一行一翻必然导致人称混乱；必须 chunk 翻译 |

**结论**：三个模型都指出"逐句翻译是灾难"，必须做上下文窗口。

---

### 2.5 专有名词自动发现（豆包、ChatGPT 提到）

| 来源 | 建议 |
|------|------|
| **豆包** | 自动从全片台词中聚类高频专有名词，生成术语表草稿，用户只需确认 |
| **ChatGPT** | ASR 文本 → LLM 提取人名/地名/招式名 → 生成候选术语表 → 用户确认 |

**结论**：降低术语表使用门槛，让普通用户也能用上。

---

### 2.6 整季级一致性记忆（ChatGPT 提到）

| 来源 | 建议 |
|------|------|
| **ChatGPT** | 创建 `series_memory.json`，跨集保存角色名、角色关系、口癖、称呼方式、术语 |
| 痛点 | 第一集叫"星野爱"，第二集变成"星野艾" |

**结论**：对批量处理整部番剧非常关键，但属于后置功能。

---

### 2.7 翻译 Adapter 设计模式（ChatGPT 重点提）

| 来源 | 建议 |
|------|------|
| **ChatGPT** | 把翻译接口做成 Adapter 模式：SakuraTranslator（默认非商用）→ QwenTranslator（许可证友好 fallback）→ GalTranslTranslator（风格备选）→ ExternalAPITranslator（API 备选） |

**结论**：不把 Sakura 写死成唯一核心，保留备用通道，架构更健壮。

---

### 2.8 A/B 模型评测小工具（ChatGPT 提到）

| 来源 | 建议 |
|------|------|
| **ChatGPT** | 手工标注几段 gold sample，内置小 benchmark，换模型自动输出 CER / 术语命中率 / 空翻译率 |

**结论**：避免"感觉这个模型更好"的主观判断，用数据说话。

---

### 2.9 SQLite 替代 JSONL 作为主状态管理（ChatGPT 建议，豆包认为 JSONL 够用）

| 来源 | 建议 |
|------|------|
| **ChatGPT** | JSONL 不适合作为唯一 checkpoint，建议 SQLite 做任务状态库 + JSONL 做日志 |
| **豆包** | JSONL 原子写入 + 阶段校验就够用，现阶段不需要 SQLite |
| **Gemini** | 没提，认可 JSONL 方案 |

**结论**：有分歧，可以先按豆包的建议用 JSONL + 原子写入，复杂了再迁移 SQLite。

---

### 2.10 推荐的全流程底座项目（豆包重点推荐）

| 来源 | 建议 |
|------|------|
| **豆包** | 推荐基于 **pyVideoTrans** 二次开发，不用从零搭建。它已经实现了完整的视频→ASR→翻译→字幕→嵌入全流程、GUI、断点续传、批量处理。只需替换 ASR 为 Anime Whisper、对接 SakuraLLM Ollama 接口 |
| **Gemini** | 推荐参考 **VideoLingo**，剥离其通用翻译，接入 Anime Whisper + SakuraLLM |
| **ChatGPT** | 没有推荐直接作为底座，但推荐了多个可参考的专项工具 |

**项目链接**：
- pyVideoTrans: https://github.com/jianchang512/pyvideotrans
- VideoLingo: https://github.com/Huanshere/VideoLingo

---

## 三、其他重要补充项目（我们没调研到的）

### 来自豆包
| 项目 | 类别 | 说明 |
|------|------|------|
| Demucs | 音频分离 | Meta 人声/BGM 分离，ASR 前置 |
| UVR5 | 音频分离 | 更偏人声提取，社区验证 |
| pyVideoTrans | 全流程底座 | 省 80% 基础工程，推荐二次开发 |
| SubtitleEdit | 字幕编辑 | 时间轴/分行算法成熟，可复用 |
| ffsubsync | 字幕对齐 | 音频特征对齐，比规则调整好一个量级 |
| N46Whisper | 日语字幕 | 参考后处理逻辑 |
| VideoCaptioner | 字幕分割 | LLM 语义级断句 |
| LinguaGacha | ACGN 翻译 | 原生支持 SakuraLLM，术语表/翻译记忆 |

### 来自 Gemini
| 项目 | 类别 | 说明 |
|------|------|------|
| BS-RoFormer | 音频分离 | 字节跳动 SOTA 音源分离 |
| VideoLingo | 全流程 | Nerflix 级字幕，三步翻译机制 |
| UVR5 | 音频分离 | 同上 |

### 来自 ChatGPT
| 项目 | 类别 | 说明 |
|------|------|------|
| stable-ts | 时间戳优化 | Whisper 时间戳稳定化 |
| WhisperX | ASR+对齐 | 词级强制对齐 |
| Subtitle Edit | 字幕编辑 | 成熟字幕处理 |
| Aegisub | 字幕编辑 | ASS 编辑标准工具 |
| ffsubsync | 字幕对齐 | 自动同步 |
| N46Whisper | 日语字幕 | 参考日语流程 |
| SubFlow | 字幕提取翻译 | 提取 MKV 内嵌字幕 → 翻译 → remux |
| KrillinAI | 全流程 | 视频本地化（含配音） |
| Voice-Pro | 全流程 GUI | Gradio Web App |
| PANNs | 音频事件 | 527 类音频标签 |
| YAMNet | 音频事件 | 521 类音频事件 |

---

## 四、三模型各自的核心观点

### 豆包
- **最务实**，重点推荐了 pyVideoTrans 作为二次开发底座，强调"省 80% 基础工程"
- 评分最细，给出具体的 MVP 5 步路径和每步时间
- 对说话人分离最悲观，建议"不要抱过高预期"

### Gemini
- **最简洁**，但切中要害
- 重点强调**人声分离**作为 ASR 前置步骤的重要性
- 建议将 5 个 Agent 合并为一次 prompt 工程，而不是并行
- 最关注显存管理，建议 ASR 和翻译用独立进程

### ChatGPT
- **最全面**，回复最长（731 行），内容最细
- 提出了最多的"新功能"（可疑行检测、A/B 评测、翻译 Adapter、整季记忆、外挂字幕优先）
- 最强调架构设计，推荐 SQLite 而非 JSONL
- 给出了最详细的"最容易翻车的坑"列表

---

## 五、汇总：如果我们采纳建议，新增功能列表

| 新增功能 | 来源 | 优先级建议 |
|---------|------|-----------|
| 人声/BGM 分离预处理（Demucs/UVR5） | 豆包+Gemini+ChatGPT | 阶段 1（可选前置） |
| 硬字幕 OCR 提取 + 翻译 | 豆包+ChatGPT | 阶段 2 |
| 可疑字幕行检测（校对降级） | ChatGPT | 阶段 1（MVP 末期） |
| 上下文窗口翻译（3-5 句上下文） | 豆包+Gemini+ChatGPT | 阶段 0（MVP） |
| 专有名词自动发现（术语表草稿） | 豆包+ChatGPT | 阶段 1 |
| 整季级一致性记忆 | ChatGPT | 阶段 2 |
| 翻译 Adapter 模式（Sakura/Qwen 备用） | ChatGPT | 阶段 0（架构设计） |
| A/B 模型评测小工具 | ChatGPT | 阶段 1 |
| 外挂字幕优先模式（提取已有字幕） | ChatGPT | 阶段 1 |
| 语义级断句 | 豆包 | 阶段 1 |
| 番剧类型预设（日常/战斗/古风） | 豆包 | 阶段 2 |
| 跨集术语与翻译记忆复用 | 豆包 | 阶段 2 |
| 字幕智能分行排版（15-20 字/行） | 豆包 | 阶段 1 |
| 参考项目：pyVideoTrans（二次开发底座） | 豆包 | 评估阶段 |
| 参考项目：VideoLingo | Gemini | 评估阶段 |
| 参考项目：SubtitleEdit（字幕后处理） | 豆包+ChatGPT | 阶段 1 集成 |
| 参考项目：ffsubsync（字幕对齐） | 豆包+ChatGPT | 阶段 1 集成 |
| 参考项目：Aegisub（人工校对出口） | ChatGPT | 阶段 1 集成 |