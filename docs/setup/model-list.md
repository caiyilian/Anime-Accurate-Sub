# 模型下载清单

> 所有需要下载的模型，按部署位置分类

---

## 本机（RTX 3060 12GB）

| 模型 | Ollama 名称 | 大小 | 用途 | 优先度 |
|------|------------|------|------|--------|
| Sakura-7B-Qwen2.5-v1.0 | `EasonONLINE/Sakura-qwen2.5-v1.0:7b` | 6.3GB | 翻译主力 | ⭐ 必下 |
| GalTransl-7B-v2.6 | `crosery/GalTransl-7B-v2.6:IQ4_XS` | 4.3GB | 翻译备选（视觉小说风格） | ⭐ 必下 |
| Qwen2.5:7b | `qwen2.5:7b` | ~4.3GB | 翻译备用（Apache 2.0 许可证） | ⭐ 必下 |
| Anime Whisper | HuggingFace: `litagin/anime-whisper` | ~3GB | ASR 主力 | 可稍后下载 |

> **下载命令**（开 CMD 窗口逐条执行）：
> ```cmd
> ollama pull EasonONLINE/Sakura-qwen2.5-v1.0:7b
> ollama pull crosery/GalTransl-7B-v2.6:IQ4_XS
> ollama pull qwen2.5:7b
> ```

---

## 服务器（2x RTX 4090，各 20GB）

| 模型 | Ollama 名称 | 大小 | 用途 | 优先度 |
|------|------------|------|------|--------|
| Sakura-14B-Qwen2.5-v1.0 (Q6_K) | `crosery/sakura-14b-qwen2.5-v1.0-q6k` | 12GB | 翻译主力高配版 | ⭐ 必下 |
| Sakura-7B-Qwen2.5-v1.0 | `EasonONLINE/Sakura-qwen2.5-v1.0:7b` | 6.3GB | 翻译备选 | 可选 |
| GalTransl-7B-v2.6 | `crosery/GalTransl-7B-v2.6:Q6_k` | 6.3GB | 翻译备选 | 可选 |
| Qwen2.5:7b | `qwen2.5:7b` | ~4.3GB | 备用翻译（Apache 2.0） | ⭐ 推荐 |
| Qwen2.5:14b | `qwen2.5:14b` | ~9GB | 中档备选翻译 | 可选 |
| Anime Whisper | HuggingFace: `litagin/anime-whisper` | ~3GB | ASR 主力 | 可稍后下载 |

> **下载命令**（开终端逐条执行）：
> ```bash
> ollama pull crosery/sakura-14b-qwen2.5-v1.0-q6k
> ollama pull EasonONLINE/Sakura-qwen2.5-v1.0:7b
> ollama pull crosery/GalTransl-7B-v2.6:Q6_k
> ollama pull qwen2.5:7b
> ollama pull qwen2.5:14b
> ```

---

## 非 Ollama 模型

| 模型 | 来源 | 大小 | 下载方式 |
|------|------|------|---------|
| Anime Whisper | HuggingFace: `litagin/anime-whisper` | ~3GB | 后续通过 Python 脚本下载 |

---

## 环境确认

| 项目 | 值 |
|------|-----|
| Python | 3.13.3 |
| PyTorch | 2.12.1+cu126 |
| CUDA | 12.6（torch 自带） / 12.9（驱动支持） |
| GPU | RTX 3060 12GB（本机） / 2x RTX 4090 20GB（服务器） |