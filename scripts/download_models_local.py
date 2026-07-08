"""
Anime Accurate Sub - 模型下载脚本（本机 Windows）
RTX 3060 12GB

用法: python scripts/download_models_local.py
"""

import subprocess
import sys
import os
from pathlib import Path

# 代理设置
os.environ["HTTP_PROXY"] = "http://127.0.0.1:7890"
os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"

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
    print("  Anime Accurate Sub — 模型下载（本机）")
    print("  RTX 3060 12GB")
    print("=" * 50)

    # ========== 1. Ollama 模型 ==========
    print("\n--- 1/4: Ollama 模型 ---")

    ollama_models = [
        ("EasonONLINE/Sakura-qwen2.5-v1.0:7b", "Sakura-7B-Qwen2.5-v1.0（翻译主力 6.3GB）"),
        ("crosery/GalTransl-7B-v2.6:IQ4_XS", "GalTransl-7B-v2.6（视觉小说翻译备选 4.3GB）"),
        ("qwen2.5:7b", "Qwen2.5:7b（Apache 2.0 备用 ~4.3GB）"),
    ]

    for model, desc in ollama_models:
        run(["ollama", "pull", model], desc)

    # ========== 2. HuggingFace 模型 ==========
    print("\n--- 2/4: HuggingFace 模型 ---")

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
    print("  ✅ 本机模型下载完成！")
    print()
    print("  已下载：")
    print("    - Sakura-7B-Qwen2.5-v1.0")
    print("    - GalTransl-7B-v2.6")
    print("    - Qwen2.5:7b")
    print("    - Anime Whisper (HuggingFace)")
    print()
    print("  如需 Sakura-14B，请在服务器运行 download_models_server.py")
    print("=" * 50)


if __name__ == "__main__":
    main()