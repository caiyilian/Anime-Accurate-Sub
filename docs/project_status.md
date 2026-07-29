# Anime Accurate Sub — 项目现状

> 最后更新：2026-07-29
> 目标：动漫日语视频 → 准确中文字幕 → SRT/ASS → 嵌入字幕的视频

## 结论

S0-S16 已全部完成，当前没有剩余的 Sprint 16 高级功能。主流程已经能对单个 MP4 或整季
视频执行日文字幕优先/Anime Whisper ASR、远程 Sakura 翻译、上下文与术语约束、翻译记忆、
五角色多 Agent 审查、双裁判 GEMBA-MQM、质量检查、人工校对、SRT/ASS 生成和 libass 视频
烧录。

单个 MP4 的完整使用方法见
[单个动漫 MP4 高质量全流程教程](usage/full-pipeline-tutorial.md)。

## Sprint 进度

| Sprint | 内容 | 状态 |
|---|---|:---:|
| S0 | 基础设施 | ✅ |
| S1-S2 | 通用/专项工具评估与架构决策 | ✅ |
| S3-S4 | Anime Whisper 主力与备选 ASR、时间戳优化 | ✅ |
| S5-S7 | 音频分离评估、说话人处理、OP/ED 检测 | ✅ |
| S8-S9 | 翻译模型、上下文、术语表、翻译记忆 | ✅ |
| S10 | SRT/ASS、样式与时间轴处理 | ✅ |
| S11 | 规则检查、多 Agent、GEMBA-MQM | ✅ |
| S12 | 断点续传与批量处理 | ✅ |
| S13-S14 | 辅助工具、翻译 Adapter、系列记忆 | ✅ |
| S15 | 全流程 CLI、可靠长视频 ASR/翻译、回归测试 | ✅ |
| S16 | 角色样式、Web UI、人工校对、插件、视频预览 | ✅ |

Sprint 16 的提交、PR、Issue 和真实验证说明见
[Sprint 16 高级功能完成报告](evaluation/S16_Completion_Report.md)。

## 当前生产流程

```text
输入 MP4
  ├─ 可靠日文 SRT/ASS/VTT 或内嵌日文文本轨 → 跳过 ASR
  └─ 无日文字幕 → FFmpeg 音频提取 → Anime Whisper CT2
       ↓
远程 Sakura-14B
  ├─ 前文上下文
  ├─ 术语表
  ├─ 系列记忆
  ├─ 翻译记忆
  └─ 格式校验失败：GalTransl → SenseNova 救援 → 隔离复核
       ↓
五角色多 Agent + 保守总编
       ↓
SenseNova Flash Lite / DeepSeek 双裁判 GEMBA-MQM
       ↓
SRT + ASS + 规则质量报告 + libass 烧录 MP4
       ↓
可选人工校对、短视频预览和重新烧录
```

人工中文字幕组文件不属于生产依赖。它只在有参考答案时用于离线对齐、差异定位和盲测评分；
完全没人翻译过的动漫仍可走完整流程。

## 《轻音少女》第一季最终验证

输入使用无广告片源：

```text
E:\projects\Anime-Accurate-Sub\data\轻音少女_全集
```

最终输出：

```text
E:\projects\Anime-Accurate-Sub\.omo\season_v6_quality
```

每集最终成片：

```text
.omo\season_v6_quality\轻音少女_第XX集\轻音少女_第XX集_subs.mp4
```

### 规模与质量检查

| 指标 | 最终结果 |
|---|---:|
| 集数 | 14 |
| 片段数 | 5,419 |
| SRT / ASS / 烧录 MP4 | 14 / 14 / 14 |
| 质量检查 error | 0 |
| `needs_review` 未决项 | 0 |
| 超过 20 秒的异常字幕段 | 0 |
| Unicode 替换字符 | 0 |

质量检查仍有 1,140 个 warning，其中 976 个是原始时间轴不足 1 秒的短语气词/快速对白，
118 个是短译文提示，26 个是已记录的翻译兜底，14 个是长时长提示，6 个术语提示均经上下文
确认是合理省略或同义表达；它们不是阻断性错误。

### 与字幕组参考的离线比较

| 指标 | 最终结果 |
|---|---:|
| 参考覆盖率 | 98.90% |
| corpus chrF | 0.4251 |
| corpus 字符 F1 | 0.6855 |
| corpus 编辑相似度 | 0.4380 |

