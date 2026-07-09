# 测试数据集资源清单

> 用于 Anime Accurate Sub 项目的测试数据来源
> 更新日期: 2026-07-09

---

## 一、当前已下载的数据

### 1.1 HF v2 音频数据集 — 已就绪

**来源**: `joujiboi/japanese-anime-speech-v2` (292637 条, 397 小时动漫风格语音)
**镜像**: https://hf-mirror.com/datasets/joujiboi/japanese-anime-speech-v2
**下载方式**: `scripts/download_test_data.py`

**当前状态**: 已下载 200 条样本到 `data/test/`

| 文件 | 说明 |
|------|------|
| `sample_0000.wav` ~ `sample_0199.wav` | 200 个 WAV 音频文件（动漫风格日语语音） |
| `manifest.json` | 音频文件与日文文本的对照表 |
| `sfw-00000.parquet` | 原始 parquet 数据文件（0.5GB，6969 条） |

**用途**:
- **ASR 准确率测试**: 输入音频 → ASR 识别 → 对比日文原文，计算 CER
- 不需要自己找视频，开箱即用

**数据格式**:
```json
// manifest.json 内容示例
[
  {"audio_file": "sample_0000.wav", "transcription": "ひと～つ、人の生き血をすすり"},
  {"audio_file": "sample_0001.wav", "transcription": "うぅ…ひっく、ひっく…行っちゃやですぅ"}
]
```

### 1.2 Kitsunekko 日文字幕 — 克隆中

**来源**: https://kitsunekko.net/subtitles/japanese/
**GitHub 镜像**: https://github.com/Ajatt-Tools/kitsunekko-mirror.git
**下载方式**: `git clone --depth 1 ...` 或 `scripts/download_kitsunekko_subs.py`

**用途**: 提供完整动漫剧集的日文文本（SRT/ASS 格式），可用于翻译模块测试。配合对应视频文件可做 ASR 测试。

**脚本**: `scripts/download_kitsunekko_subs.py`
- 用法: `.venv\Scripts\python scripts\download_kitsunekko_subs.py <动漫名>`
- 无参数时列出所有 2595 部可用动漫
- 示例: `python scripts/download_kitsunekko_subs.py Bakemonogatari`
- 下载到 `data/subtitles/<动漫名>/`

---

## 二、测试数据用途说明

### ASR 测试（当前可用）
```
测试数据: data/test/ 下的 200 条音频 + 日文文本
流程: 输入 WAV → Anime Whisper ASR → 输出日文 → 对比原文 → 计算 CER
指标: CER (字符错误率), RTF (实时率)
```

### 翻译测试（需要 Kitsunekko 字幕克隆完毕后）
```
测试数据: Kitsunekko 的日文字幕（SRT/ASS）
流程: 日文字幕 → SakuraLLM 翻译 → 输出中文 → 人工评估
```

### 全流程测试（需要自己提供视频）
```
测试数据: 动漫视频文件 + 对应字幕
流程: 视频 → 提取音频 → ASR → 翻译 → 字幕生成 → 嵌入视频
```

---

## 三、已确认可用的数据集来源

| 类型 | 来源 | 内容 | 状态 |
|------|------|------|------|
| 音频+日文文本 | HF v2 (joujiboi/japanese-anime-speech-v2) | 200 条动漫风格语音，5-10 秒/条 | ✅ 已下载 |
| 日文字幕（完整） | Kitsunekko GitHub 镜像 | 数千部动漫的 SRT/ASS 字幕 | ⏳ 克隆中 |
| 日文字幕（单部） | Kitsunekko 网站 | 单部动漫字幕，几十 KB | ✅ 可随时下载 |
| 日中双语 | HF ScreenTalk_JA2ZH | 日语音频+中文翻译 | 📝 未下载 |
| 中文字幕 | HF Anime_subtitles_CN | 4000 条动漫中文字幕 | 📝 未下载 |

---

## 四、动漫视频下载来源

| 来源 | 网址 | 说明 |
|------|------|------|
| **ACG FTA** | https://acgfta.com/ | 在线观看/下载，视频为 m3u8 格式，可用 yt-dlp 下载 |
| **Nyaa** | https://nyaa.si/ | 种子网站，需 BT 软件，资源最全 |
| **Internet Archive** | https://archive.org/ | 免费公有领域动漫，直链下载，国内被墙 |

### 使用 yt-dlp 从 ACG FTA 下载

1. 打开动漫播放页（如 https://acgfta.com/play/4551-7-1.html）
2. 页面源码的 `player_aaaa` 变量中有 `"url":"...m3u8"` 字段
3. 提取该 m3u8 链接，用 yt-dlp 下载：
   ```bash
   yt-dlp "https://play.modujx10.com/20230909/xxx/index.m3u8"
   ```

或者在项目根目录运行写好的脚本：
```bash
.venv\Scripts\python scripts\dl_k-on_full.py
```

---

## 五、数据目录结构

```
data/
├── test/                        # ASR 测试数据（已就绪）
│   ├── manifest.json            # 200 条音频-文本对照表
│   ├── sample_0000.wav ~ 0199   # 200 个 WAV 音频文件
│   └── sfw-00000.parquet        # 原始 parquet 数据
│
├── subtitles/                   # Kitsunekko 字幕（克隆中）
│   └── Bakemonogatari/          # 示例
│       ├── [MTBB] ... 01.jp.srt
│       └── ...
│
└── kitsunekko/                  # 完整 Git 镜像（克隆中）

---

## 七、各阶段测试数据需求清单

| Sprint | 阶段名称 | 需要的数据 | 已有？ | 还缺什么 |
|--------|---------|-----------|--------|---------|
| S1-S2 | 参考项目评估 | 视频文件 | ✅ K-On! 14 集 | 无 |
| S3-S4 | ASR 评估 | 日语音频 + 日文文本 | ✅ HF 200 条 + K-On! 各集 | 无 |
| S5 | 音频分离 | 带 BGM 的音频 | ✅ K-On! 有大量音乐场景 | 无 |
| S6 | 说话人分离 | 多人对话音频 + 角色标签 | ✅ K-On! 有多个角色 | &#x26A0; 缺少人工标注的说话人标签 |
| S7 | OP/ED 检测 | 带 OP/ED 的动漫视频 | ✅ K-On! 有 OP/ED | 无 |
| **S8-S9** | **翻译评估** | **日文&#x2192;中文参考翻译** | **&#x274C; 没有参考译文** | **需要日中双语平行语料** |
| S10 | 字幕生成 | 日文字幕 + 中文字幕参考 | ✅ 日文字幕有 | &#x274C; 中文参考译文 |
| S11 | 质量审查 | 同上 | 同上 | 同上 |
| S12-S16 | 工程域 | 依赖前面阶段产出 | — | — |

### 翻译评估数据补缺方案

| 候选来源 | 说明 | 推荐度 |
|---------|------|--------|
| **人人影视字幕**（HF 600K 条） | 中英/中日双语字幕，HF 可直接加载 | ⭐ 首选 |
| **WCC-JC 2.0** | 日中平行语料 140 万句，但只公开了 20 万 demo | ⭐⭐ 备选 |
| **ScreenTalk_JA2ZH** | 日语音频 + 中文翻译 | ⭐⭐ 备选 |
| **手动标注** | 从 K-On! 第 1 集挑 50 句手动翻译 | ⭐ 最简单但费人工 |
```