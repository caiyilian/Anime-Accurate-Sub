# 单个动漫 MP4 高质量全流程教程

> 适用环境：Windows PowerShell，项目目录 `E:\projects\Anime-Accurate-Sub`。
> 目标：输入一个日语动漫 MP4，输出日文识别结果、中文审校稿、SRT、ASS、质量报告和烧录中文字幕的 MP4。

## 1. 先明确：不需要现成中文字幕

主流程只需要动漫视频。日文字幕是可选的高质量输入；如果没有，程序会自动使用 Anime
Whisper 从音频识别日语。下载的中文字幕组文件只用于有参考答案时的离线评测，不参与未知
动漫的正常生成流程。

推荐生产链路如下：

```text
MP4
  ├─ 有可靠日文 SRT/ASS/VTT → 校验并直接读取日文时间轴
  └─ 没有日文字幕          → FFmpeg 提取音频 → Anime Whisper ASR
       ↓
远程 Sakura 翻译（上下文 + 术语表 + 系列记忆 + 翻译记忆）
       ↓
五角色多 Agent 审查 + 保守总编
       ↓
双裁判 GEMBA-MQM + 独立修订验证
       ↓
SRT / ASS → 质量检查 → libass 烧录 MP4
       ↓
可选人工校对 → 重新生成字幕和成片
```

## 2. 当前《轻音少女》最终成品在哪里

本次无广告第一季 14 集的总目录是：

```text
E:\projects\Anime-Accurate-Sub\.omo\season_v6_quality
```

每集成品位于对应子目录，命名规则为：

```text
.omo\season_v6_quality\轻音少女_第XX集\轻音少女_第XX集_subs.mp4
.omo\season_v6_quality\轻音少女_第XX集\轻音少女_第XX集.srt
.omo\season_v6_quality\轻音少女_第XX集\轻音少女_第XX集.ass
```

例如第一集：

```text
E:\projects\Anime-Accurate-Sub\.omo\season_v6_quality\轻音少女_第01集\轻音少女_第01集_subs.mp4
```

`*_subs.mp4` 是已经烧录中文字幕的最终视频；`.srt` 是通用字幕；`.ass` 带有动漫样式，
也是烧录视频时实际使用的字幕。

当前最终统计：14 集、5,419 个片段、质量检查 0 个 error；与人工字幕组参考的对齐覆盖率
98.90%，corpus chrF 0.4251，字符 F1 0.6855。参考分数只能衡量与该字幕组表达的接近程度，
不能等同于绝对翻译准确率。

## 3. 一次性环境准备

### 3.1 进入项目并创建 Python 环境

项目要求 Python 3.11 或更高版本。本机目前可直接使用 `D:\miniconda3\python.exe`；如果要
建立独立虚拟环境，可执行：

```powershell
Set-Location 'E:\projects\Anime-Accurate-Sub'
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e '.[web,dev]'
```

如果沿用本机 Miniconda，后文所有 `python` 都可以替换为：

```text
D:\miniconda3\python.exe
```

检查 Python 和 GPU：

```powershell
python --version
python -c "import torch; print('torch=', torch.__version__, 'cuda=', torch.cuda.is_available())"
```

ASR 默认使用 CUDA 和 `int8_float16`。如果 `cuda=False`，需要先安装与显卡驱动匹配的 CUDA
版 PyTorch；纯 CPU 运行整集会非常慢。

### 3.2 准备支持 libass 的 FFmpeg

程序优先使用仓库内以下构建：

```text
.omo\ffmpeg-libass\ffmpeg-2026-05-28-git-7b46c6a2a3-full_build\bin\ffmpeg.exe
```

如果该文件不存在，则使用系统 `PATH` 中的 `ffmpeg`。检查：

```powershell
ffmpeg -version
ffprobe -version
ffmpeg -hide_banner -filters | Select-String 'ass|subtitles'
```

最后一条至少应显示 `ass` 或 `subtitles` 滤镜，否则可以生成 SRT/ASS，但不能完成 ASS
硬字幕烧录。

### 3.3 准备 Anime Whisper CT2 模型

当前主力模型目录是：

```text
.omo\efwkjn-anime-whisper
```

该目录必须至少包含 `model.bin` 和 `tokenizer.json`。检查：

```powershell
Test-Path '.omo\efwkjn-anime-whisper\model.bin'
Test-Path '.omo\efwkjn-anime-whisper\tokenizer.json'
```