这不是“绝对准确率”。字幕组版本包含意译、合并/拆分、时间轴偏移和少量错误；最终人工终审
也明确拒绝了一些虽然更接近参考、但日文语义或角色上下文不正确的建议。

### 审查范围

- 正常主流程：五类审查角色并行检查准确性、自然度、一致性、ASR 和风格，再由总编保守应用；
- MQM：Flash Lite 与 DeepSeek 双裁判，对低分候选进行编辑和双重复核；
- 字幕组差异审计：327 条目标样本全部完成；
- 第一轮人工终审：329 条（含两条相邻上下文追加项）；
- 最终修改后的独立复核：327/327 完成，20 条争议建议全部人工裁决，最终采纳 8 条；
- 对受影响集数重新生成 SRT/ASS 并重新烧录，随后再次运行全季质量检查。

## 关键模块

| 模块 | 路径 | 说明 |
|---|---|---|
| 全流程 CLI | `scripts/anime_sub.py` | 单集/批量生产入口 |
| ASR | `scripts/asr_engine.py` | 可靠长视频 Anime Whisper 和字幕安全分段 |
| 翻译适配 | `scripts/translator_adapter.py` | Sakura/GalTransl/Qwen/External、校验与救援 |
| 翻译引擎 | `scripts/translation_engine.py` | 批次、稳定行 ID、上下文和断点 |
| 多 Agent | `scripts/review_agents.py` | 五角色审查与保守总编 |
| MQM | `scripts/mqm_quality_review.py` | 双裁判、编辑、复核和审计 |
| 最终参考审计 | `scripts/adjudicate_fansub_review.py` | 可选字幕组差异审查和人工覆盖 |
| 人工校对 | `scripts/proofread.py` | SHA 冲突保护、历史记录和字幕重建 |
| 字幕生成 | `scripts/subtitle_gen.py` | SRT/ASS、样式和角色映射 |
| 质量检查 | `scripts/quality_check.py` | 规则检查报告 |
| Web UI | `scripts/web_ui.py` | 上传、后台任务、日志、校对、预览和监控 |
| 视频预览 | `scripts/video_preview.py` | libass 短片段预览 |
| 插件系统 | `scripts/plugin_system.py` | 翻译、ASR、字幕样式扩展 |
| 回归测试 | `scripts/test_all.py` | S3-S16 共 22 项回归入口 |

## 当前模型与服务

| 用途 | 模型/服务 | 状态 |
|---|---|:---:|
| 主翻译 | `172.31.102.189` / Sakura-14B Q6_K | ✅ 已用于整季 |
| 翻译格式兜底 | `172.31.102.189` / `crosery/GalTransl-7B-v2.6:Q6_k` | ✅ 已验证 |
| 多 Agent / MQM 主力 | SenseNova `sensenova-6.7-flash-lite`，多账号轮询 | ✅ |
| 深度裁判 | SenseNova `deepseek-v4-flash` | ✅ |
| ASR | `.omo/efwkjn-anime-whisper` CT2 | ✅ |
| 字幕烧录 | `.omo/ffmpeg-libass` full build | ✅ |

本机 Sakura 可以作为远程服务器不可用时的后备，但不应与本轮整季指标混用；切换模型后应使用
新输出目录单独评测。

## 已知边界

- 完全未知作品没有人工参考答案时，无法计算“与字幕组相似度”，但不影响生成；质量依靠日文
  源、上下文、多 Agent、MQM 和最终人工抽查保障。
- `needs_review` 是保守门禁，不是失败；生产交付前需要人工或独立审校者逐条裁决。
- 自动说话人身份识别仍不足以完全取消人工角色映射；S16.1 完成的是标签保存、映射和样式。
- 硬字幕使用 CRF 22 重新编码视频；如果要求视频流无损，应交付外挂 ASS/SRT，或另行封装软
  字幕轨。
- 日文外挂字幕必须与视频版本一致；广告、删减和不同 OP 长度会造成时间轴偏移。

## GitHub 状态

截至本次质量收尾前，Sprint 16 的五个 PR 均已合并，最终审查、人工覆盖和监控状态改进也已
分别通过 PR #182、#184、#186 合入 `master`；对应 Issue 均已关闭，临时分支均已删除。
