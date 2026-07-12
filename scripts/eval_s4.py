"""
S4.1 ASR 备选评估 + AED 测试
测试 SenseVoice Small 和 efwkjn/whisper-ja-anime-v0.3
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from jiwer import cer

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

TEST_DATA_DIR = project_root / "data" / "test"
MANIFEST_PATH = TEST_DATA_DIR / "manifest.json"
RESULTS_DIR = project_root / "docs" / "evaluation"
MODEL_DIR = project_root / ".omo"


def load_samples():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    samples = []
    for item in manifest:
        ap = TEST_DATA_DIR / item["audio_file"]
        if ap.exists():
            samples.append({"audio_path": str(ap), "reference": item["transcription"]})
    print(f"Loaded {len(samples)} samples")
    return samples


def normalize_text(text):
    import re
    return re.sub(r'\s+', '', text).strip()


def test_efwkjn_model(samples):
    """Test efwkjn/whisper-ja-anime-v0.3 via faster-whisper"""
    from faster_whisper import WhisperModel

    model_path = str(MODEL_DIR / "efwkjn-anime-whisper")
    if not os.path.exists(os.path.join(model_path, "model.bin")):
        print("efwkjn model not fully downloaded, skipping...")
        return None

    print(f"\n{'='*60}")
    print(f"Testing efwkjn/whisper-ja-anime-v0.3")
    print(f"{'='*60}")

    t0 = time.time()
    model = WhisperModel(model_path, device="cuda", compute_type="int8_float16")
    load_time = time.time() - t0
    print(f"  Loaded in {load_time:.1f}s")

    results = []
    total_asr = 0.0
    total_audio = 0.0

    for i, s in enumerate(samples):
        asr_start = time.time()
        segments, info = model.transcribe(s["audio_path"], language="ja",
                                          beam_size=5, vad_filter=False)
        text = " ".join([seg.text.strip() for seg in segments])
        asr_time = time.time() - asr_start
        duration = info.duration if info and info.duration else 0
        total_asr += asr_time
        total_audio += duration
        cer_score = cer(normalize_text(s["reference"]), normalize_text(text))
        results.append({"sample": os.path.basename(s["audio_path"]),
                        "reference": s["reference"], "transcription": text,
                        "cer": cer_score, "asr_time": asr_time, "audio_duration": duration})
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(samples)}, avg CER={np.mean([r['cer'] for r in results]):.4f}")

    cers = [r["cer"] for r in results]
    summary = {
        "model": "efwkjn/whisper-ja-anime-v0.3",
        "compute_type": "int8_float16",
        "samples": len(results),
        "load_time_s": round(load_time, 2),
        "total_asr_s": round(total_asr, 2),
        "total_audio_s": round(total_audio, 2),
        "rtf": round(total_asr / total_audio, 4) if total_audio > 0 else 0,
        "avg_cer": round(float(np.mean(cers)), 4),
        "median_cer": round(float(np.median(cers)), 4),
        "p90_cer": round(float(np.percentile(cers, 90)), 4),
    }
    print(f"  Avg CER: {summary['avg_cer']:.4f}  Med CER: {summary['median_cer']:.4f}  RTF: {summary['rtf']:.4f}")
    return summary


def test_sensevoice_small(samples):
    """Test SenseVoice Small via funasr"""
    import torch
    from funasr import AutoModel

    print(f"\n{'='*60}")
    print(f"Testing SenseVoice Small")
    print(f"{'='*60}")

    t0 = time.time()
    model = AutoModel(
        model="iic/SenseVoiceSmall",
        vad_model="iic/speech_fsmn_vad_zh-cn",
        vad_kwargs={"max_single_segment_time": 30000},
        device="cuda:0",
        disable_update=True,
    )
    load_time = time.time() - t0
    print(f"  Loaded in {load_time:.1f}s")

    results = []
    total_asr = 0.0
    total_audio = 0.0

    for i, s in enumerate(samples):
        asr_start = time.time()
        try:
            res = model.generate(
                input=s["audio_path"],
                language="ja",
                use_itn=True,
                batch_size_s=0,
            )
            text = ""
            if res and isinstance(res, list) and len(res) > 0:
                if isinstance(res[0], dict):
                    text = res[0].get("text", "")
                else:
                    text = str(res[0])
            # Clean text
            text = text.strip()
        except Exception as e:
            text = f"<ERROR: {e}>"

        asr_time = time.time() - asr_start
        # Get audio duration from file
        duration = 0
        try:
            import soundfile as sf
            data, sr = sf.read(s["audio_path"])
            duration = len(data) / sr
        except:
            pass

        total_asr += asr_time
        total_audio += duration
        cer_score = cer(normalize_text(s["reference"]), normalize_text(text)) if text and not text.startswith("<ERROR") else 1.0
        results.append({"sample": os.path.basename(s["audio_path"]),
                        "reference": s["reference"], "transcription": text,
                        "cer": cer_score, "asr_time": asr_time, "audio_duration": duration})
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(samples)}, avg CER={np.mean([r['cer'] for r in results]):.4f}")

    cers = [r["cer"] for r in results]
    summary = {
        "model": "SenseVoice Small",
        "samples": len(results),
        "load_time_s": round(load_time, 2),
        "total_asr_s": round(total_asr, 2),
        "total_audio_s": round(total_audio, 2),
        "rtf": round(total_asr / total_audio, 4) if total_audio > 0 else 0,
        "avg_cer": round(float(np.mean(cers)), 4),
        "median_cer": round(float(np.median(cers)), 4),
        "p90_cer": round(float(np.percentile(cers, 90)), 4),
    }
    print(f"  Avg CER: {summary['avg_cer']:.4f}  Med CER: {summary['median_cer']:.4f}  RTF: {summary['rtf']:.4f}")
    return summary


def test_sensevoice_aed():
    """Test SenseVoice AED (Audio Event Detection) for OP/ED detection"""
    from funasr import AutoModel
    import torch

    print(f"\n{'='*60}")
    print(f"Testing SenseVoice AED (Audio Event Detection)")
    print(f"{'='*60}")

    t0 = time.time()
    model = AutoModel(
        model="iic/SenseVoiceSmall",
        device="cuda:0",
        disable_update=True,
    )
    print(f"  Loaded in {time.time() - t0:.1f}s")

    # Test with a few sample clips
    test_files = []
    for i in range(5):
        test_files.append(str(TEST_DATA_DIR / f"sample_{i:04d}.wav"))

    results = []
    for f in test_files:
        if not os.path.exists(f):
            continue
        res = model.generate(input=f, language="auto", use_itn=True)
        text = ""
        if res and isinstance(res, list) and len(res) > 0:
            if isinstance(res[0], dict):
                text = res[0].get("text", str(res[0]))
            else:
                text = str(res[0])
        results.append({"file": os.path.basename(f), "raw_output": text[:200]})
        print(f"  {os.path.basename(f)}: {text[:100]}")

    return results


def generate_report(efwkjn_result, sv_result, aed_results):
    report_path = RESULTS_DIR / "S4.1_Alternative_ASR_Evaluation.md"

    # Load baseline (Anime Whisper from S3)
    baseline_path = RESULTS_DIR / "S3.1_results_anime-whisper.json"
    baseline = None
    if baseline_path.exists():
        with open(baseline_path) as f:
            baseline = json.load(f)

    lines = []
    lines.append("# S4.1 ASR 备选评估 + AED 测试报告")
    lines.append(f"> 日期: 2026-07-11")
    lines.append(f"> 测试集: 200 条日语语音片段")
    lines.append(f"> 环境: Python 3.13 + torch 2.11.0+cu128, RTX 3060 12GB")
    lines.append("")

    lines.append("## 三模型对比")
    lines.append("")
    lines.append("| 模型 | Avg CER | Med CER | RTF | 大小 | 特点 |")
    lines.append("|------|:-------:|:-------:|:---:|:----:|------|")

    models = []
    if baseline:
        models.append(("Anime Whisper (主力)", baseline.get("avg_cer", "?"), baseline.get("median_cer", "?"), baseline.get("real_time_factor", "?"), "1.5GB", "kotoba-whisper v2.0 蒸馏版, 5,300h Galgame 微调"))
    if efwkjn_result:
        models.append(("efwkjn/whisper-ja-anime-v0.3", efwkjn_result["avg_cer"], efwkjn_result["median_cer"], efwkjn_result["rtf"], "~1.5GB", "large-v3-turbo 微调, 日语 tokenizer"))
    if sv_result:
        models.append(("SenseVoice Small", sv_result["avg_cer"], sv_result["median_cer"], sv_result["rtf"], "~936MB", "非 Whisper 架构, 多语言 + AED"))

    for name, avg, med, rtf, size, note in models:
        lines.append(f"| {name} | {avg} | {med} | {rtf} | {size} | {note} |")

    lines.append("")
    lines.append("## 详细分析")
    lines.append("")

    if efwkjn_result:
        lines.append("### efwkjn/whisper-ja-anime-v0.3")
        lines.append("")
        lines.append(f"- Avg CER: {efwkjn_result['avg_cer']:.4f}")
        lines.append(f"- Med CER: {efwkjn_result['median_cer']:.4f}")
        lines.append(f"- RTF: {efwkjn_result['rtf']:.4f}")
        if baseline:
            cer_change = (efwkjn_result['avg_cer'] / baseline['avg_cer'] - 1) * 100
            lines.append(f"- vs Anime Whisper: CER {cer_change:+.1f}%")
        lines.append("")

    if sv_result:
        lines.append("### SenseVoice Small")
        lines.append("")
        lines.append(f"- Avg CER: {sv_result['avg_cer']:.4f}")
        lines.append(f"- Med CER: {sv_result['median_cer']:.4f}")
        lines.append(f"- RTF: {sv_result['rtf']:.4f}")
        if baseline:
            cer_change = (sv_result['avg_cer'] / baseline['avg_cer'] - 1) * 100
            lines.append(f"- vs Anime Whisper: CER {cer_change:+.1f}%")
        lines.append("")

    lines.append("### SenseVoice AED (音频事件检测)")
    lines.append("")
    lines.append("SenseVoice Small 内置 AED 能力，可检测 BGM/Speech/Music 等事件类别。")
    lines.append("测试结果：")
    lines.append("")
    if aed_results:
        for r in aed_results:
            lines.append(f"- {r['file']}: `{r['raw_output']}`")
    else:
        lines.append("- AED 测试未完成")
    lines.append("")

    lines.append("## 结论")
    lines.append("")
    lines.append("### ASR 选型建议")
    lines.append("")
    if baseline and efwkjn_result:
        if efwkjn_result['avg_cer'] < baseline['avg_cer']:
            lines.append("efwkjn/whisper-ja-anime-v0.3 精度优于当前主力，建议升级。")
        else:
            lines.append("当前主力 Anime Whisper 仍然是最优选择。")
    lines.append("")
    lines.append("### SenseVoice 定位")
    lines.append("")
    lines.append("SenseVoice 可作为快速通道（低延迟场景）或音频事件检测模块使用。")
    lines.append("")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nReport: {report_path}")


if __name__ == "__main__":
    samples = load_samples()

    # Test efwkjn model
    efwkjn_result = test_efwkjn_model(samples)

    # Test SenseVoice (uses AnimeTranslator venv)
    sv_result = None
    sv_aed = None
    try:
        sv_result = test_sensevoice_small(samples)
        sv_aed = test_sensevoice_aed()
    except Exception as e:
        print(f"SenseVoice error: {e}")
        import traceback
        traceback.print_exc()

    generate_report(efwkjn_result, sv_result, sv_aed)