两项都应返回 `True`。如果模型放在其他位置，在当前 PowerShell 会话中设置：

```powershell
$env:ANIME_WHISPER_MODEL = 'D:\models\efwkjn-anime-whisper-ct2'
```

这里必须是可供 `faster-whisper` 使用的 CTranslate2 模型目录，不能只放原始 Transformers
权重。

### 3.4 准备远程 Sakura 与 SenseNova 密钥

推荐翻译配置已经提供：

```text
config\translator.sakura-remote.example.json
```

当前配置使用：

- 主翻译：`172.31.102.189` 上的 `crosery/sakura-14b-qwen2.5-v1.0-q6k:latest`；
- 格式/异常兜底：同服务器的 `crosery/GalTransl-7B-v2.6:Q6_k`；
- 两者仍失败时：SenseNova Flash Lite 为主、DeepSeek 为辅。

检查远程 Ollama：

```powershell
$tags = Invoke-RestMethod 'http://172.31.102.189:11434/api/tags' -TimeoutSec 30
$tags.models.name
```

SenseNova 密钥放在以下本地文件中，每行一个 API Key，空行会被忽略：

```text
config\sensenova_apikeys
```

示意格式：

```text
第一账号的 API Key
第二账号的 API Key
第三账号的 API Key
```

项目会线程安全地轮询所有行。不要把真实密钥写入教程、命令行、Issue、日志或 Git；该文件
已被 `.gitignore` 排除。

### 3.5 运行预检

```powershell
python -X utf8 scripts\anime_sub.py --version
python -X utf8 scripts\anime_sub.py --list-plugins
python -X utf8 scripts\test_all.py
```

`scripts/test_all.py` 应报告全部模块通过。正式处理前还建议做一次短预览，见第 9 节。

## 4. 准备单个 MP4 和可选资料

假设待处理文件是：

```text
E:\anime\新番\第01集.mp4
```

推荐为每部作品单独建立输出目录，例如：

```text
E:\projects\Anime-Accurate-Sub\output\新番
```

### 4.1 有日文字幕时

可靠的日文 SRT、ASS 或 VTT 通常比 ASR 更准确。可以直接指定：

```text
E:\anime\新番\第01集.ja.srt
```

它只应包含日文原文；不要把中文字幕组文件当作日文输入。

### 4.2 没有日文字幕时

不需要额外操作。使用 `--prefer-japanese-subtitles` 后，程序依次尝试：

1. 同目录中能唯一匹配的日文外挂字幕；
2. MP4/MKV 内嵌的日文文本字幕轨；
3. 都没有时自动回退到 Anime Whisper ASR。

### 4.3 术语表和系列记忆

对于完全新作品，可以先不传这两个参数；但为了最高质量，建议在已知角色名和专有名词后
准备文件。

术语表格式参考 `data\glossary\k-on_glossary.json`：

```json
{
  "terms": [
    {"ja": "主人公名", "zh": "固定中文名"},
    {"ja": "必殺技", "zh": "必杀技"}
  ]
}
```

系列记忆格式参考 `data\series_memory\k-on_s1.json`，可以记录角色全名、昵称、说话风格、
人物关系和作品级固定术语。第一集审校后继续复用同一系列记忆和翻译记忆，后续集数的一致性
会更好。

## 5. 推荐命令：有可靠日文字幕

这是质量优先的完整命令。PowerShell 中反引号必须是每行最后一个字符。

```powershell
Set-Location 'E:\projects\Anime-Accurate-Sub'

$video = 'E:\anime\新番\第01集.mp4'
$japanese = 'E:\anime\新番\第01集.ja.srt'
$output = 'E:\projects\Anime-Accurate-Sub\output\新番'

python -X utf8 -u scripts\anime_sub.py $video `
  --output-dir $output `
  --backend sakura `
  --config config\translator.sakura-remote.example.json `
  --japanese-subtitle $japanese `
  --translation-batch-size 16 `
  --translation-context-window 3 `
  --translation-memory "$output\translation_memory.jsonl" `
  --quality-check `
  --multi-agent-review `
  --review-config config\quality_review.sensenova.json `
  --mqm-quality-review `
  --mqm-config config\quality_mqm.sensenova.json
```

如果已经准备好本作品的文件，再追加：

