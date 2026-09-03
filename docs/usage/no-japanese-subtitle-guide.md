# 没有日文字幕 — 单个 MP4 处理流程

> 适用场景：手头只有日语动漫 MP4，没有任何外挂字幕，也没有内嵌字幕轨。
> 程序会自动走 ASR 识别日语 → 翻译 → 审校 → 烧录字幕的全流程。

---

## 1. 前置条件

确保以下组件就绪后，再开始处理。

### 1.1 进入项目

```powershell
Set-Location 'E:\projects\Anime-Accurate-Sub'
```

### 1.2 FFmpeg（带 libass）

确认 ffmpeg 支持 `ass` 滤镜：

```powershell
ffmpeg -hide_banner -filters | Select-String 'ass|subtitles'
```

如果输出为空，使用仓库内预置的 full build：

```text
.omo\ffmpeg-libass\ffmpeg-2026-05-28-git-7b46c6a2a3-full_build\bin\ffmpeg.exe
```

### 1.3 Anime Whisper CT2 模型

确认 ASR 模型存在：

```powershell
Test-Path '.omo\efwkjn-anime-whisper\model.bin'
Test-Path '.omo\efwkjn-anime-whisper\tokenizer.json'
```

两项都应返回 `True`。如果模型在其他路径，设置环境变量：

```powershell
$env:ANIME_WHISPER_MODEL = 'D:\你的路径\efwkjn-anime-whisper-ct2'
```

### 1.4 远程 Sakura 翻译（服务器 172.31.102.189）

确认远程 Ollama 可达：

```powershell
Test-NetConnection 172.31.102.189 -Port 11434
Invoke-RestMethod 'http://172.31.102.189:11434/api/tags' -TimeoutSec 30
```

### 1.5 SenseNova API Key（多 Agent 审查 + MQM 评分用）

Key 文件（已被 `.gitignore` 排除）：

```text
config\sensenova_apikeys
```

格式：每行一个 API Key，空行会被忽略。

```text
第一账号的 API Key
第二账号的 API Key
第三账号的 API Key
```

### 1.6 运行预检

```powershell
python -X utf8 scripts\anime_sub.py --version
python -X utf8 scripts\test_all.py
```

---

## 2. 完整流程概览

```
MP4
  → 优先查找同目录日文外挂字幕 / 内嵌日文文本轨
  → 都没找到 → FFmpeg 提取音频 → Anime Whisper ASR（日语识别）
  → 远程 Sakura-14B 翻译（上下文窗口 + 翻译记忆）
  → 多 Agent 审查（5 个角色并行 + 保守总编）
  → 双裁判 GEMBA-MQM 质量评分（Flash Lite + DeepSeek）
  → 生成 SRT / ASS → 规则质量检查 → libass 烧录到视频
  → 可选人工校对 → 重新生成字幕和成片
```

---

## 3. 一条命令跑完

```powershell
Set-Location 'E:\projects\Anime-Accurate-Sub'

$video = 'E:\你的视频\第01集.mp4'
$output = 'E:\projects\Anime-Accurate-Sub\output\你的作品名'

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

### 关键参数说明

| 参数 | 作用 |
|:-----|:-----|
| `--asr-backend anime_whisper` | 指定 ASR 方案 |
| `--prefer-japanese-subtitles` | 先找同目录日文外挂/内嵌轨，找不到回退 ASR |
| `--backend sakura` | 使用 Sakura 翻译适配器 |
| `--translation-context-window 3` | 给翻译提供前 3 句已接受的中文上下文 |
| `--translation-memory` | 翻译记忆，相同台词自动复用 |
| `--multi-agent-review` | 五角色 + 总编审查 |
| `--mqm-quality-review` | 双裁判 MQM 质量评分 |
| `--quality-check` | 规则质量检查 |

### 如果没找到日文字幕，日志会显示

```text
No Japanese sidecar or text track found; falling back to ASR
```

这是正常行为，表示正在走"音频提取 → Anime Whisper ASR"分支。

---

## 4. 可选：准备术语表和系列记忆（推荐）

首次跑完后，可以从 ASR 结果中整理角色名和专有名词，后续集数使用。

术语表格式（参考 `data\glossary\k-on_glossary.json`）：

```json
{
  "terms": [
    {"ja": "角色名", "zh": "固定中文名"},
    {"ja": "必殺技", "zh": "必杀技"}
  ]
}
```

系列记忆格式（参考 `data\series_memory\k-on_s1.json`）：

```json
{
  "characters": [
    {
      "name": "角色名",
      "aliases": ["昵称1", "昵称2"],
      "style": "说话风格描述",
      "relationships": {"与其他角色关系": "描述"}
    }
  ],
  "terms": [{"ja": "...", "zh": "..."}]
}
```

准备好后追加到命令中：

```powershell
  --memory 'data\series_memory\你的作品.json' `
  --glossary 'data\glossary\你的作品.json'
```

