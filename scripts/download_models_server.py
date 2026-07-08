"""
Anime Accurate Sub - 模型下载脚本（服务器 Linux）
2x NVIDIA RTX 4090 (20GB each)

用法: python3 scripts/download_models_server.py
"""

import subprocess
import sys
import os
from pathlib import Path

# 如果服务器需要代理，取消注释以下两行
# os.environ["HTTP_PROXY"] = "http://127.0.0.1:7890"
# os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"

# Ollama 多卡支持：默认自动使用所有可用 GPU
os.environ["CUDA_VISIBLE_DEVICES"] = "0,1"

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"


def run(cmd: list[str], desc: str):
    print(f"\n[{desc}]")
    print(f"    命令: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"    ❌ 失败 (exit code {result.returncode})")
        sys.exit(1)
    print(f"    ✅ 完成")


def main():
    print("=" * 50)
    print("  Anime Accurate Sub — 模型下载（服务器）")
    print("  2x RTX 4090 (20GB each)")
    print("=" * 50)

    # ========== 1. Ollama 模型 ==========
    print("\n--- 1/5: Ollama 模型 ---")

    ollama_models = [
        ("crosery/sakura-14b-qwen2.5-v1.0-q6k",
         "Sakura-14B Q6_K（翻译主力高配版 ~12GB，多卡自动支持）"),
        ("EasonONLINE/Sakura-qwen2.5-v1.0:7b",
         "Sakura-7B-Qwen2.5-v1.0（翻译主力轻量版 6.3GB）"),
        ("crosery/GalTransl-7B-v2.6:Q6_k",
         "GalTransl-7B-v2.6（视觉小说翻译备选 6.3GB）"),
        ("qwen2.5:7b",
         "Qwen2.5:7b（Apache 2.0 备用 ~4.3GB）"),
        ("qwen2.5:14b",
         "Qwen2.5:14b（中档翻译备选 ~9GB）"),
    ]

    for model, desc in ollama_models:
        run(["ollama", "pull", model], desc)

    # ========== 2. HuggingFace 模型 ==========
    print("\n--- 2/5: HuggingFace 模型 ---")

    print("\n[Anime Whisper] 下载 ASR 主力模型 litagin/anime-whisper")
    try:
        from huggingface_hub import snapshot_download
        model_dir = str(MODELS_DIR / "anime-whisper")
        print(f"    目标路径: {model_dir}")
        snapshot_download("litagin/anime-whisper", local_dir=model_dir)
        print("    ✅ 下载完成")
    except ImportError:
        print("    ⚠️  huggingface_hub 未安装，尝试 pip install")
        run([sys.executable, "-m", "pip", "install", "huggingface_hub"],
            "安装 huggingface_hub")
        from huggingface_hub import snapshot_download
        model_dir = str(MODELS_DIR / "anime-whisper")
        print(f"    目标路径: {model_dir}")
        snapshot_download("litagin/anime-whisper", local_dir=model_dir)
        print("    ✅ 下载完成")

    print("\n" + "=" * 50)
    print("  ✅ 服务器模型下载完成！")
    print()
    print("  已下载：")
    print("    - Sakura-14B-Qwen2.5-v1.0 (Q6_K)")
    print("    - Sakura-7B-Qwen2.5-v1.0")
    print("    - GalTransl-7B-v2.6")
    print("    - Qwen2.5:7b")
    print("    - Qwen2.5:14b")
    print("    - Anime Whisper (HuggingFace)")
    print()
    print("  Ollama 多卡说明：默认使用 CUDA_VISIBLE_DEVICES=0,1")
    print("  如需调整，运行前 export CUDA_VISIBLE_DEVICES=0 即可")
    print("=" * 50)


if __name__ == "__main__":
    main()