```powershell
  --memory 'data\series_memory\新番.json' `
  --glossary 'data\glossary\新番.json'
```

不要传不存在或从其他作品复制来的术语表；错误的角色关系和译名会稳定地污染整部作品。

## 6. 推荐命令：只有 MP4、没有任何字幕

```powershell
Set-Location 'E:\projects\Anime-Accurate-Sub'

$video = 'E:\anime\新番\第01集.mp4'
$output = 'E:\projects\Anime-Accurate-Sub\output\新番'

python -X utf8 -u scripts\anime_sub.py $video `
  --output-dir $output `
  --backend sakura `
  --config config\translator.sakura-remote.example.json `
  --asr-backend anime_whisper `
  --prefer-japanese-subtitles `
  --translation-batch-size 16 `
  --translation-context-window 3 `
  --translation-memory "$output\translation_memory.jsonl" `
  --quality-check `
  --multi-agent-review `
  --review-config config\quality_review.sensenova.json `
  --mqm-quality-review `
  --mqm-config config\quality_mqm.sensenova.json
```

如果同目录没有外挂或内嵌日文字幕，日志会显示：

```text
No Japanese sidecar or text track found; falling back to ASR
```

这不是错误，表示正在走“音频提取 → Anime Whisper”分支。

## 7. 可选的 OP/ED 处理

自动检测需要能从 AnimeThemes 找到作品，并且作品名、季数和集数要对应。对于已确认的作品可在
上面的命令后追加：

```powershell
  --oped-series '作品在 AnimeThemes 上的名称' `
  --episode-number 1 `
  --oped-best-effort
```

`--oped-best-effort` 表示检测失败时继续全流程，不因为网络或作品名问题中止。

已知精确时间段时也可以离线指定，参数可重复：

```powershell
  --oped-range 'op:90.0-179.5' `
  --oped-range 'ed:1320.0-1409.5'
```

时间段不确定时宁可不删；错误范围会把正常对白一并过滤。

## 8. 每个参数在做什么

| 参数 | 作用 | 质量建议 |
|---|---|---|
| `--backend sakura` | 使用 Sakura 翻译适配器 | 保留 |
| `--config ...` | 固定远程模型、重试和兜底策略 | 保留，便于复现 |
| `--japanese-subtitle` | 使用指定日文字幕并跳过 ASR | 有可靠日文字幕时优先 |
| `--prefer-japanese-subtitles` | 先找日文轨，找不到再 ASR | 只有 MP4 时保留 |
| `--translation-batch-size 16` | 每次翻译 16 条 | 当前远程 Sakura 验证值 |
| `--translation-context-window 3` | 给翻译提供前 3 条已接受中文 | 当前生产验证值 |
| `--memory` | 注入人物关系、口癖和系列设定 | 连续剧集强烈建议 |
| `--glossary` | 固定角色名和专有名词 | 强烈建议 |
| `--translation-memory` | 跨集复用完全相同的台词 | 同一作品使用同一个文件 |
| `--multi-agent-review` | 五类审查角色加总编 | 质量优先时必须启用 |
| `--mqm-quality-review` | 双裁判 MQM 和候选修订复核 | 质量优先时必须启用 |
| `--quality-check` | 生成规则质量报告 | 保留 |
| `--speaker-map` | 把 `SPEAKER_00` 等映射为角色名和颜色 | 有可靠说话人标签时使用 |

多 Agent 和 MQM 都采用保守策略：只有高置信度、经过验证的修改才自动写入。意见分歧会保留
当前译文并标记为 `needs_review`，不会为了让统计好看而强行改字。

## 9. 正式跑整集前先生成短预览

如果已经有一份 ASS，可以先检查字体、字号、边距和烧录能力：

```powershell
python -X utf8 scripts\video_preview.py `
  'E:\anime\新番\第01集.mp4' `
  --subtitle 'E:\projects\Anime-Accurate-Sub\output\新番\第01集\第01集.ass' `
  --output 'E:\projects\Anime-Accurate-Sub\output\新番\第01集\preview.mp4' `
  --start 300 `
  --duration 20 `
  --preset fast