---

## 5. 输出文件说明

假设输入是 `第01集.mp4`，输出目录为 `output\你的作品名\第01集\`：

| 文件 | 含义 |
|:-----|:------|
| `checkpoint.json` | 阶段状态，断点续传依据 |
| `第01集.wav` | 提取的 16kHz 单声道音频 |
| `asr_results.json` | ASR 日文文本 + 时间轴 |
| `translated.json` | Sakura 初译结果 |
| `multi_agent_review.json` | 五角色审查 + 总编完整证据 |
| `reviewed.json` | 多 Agent 自动修正后的字幕 |
| `mqm_quality_report.json` | 双裁判 MQM 评分 + 修订证据 |
| `mqm_reviewed.json` | **最终用于生成字幕的数据** |
| `第01集.srt` | 通用中文字幕 |
| `第01集.ass` | 带样式的 ASS 中文字幕 |
| `第01集_subs.mp4` | **最终成片（字幕已烧录）** |
| `quality_report.json` | 规则检查结果 |

---

## 6. 中断后续传

命令执行过程中如果网络断开、终端关闭、模型返回 429/500，**直接重新执行完全相同的命令**。程序会自动读取 checkpoint 跳过已完成阶段，从未完成处继续。

不要为了"继续"而换输出目录，否则会从头开始。

---

## 7. 跑完后检查

### 7.1 检查质量报告

```powershell
python -c "import json; r=json.load(open(r'$output\第01集\mqm_quality_report.json')); print('needs_review:', sum(1 for s in r['segments'] if s['status']=='needs_review'))"
```

`needs_review` 为 0 表示所有裁判意见一致，无需人工干预。

### 7.2 检查规则检查结果

```powershell
python -c "import json; r=json.load(open(r'$output\第01集\quality_report.json')); print('errors:', r.get('errors', r.get('summary',{}).get('errors','?')))"
```

`errors` 应为 0。

### 7.3 确认成片完整性

```powershell
ffprobe -v error -show_entries stream=codec_type -of csv=p=0 '$output\第01集\第01集_subs.mp4'
```

应该同时看到 `video` 和 `audio`。

### 7.4 抽样检查

打开 `*_subs.mp4`，随机检查开头、中段、高潮、快速对话场景的字幕准确性。

---

## 8. 有人工校对需求怎么办

如果 MQM 留下 `needs_review` 或你发现需要修改的译文：

导出校对稿：

```powershell
python -X utf8 scripts\proofread.py export `
  --input "$output\第01集\mqm_reviewed.json" `
  --quality-report "$output\第01集\mqm_quality_report.json" `
  --output "$output\第01集\proofread_sheet.json" `
  --only-review
```

修改 `proofread_sheet.json` 后应用并重建字幕：

```powershell
python -X utf8 scripts\proofread.py apply `
  --input "$output\第01集\mqm_reviewed.json" `
  --sheet "$output\第01集\proofread_sheet.json" `
  --history "$output\第01集\proofread_history.jsonl" `
  --operator '你的名字' `
  --regenerate `
  --subtitle-base "$output\第01集\第01集"
```

重新烧录成片：

```powershell
python -X utf8 -c "from scripts.anime_sub import embed_subtitle; embed_subtitle(r'$video', r'$output\第01集\第01集.ass', r'$output\第01集\第01集_proofread_subs.mp4')"
```

---

## 9. 最终交付检查清单

- [ ] 命令显示所有阶段正常完成
- [ ] `mqm_reviewed.json` 无空译文、日文残留、重复幻觉
- [ ] `quality_report.json` 中 `errors` 为 0
- [ ] `needs_review` 已逐条裁决或确认保留
- [ ] SRT 和 ASS 能正常加载
- [ ] 抽样检查开头、中段、高潮、快速对话无误
- [ ] `*_subs.mp4` 同时包含视频流和音频流
- [ ] 角色名、称谓、专有名词前后一致