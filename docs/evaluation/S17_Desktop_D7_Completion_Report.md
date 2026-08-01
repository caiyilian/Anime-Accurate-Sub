# Desktop D7 最终验收报告

验收日期：2026-08-01
关联需求：Issue #190
阶段 Issue：Issue #205

## 自动化门禁

在 desktop 目录全新 npm ci 后执行并通过：

- npm run lint
- npm run format:check
- npm run typecheck
- npm test：12 个测试文件，25 项测试
- npm run build
- npm run smoke

开发版 smoke 同时使用真实的轻音少女第一集文件，确认视频接收、质量检查、五 Agent 和 MQM 参数进入实际 Python 命令。

## NSIS 安装器

安装器：

~~~text
desktop/release/Anime Accurate Sub-Setup-0.1.0-x64.exe
~~~

已验证：

1. NSIS 静默安装退出码为 0；
2. 安装版在隔离 userData 中启动成功；
3. 安装版诊断将项目根目录解析为自身 resources/backend；
4. 安装版可选择真实 MP4，质量检查、五 Agent、MQM 参数均为 true；
5. 静默卸载退出码为 0，安装 EXE 已删除。

资源安全扫描输出 RELEASE_SECRET_SCAN_OK，扫描 108 个打包文件。扫描输入包含本机 1 个 GitHub token 和 6 个 SenseNova Key 的实际值，未发现任何匹配；安装包同时排除了模型、测试媒体和输出目录。

## 真实桌面 Pipeline

输入是无广告片源：

~~~text
data/轻音少女_全集/轻音少女_第01集.mp4
~~~

为缩短验收时间，从 300 秒截取 60.083 秒，并使用同一片源的 21 条日文字幕作为日文输入。桌面 smoke 使用：

- Sakura：172.31.102.189 上的 crosery/sakura-14b-qwen2.5-v1.0-q6k:latest；
- 系列记忆：data/series_memory/k-on_s1.json；
- 术语表：data/glossary/k-on_glossary.json；
- 多 Agent：5 角色 + 保守总编；
- MQM：SenseNova Flash Lite + DeepSeek。

桌面 PipelineManager 快照最终为 completed、job succeeded、exitCode 0、overall 100%。阶段耗时为：翻译 71.6 秒，多 Agent 209.6 秒，MQM 195.6 秒，嵌字 4.4 秒。

输出目录：

~~~text
output/desktop-test/pipeline-run-20260801-123354/k-on-d7-60s
~~~

目录包含 SRT、ASS、嵌字 MP4、quality_report.json、multi_agent_review.json、mqm_quality_report.json、mqm_reviewed.json、checkpoint.json 和各阶段进度文件。SRT/ASS 均为 21 条；嵌字视频为 60.083 秒，包含 H.264 视频流和 AAC 音频流；所有审计文本均为有效 UTF-8，无 Unicode 替换字符和 NUL。

质量报告的 stats.errors 为 0，3 条 duration_too_short 为 warning；MQM 21 条中 17 条 approved、4 条 needs_review、0 条 errors。needs_review 是保守人工裁决门，不是 Pipeline 失败。

## 取消与恢复

桌面 smoke 在 checkpoint 出现后取消一次，确认 checkpoint 保留；随后从同一视频和同一输出目录调用 resume。最终报告字段为：

~~~text
canceledWithCheckpoint=true
resumed=true
status=completed
jobStatus=succeeded
~~~

## 交付文档

面向新用户的完整教程位于 docs/usage/desktop-guide.md，内容包括安装、Python/FFmpeg/Sakura/SenseNova 准备、日文字幕可选分支、无参考字幕的新作品流程、配置、队列、进度、取消恢复、结果预览、needs_review 校对、重新打包和故障排查。
