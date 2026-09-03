"""
Anime Whisper 模型下载脚本

从 HuggingFace 镜像下载 quantumcookie/anime-whisper-ct2-fp16。
如果网络正常，会自动续传之前未完成的下载。

用法:
  uv pip install huggingface-hub
  python scripts/download_anime_whisper.py
"""

import os
import sys
import time

# ===== 配置 =====
MODEL_NAME = "quantumcookie/anime-whisper-ct2-fp16"
"""目标模型名"""

# HF 镜像（国内可用）
HF_ENDPOINT = "https://hf-mirror.com"
# 缓存目录
CACHE_DIR = os.path.expanduser("~/.cache/huggingface/hub")
# 本地 fallback 目录（如果下载失败就用这个）
LOCAL_MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", ".omo", "anime-whisper-ct2")


def download_model():
    """使用 huggingface_hub 下载完整模型"""
    # 设置环境
    os.environ["HF_ENDPOINT"] = HF_ENDPOINT
    # 取消所有代理（hf-mirror 直连即可）
    for k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
        os.environ.pop(k, None)

    # 确保 huggingface_hub 已安装
    try:
        import huggingface_hub
        print(f"huggingface_hub 版本: {huggingface_hub.__version__}")
    except ImportError:
        print("请先安装: uv pip install huggingface-hub")
        sys.exit(1)

    from huggingface_hub import snapshot_download

    print(f"下载模型: {MODEL_NAME}")
    print(f"镜像: {HF_ENDPOINT}")
    print(f"缓存目录: {CACHE_DIR}")

    start = time.time()
    try:
        path = snapshot_download(
            MODEL_NAME,
            local_files_only=False,
            max_workers=4,
        )
        elapsed = time.time() - start
        print(f"\n✅ 下载完成!")
        print(f"   路径: {path}")
        print(f"   用时: {elapsed:.1f}s")

        # 验证文件完整性
        required = ["model.bin", "config.json", "tokenizer.json", "vocabulary.json", "preprocessor_config.json"]
        missing = [f for f in required if not os.path.exists(os.path.join(path, f))]
        if missing:
            print(f"⚠️  缺失文件: {missing}")
            print(f"   下载可能不完整，请检查网络后重试")
            return False
        else:
            print(f"✅ 全部 {len(required)} 个必要文件完整")
            return True

    except Exception as e:
        elapsed = time.time() - start
        print(f"\n❌ 下载失败 ({elapsed:.1f}s): {e}")
        print(f"   错误类型: {type(e).__name__}")
        return False


def verify_local_model():
    """检查本地已下载的 fallback 模型文件"""
    import json

    model_dir = os.path.abspath(LOCAL_MODEL_DIR)
    if not os.path.exists(model_dir):
        print(f"本地模型目录不存在: {model_dir}")
        return False

    print(f"\n检查本地模型: {model_dir}")

    required = ["model.bin", "config.json", "tokenizer.json", "vocabulary.json", "preprocessor_config.json"]
    results = {}
    all_ok = True

    for f in required:
        path = os.path.join(model_dir, f)
        if os.path.exists(path):
            size = os.path.getsize(path)
            if size > 0:
                results[f] = f"✅ ({size / 1e6:.1f} MB)" if size > 1e6 else f"✅ ({size / 1e3:.1f} KB)"
            else:
                results[f] = "❌ (空文件)"
                all_ok = False
        else:
            results[f] = "❌ (缺失)"
            all_ok = False

    for name, status in results.items():
        print(f"  {name}: {status}")

    if all_ok:
        print(f"\n✅ 本地模型完整，可以直接使用:")
        print(f"   WhisperModel(r\"{model_dir}\", device=\"cuda\", compute_type=\"float16\")")
    else:
        print(f"\n⚠️  本地模型不完整，需要重新下载")

    return all_ok


def main():
    print("=" * 60)
    print("Anime Whisper 模型下载工具")
    print(f"模型: {MODEL_NAME}")
    print("=" * 60)

    # 先检查本地已有文件
    verify_local_model()

    print("\n--- 开始从 HuggingFace 下载完整模型 ---")
    success = download_model()

    if success:
        print("\n🎉 模型下载完成！现在可以直接使用:")
        print(f"  from faster_whisper import WhisperModel")
        print(f"  model = WhisperModel(\"{MODEL_NAME}\", device=\"cuda\", compute_type=\"float16\")")
        print()
        print(f"  或运行评测:")
        print(f"  python scripts/eval_asr.py --model {MODEL_NAME} --output docs/evaluation/S3.1_results_anime-whisper.json")
    else:
        print("\n⚠️  下载未完成。当前已下载的文件可用作 fallback:")
        verify_local_model()


if __name__ == "__main__":
    main()