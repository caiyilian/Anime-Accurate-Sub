# Sprint 16 高级功能完成报告

## 结论

Sprint 16 的五个高级功能已全部实现并合入 `master`。本轮不是只做接口占位：说话人样式、
人工校对和视频预览均使用《轻音少女》第 9 集的真实流水线输出验证；Web UI 使用浏览器完成
上传页、任务接口、校对和视频预览回归；插件系统已实际接入翻译、ASR 和字幕生成路径。

## 子阶段交付

| 子阶段 | 交付内容 | 提交 | PR / Issue |
|---|---|---|---|
| S16.1 | 保留 `speaker` 信息；支持 JSON 角色映射、ASS 角色颜色与 SRT 角色名前缀 | `7463c2d` | [PR #128](https://github.com/caiyilian/Anime-Accurate-Sub/pull/128) / [Issue #129](https://github.com/caiyilian/Anime-Accurate-Sub/issues/129) |
| S16.2 | FastAPI Web UI：上传、参数配置、后台任务、检查点进度、日志和结果下载 | `cc23fff` | [PR #130](https://github.com/caiyilian/Anime-Accurate-Sub/pull/130) / [Issue #131](https://github.com/caiyilian/Anime-Accurate-Sub/issues/131) |
| S16.3 | 带源文件 SHA 冲突保护、备份与审计记录的校对稿导出/导入；CLI/Web 共用 | `28d5c42` | [PR #132](https://github.com/caiyilian/Anime-Accurate-Sub/pull/132) / [Issue #133](https://github.com/caiyilian/Anime-Accurate-Sub/issues/133) |
| S16.4 | 翻译、ASR、字幕样式三类插件注册表；支持本地文件和 Python entry point | `9e40e66` | [PR #134](https://github.com/caiyilian/Anime-Accurate-Sub/pull/134) / [Issue #135](https://github.com/caiyilian/Anime-Accurate-Sub/issues/135) |
| S16.5 | 基于 libass 的短片段预览；CLI/Web 共用；修复 seek 后字幕时间基偏移 | `4c39a0a` | [PR #136](https://github.com/caiyilian/Anime-Accurate-Sub/pull/136) / [Issue #137](https://github.com/caiyilian/Anime-Accurate-Sub/issues/137) |

## 验证结果

- `python -m pytest tests -q --disable-warnings`：2026-07-29 重跑，144/144 通过。
- `python scripts/test_all.py`：S3-S16 共 22/22 项通过，机器可读结果见
  `docs/evaluation/S15.3_regression_results.json`。
- 第 9 集第 253 行经中文字幕组参考和视频上下文复核，从英文拟声修订为“喂！”，随后重新
  生成 SRT、ASS 和硬字幕视频；修订包含原值、操作者、时间和原因的审计记录。
- 10.01 秒预览片段在约 0.4 秒内生成；浏览器报告 `readyState=4`，时长、字幕画面均正确，
  控制台无错误。
- GitHub 收尾前检查：开放 Issue 0 个，开放 PR 0 个。

真实验证产物：

- `.omo/season_v4_tagged/轻音少女_第09集/轻音少女_第09集_proofread_subs.mp4`
- `.omo/season_v4_tagged/轻音少女_第09集/轻音少女_第09集_preview.mp4`

## 与整季质量结果的关系

《轻音少女》第一季已使用无广告源 `data/轻音少女_全集` 完成最终质量重跑：14 集、5,419
个片段，SRT、ASS 和烧录 MP4 均为 14/14。中文参考覆盖率为 98.90%，corpus char-F1 为
0.6855、chrF 为 0.4251；规则质量检查为 0 个 error，最终未决 `needs_review` 为 0。翻译批次
使用稳定行 ID，避免模型漏行后译文错绑时间轴；Sakura 校验失败时依次使用同服 GalTransl
和 SenseNova 救援，仍不可靠的结果会进入隔离与人工复核，而不会静默当成正常译文。

字幕组参考只用于主流程完成后的离线差异审计，不是生产翻译输入。最终独立复核 327/327
完成，20 条模型争议建议经日文、上下文、相邻分段和画面人工裁决，仅采纳其中 8 条；受影响
集数随后重新生成 SRT/ASS 并重新烧录。

结果表明当前最大的准确率瓶颈仍包括无日文字幕时的 ASR，而不是模型连通性：远程 Sakura
14B 和同服务器 `crosery/GalTransl-7B-v2.6:Q6_k` 均已实际调用；本机 `11435` 与 `11434` 的
`EasonONLINE/Sakura-qwen2.5-v1.0:7b` 也已验证可用，但未混入整季主指标。

## 已知边界

- S16.1 完成的是说话人标签保存、人工角色映射和颜色呈现；动漫角色的自动身份识别准确率仍
  不足以取消人工确认，因此没有把广义“说话人分离”标成完全完成。
- TQE 和更多语言对不属于本 Sprint 五个子阶段，仍保留在后续需求中。
- Web 上传文件名会净化，任务与输出限制在工作目录；校对导入要求源 SHA 一致，避免旧校对稿
  静默覆盖新结果。