```

先看 20 秒预览可以及时发现字体缺失、字幕过大、颜色不合适或时间轴整体偏移。

## 10. 输出目录和文件说明

假设输入是 `第01集.mp4`，输出根目录是 `output\新番`，单集工作目录为：

```text
output\新番\第01集
```

主要文件：

| 文件 | 含义 |
|---|---|
| `checkpoint.json` | 阶段完成状态；断点续传依据 |
| `第01集.wav` | 从视频提取的 16 kHz 单声道音频；用日文字幕时不会生成 |
| `asr_results.json` | 日文文本和时间轴；来源可能是 ASR 或日文字幕 |
| `japanese_source.json` | 外挂/内嵌日文字幕的来源、SHA 和归档信息 |
| `translated.json` | Sakura 初译结果 |
| `translation_memory.jsonl` | 单集默认翻译记忆；显式指定后可跨集共享 |
| `multi_agent_review.json` | 五类审查与总编的完整证据 |
| `multi_agent_review.progress.jsonl` | 多 Agent 断点记录 |
| `reviewed.json` | 多 Agent 自动修正后的字幕 |
| `mqm_quality_report.json` | 双裁判 MQM、编辑候选和复核证据 |
| `mqm_quality_review.progress.jsonl` | MQM 断点记录 |
| `mqm_reviewed.json` | 最终用于生成字幕的结构化文本 |
| `第01集.srt` | 通用中文字幕 |
| `第01集.ass` | 带样式的中文字幕 |
| `第01集_subs.mp4` | 已烧录 ASS 中文字幕的最终成片 |
| `quality_report.json` | 规则检查结果 |

交付时至少保留 `*_subs.mp4`、`.srt`、`.ass`、`mqm_reviewed.json`、
`mqm_quality_report.json` 和 `quality_report.json`。其余文件对断点续传和审计仍有价值，不建议
在确认交付前删除。

## 11. 中断后怎么继续

网络断开、终端关闭或模型暂时 429/500 后，重新执行完全相同的命令即可。程序会读取：

- `checkpoint.json`；
- `translated.json`；
- `multi_agent_review.progress.jsonl`；
- `mqm_quality_review.progress.jsonl`。

已成功阶段会跳过，未完成请求会继续。不要为了“继续”而换输出目录，否则会从头开始。

如果你修改了模型、术语表、系列记忆或关键参数，并希望做一轮干净对比，最安全的做法是使用
一个新的输出目录，例如：

```text
output\新番_quality_v2
```

这样不会把旧检查点、旧翻译记忆和新配置混在一起。

## 12. 如何查看和处理 `needs_review`

打开单集的 `mqm_quality_report.json`，搜索：

```text
"status": "needs_review"
```

它不表示流水线失败，而是表示裁判意见冲突或候选修订没有达到自动应用门槛。可以由你、其他
人工审校者或 Codex 根据日文、上下文、画面和角色关系处理；不要求必须由项目所有者本人完成。

导出便于编辑的校对稿：

```powershell
$work = 'E:\projects\Anime-Accurate-Sub\output\新番\第01集'

python -X utf8 scripts\proofread.py export `
  --input "$work\mqm_reviewed.json" `
  --quality-report "$work\mqm_quality_report.json" `
  --output "$work\proofread_sheet.json" `
  --only-review
```

编辑 `proofread_sheet.json` 后应用，并自动重建 SRT/ASS：

```powershell
python -X utf8 scripts\proofread.py apply `
  --input "$work\mqm_reviewed.json" `
  --sheet "$work\proofread_sheet.json" `
  --history "$work\proofread_history.jsonl" `
  --operator '你的名字' `
  --regenerate `
  --subtitle-base "$work\第01集"
```

该流程会校验源文件 SHA，避免旧校对稿静默覆盖新版。除非明确知道冲突原因，不要使用
`--force`。

重新烧录人工校对后的 ASS：

```powershell
python -X utf8 -c "from scripts.anime_sub import embed_subtitle; embed_subtitle(r'E:\anime\新番\第01集.mp4', r'E:\projects\Anime-Accurate-Sub\output\新番\第01集\第01集.ass', r'E:\projects\Anime-Accurate-Sub\output\新番\第01集\第01集_proofread_subs.mp4')"
```

建议写到新的 `*_proofread_subs.mp4`，检查无误后再决定是否替换原成片。

## 13. 使用 Web UI

安装 Web 依赖后启动：

```powershell
Set-Location 'E:\projects\Anime-Accurate-Sub'
python -X utf8 scripts\web_ui.py --host 0.0.0.0 --port 8000
```

本机访问：

```text
http://127.0.0.1:8000/
```

局域网访问时，把 `127.0.0.1` 换成运行电脑的局域网 IPv4 地址，并确保 Windows 防火墙允许
TCP 8000 入站。`0.0.0.0` 只表示监听所有网卡，不是浏览器访问地址。

Web UI 可以上传视频、选择参数、后台运行、看日志、下载结果、导出/导入校对稿和生成短预览。
Web UI 启动的任务才会出现在它的任务列表；另一个终端里独立启动的 CLI 进程不会自动被接管。

要把某个整季输出目录显示在 `/monitor`，可以额外指定：

```powershell
python -X utf8 scripts\web_ui.py `
  --host 0.0.0.0 `
  --port 8765 `
  --season-root 'E:\projects\Anime-Accurate-Sub\.omo\season_v6_quality' `
  --season-episodes 14
```

然后访问 `http://127.0.0.1:8765/monitor`。

## 14. 有人工中文字幕时的可选离线评测

这一节不是未知动漫的生产步骤。只有你恰好拥有人工字幕组参考时才运行：

```powershell
python -X utf8 scripts\eval_fansub_quality.py `
  --prediction-root 'E:\projects\Anime-Accurate-Sub\output\某一季' `
  --reference-root 'E:\anime\某一季\中文字幕组' `
  --output 'E:\projects\Anime-Accurate-Sub\output\某一季\fansub_quality.json'
```

评测结果只用于找差异和抽样审计。不能因为参考字幕不同就机械替换当前译文；参考字幕也可能
意译、合并时间轴、漏译或翻错。为了得到严格盲测成绩，应先在不提供参考字幕的情况下冻结
生成结果，再运行这一步，并且不要把参考答案反馈到生成阶段。

## 15. 常见问题

### 远程 Sakura 连接超时或 HTTP 500

先检查服务器：

```powershell
Test-NetConnection 172.31.102.189 -Port 11434
Invoke-RestMethod 'http://172.31.102.189:11434/api/tags' -TimeoutSec 30
```

服务器恢复后重新执行原命令，检查点会继续。如果 Sakura 返回重复句、日文原文或格式错误，
适配器会重试，再尝试 GalTransl 和 SenseNova；最终仍失败的行会进入隔离/复核，而不会偷偷
当成正常中文。

### SenseNova 返回 429

检查 `config\sensenova_apikeys` 是否一行一个有效 Key，是否误带引号或空格。程序会轮询多
账号并重试；所有账号都达到窗口限额时，等待配额恢复后重跑相同命令。

### 找不到 Anime Whisper 模型

错误中会显示期望目录。确认 `model.bin`、`tokenizer.json` 存在，或者设置：

```powershell
$env:ANIME_WHISPER_MODEL = '实际 CT2 模型目录'
```

### FFmpeg 提示没有 `ass` 滤镜

当前 FFmpeg 不带 libass。安装 full build，或把本项目已经验证的构建放到第 3.2 节的固定目录。

### 字幕和画面整体错位

先确认输入视频没有插播广告、删减或不同片头长度。日文字幕必须和该 MP4 是同一片源；来自
其他版本的字幕即使作品和集数相同，也可能从某个时间点开始整体偏移。

### 修改 JSON 后重跑却没有变化

流水线看见已完成的 `checkpoint.json` 会跳过对应阶段。人工校对应走第 12 节的导出/应用/
重生成流程；模型或参数对比应使用新的输出目录。

## 16. 最终交付检查表

处理一个新 MP4 后，至少确认：

- 命令最后显示所有启用阶段完成；
- `mqm_reviewed.json` 没有空译文、整段日文残留或重复幻觉；
- `quality_report.json` 的 `errors` 为 0；
- `needs_review` 已经逐条人工裁决，或明确接受保留原译；
- SRT 和 ASS 都能正常加载；
- 随机检查开头、中段、高潮、快速对话和结尾；
- `*_subs.mp4` 同时包含视频流和音频流，时长与源视频接近；
- 角色名、称谓、专有名词和前后文一致；
- 如果使用日文外挂字幕，确认它与 MP4 片源完全匹配；
- 如果使用参考中文字幕评分，清楚区分“与参考相似”与“语义正确”。

完成以上检查后，`*_subs.mp4` 才是建议交付的最终成片，`.srt` 和 `.ass` 则作为可修改、
可复用的字幕源一并保存。
