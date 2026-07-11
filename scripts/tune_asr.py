"""
S3.2 Faster-Whisper 推理优化
测试不同 compute_type / batch_size / VAD 配置下的 CER 和 RTF
"""
import json
import os
import sys
import time
import argparse
from pathlib import Path

import numpy as np
from jiwer import cer

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

TEST_DATA_DIR = project_root / "data" / "test"
MANIFEST_PATH = TEST_DATA_DIR / "manifest.json"
MODEL_PATH = project_root / ".omo" / "anime-whisper-ct2"
RESULTS_DIR = project_root / "docs" / "evaluation"

# All configurations to test
CONFIGS = [
    # (compute_type, batch_size, vad, label)
    ("float16",      1,  True,  "float16_b1_vad"),      # baseline
    ("int8_float16", 1,  True,  "int8f16_b1_vad"),
    ("int8",         1,  True,  "int8_b1_vad"),
    ("float16",      8,  True,  "float16_b8_vad"),
    ("int8_float16", 8,  True,  "int8f16_b8_vad"),
    ("float16",      1,  False, "float16_b1_novad"),
    ("int8_float16", 8,  False, "int8f16_b8_novad"),
]


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


def test_config(config, samples):
    from faster_whisper import WhisperModel
    from faster_whisper.transcribe import BatchedInferencePipeline

    compute_type, batch_size, vad, label = config
    print(f"\n{'='*60}")
    print(f"Config: {label}")
    print(f"  compute_type={compute_type}, batch_size={batch_size}, VAD={vad}")
    print(f"{'='*60}")

    t0 = time.time()
    model = WhisperModel(str(MODEL_PATH), device="cuda", compute_type=compute_type)
    load_time = time.time() - t0
    print(f"  Loaded in {load_time:.1f}s")

    # Use batched pipeline when batch_size > 1
    if batch_size > 1:
        transcriber = BatchedInferencePipeline(model=model)
        use_batched = True
    else:
        transcriber = model
        use_batched = False

    results = []
    total_asr = 0.0
    total_audio = 0.0

    for i, sample in enumerate(samples):
        ap = sample["audio_path"]
        ref = sample["reference"]

        asr_start = time.time()

        if use_batched:
            segments, info = transcriber.transcribe(
                ap, batch_size=batch_size,
                language="ja", beam_size=5,
                vad_filter=vad,
            )
        else:
            segments, info = transcriber.transcribe(
                ap, language="ja", beam_size=5,
                vad_filter=vad,
                vad_parameters=dict(min_silence_duration_ms=500) if vad else None,
            )

        text = " ".join([s.text.strip() for s in segments])
        asr_time = time.time() - asr_start
        duration = info.duration if info and info.duration else 0
        total_asr += asr_time
        total_audio += duration
        cer_score = cer(normalize_text(ref), normalize_text(text))

        results.append({
            "sample": os.path.basename(ap), "reference": ref,
            "transcription": text, "cer": cer_score,
            "asr_time": asr_time, "audio_duration": duration,
        })

        if (i + 1) % 50 == 0:
            avg_c = np.mean([r["cer"] for r in results])
            print(f"  {i+1}/{len(samples)}, avg CER={avg_c:.4f}")

    cers = [r["cer"] for r in results]
    avg_cer = float(np.mean(cers))
    median_cer = float(np.median(cers))
    p90_cer = float(np.percentile(cers, 90))
    rtf = total_asr / total_audio if total_audio > 0 else 0

    summary = {
        "label": label,
        "compute_type": compute_type,
        "batch_size": batch_size,
        "vad": vad,
        "model": str(MODEL_PATH),
        "samples": len(results),
        "load_time_s": load_time,
        "total_asr_s": total_asr,
        "total_audio_s": total_audio,
        "rtf": round(rtf, 4),
        "avg_cer": round(avg_cer, 4),
        "median_cer": round(median_cer, 4),
        "p90_cer": round(p90_cer, 4),
    }

    print(f"\n  Avg CER: {avg_cer:.4f}  Med CER: {median_cer:.4f}  RTF: {rtf:.4f}")
    return summary, results


def generate_report(all_results):
    report_path = RESULTS_DIR / "S3.2_Inference_Optimization.md"
    baseline = [r for r in all_results if r["label"] == "float16_b1_vad"]
    bl = baseline[0] if baseline else None

    lines = []
    lines.append("# S3.2 Faster-Whisper 推理优化报告")
    lines.append(f"> 日期: 2026-07-11")
    lines.append(f"> 模型: Anime Whisper (quantumcookie/anime-whisper-ct2-fp16)")
    lines.append(f"> 测试集: {all_results[0]['samples']} 条日语语音片段 ({all_results[0]['total_audio_s']:.0f}s)")
    lines.append(f"> 环境: Python 3.13 + torch 2.11.0+cu128, RTX 3060 12GB")
    lines.append("")
    lines.append("## 结果对比")
    lines.append("")
    lines.append("| # | 配置 | compute_type | batch | VAD | Avg CER | Med CER | RTF | vs 基线 |")
    lines.append("|---|------|-------------|:-----:|:---:|:-------:|:-------:|:---:|:-------:|")
    for i, r in enumerate(all_results):
        label = r["label"]
        ct = r["compute_type"]
        bs = r["batch_size"]
        vad = "ON" if r["vad"] else "OFF"
        avg_c = f"{r['avg_cer']:.4f}"
        med_c = f"{r['median_cer']:.4f}"
        rtf = f"{r['rtf']:.4f}"
        if bl and r["label"] != "float16_b1_vad":
            speedup = (bl["rtf"] / r["rtf"] - 1) * 100
            change = f"RTF {speedup:+.0f}%"
        else:
            change = "baseline"
        lines.append(f"| {i+1} | {label} | {ct} | {bs} | {vad} | {avg_c} | {med_c} | {rtf} | {change} |")

    lines.append("")
    lines.append("## 详细分析")
    lines.append("")

    # Find best configs
    best_cer = min(all_results, key=lambda r: r["avg_cer"])
    best_rtf = min(all_results, key=lambda r: r["rtf"])
    best_tradeoff = min(all_results, key=lambda r: r["rtf"] * (1 + r["avg_cer"]))

    lines.append("### 最优精度配置")
    lines.append(f"- **{best_cer['label']}**: Avg CER={best_cer['avg_cer']:.4f}, RTF={best_cer['rtf']:.4f}")
    lines.append("")
    lines.append("### 最优速度配置")
    lines.append(f"- **{best_rtf['label']}**: RTF={best_rtf['rtf']:.4f}, Avg CER={best_rtf['avg_cer']:.4f}")
    lines.append("")
    lines.append("### 最优均衡配置")
    lines.append(f"- **{best_tradeoff['label']}**: RTF={best_tradeoff['rtf']:.4f}, Avg CER={best_tradeoff['avg_cer']:.4f}")
    lines.append("")

    # Quantization analysis
    lines.append("### 量化影响")
    lines.append("")
    lines.append("| 量化 | batch=1 VAD=on | vs baseline |")
    lines.append("|------|:--------------:|:-----------:|")
    for ct in ["float16", "int8_float16", "int8"]:
        r = next((x for x in all_results if x["compute_type"] == ct and x["batch_size"] == 1 and x["vad"]), None)
        if r and bl:
            cer_d = (r['avg_cer'] / bl['avg_cer'] - 1) * 100
            rtf_d = (bl["rtf"] / r["rtf"] - 1) * 100
            lines.append(f"| {ct} | CER={r['avg_cer']:.4f} RTF={r['rtf']:.4f} | CER {cer_d:+.1f}% RTF {rtf_d:+.0f}% |")

    lines.append("")
    lines.append("### VAD 影响")
    lines.append("")
    vad_on = next((x for x in all_results if x["compute_type"] == "float16" and x["batch_size"] == 1 and x["vad"]), None)
    vad_off = next((x for x in all_results if x["compute_type"] == "float16" and x["batch_size"] == 1 and not x["vad"]), None)
    if vad_on and vad_off:
        lines.append(f"- VAD ON:  CER={vad_on['avg_cer']:.4f}  RTF={vad_on['rtf']:.4f}")
        lines.append(f"- VAD OFF: CER={vad_off['avg_cer']:.4f}  RTF={vad_off['rtf']:.4f}")
        lines.append("")

    lines.append("### BatchedInferencePipeline 影响")
    lines.append("")
    for ct in ["float16", "int8_float16"]:
        b1 = next((x for x in all_results if x["compute_type"] == ct and x["batch_size"] == 1 and x["vad"]), None)
        b8 = next((x for x in all_results if x["compute_type"] == ct and x["batch_size"] == 8 and x["vad"]), None)
        if b1 and b8:
            speedup = (b1["rtf"] / b8["rtf"] - 1) * 100
            lines.append(f"- {ct}: batch=1 RTF={b1['rtf']:.4f} → batch=8 RTF={b8['rtf']:.4f} (快 {speedup:.0f}%)")

    lines.append("")
    lines.append("## 推荐配置")
    lines.append("")
    lines.append(f"**生产环境推荐**: {best_tradeoff['label']}")
    lines.append(f"- compute_type={best_tradeoff['compute_type']}")
    lines.append(f"- batch_size={best_tradeoff['batch_size']}")
    lines.append(f"- VAD={'ON' if best_tradeoff['vad'] else 'OFF'}")
    lines.append(f"- RTF={best_tradeoff['rtf']:.4f} | Avg CER={best_tradeoff['avg_cer']:.4f}")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nReport: {report_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--configs", default="all", help="Config to run (label) or 'all'")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    if args.report_only:
        # Load saved results
        all_summaries = []
        for c in CONFIGS:
            result_file = RESULTS_DIR / f"S3.2_results_{c[3]}.json"
            if result_file.exists():
                with open(result_file) as f:
                    all_summaries.append(json.load(f))
        if all_summaries:
            generate_report(all_summaries)
        else:
            print("No results found")
        return

    samples = load_samples()
    all_summaries = []

    for config in CONFIGS:
        label = config[3]
        result_file = RESULTS_DIR / f"S3.2_results_{label}.json"
        if result_file.exists() and args.configs != label:
            with open(result_file) as f:
                all_summaries.append(json.load(f))
            print(f"Config {label}: using cached results")
            continue

        if args.configs != "all" and args.configs != label:
            continue

        summary, results = test_config(config, samples)
        all_summaries.append(summary)

        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"  Saved: {result_file}")

    generate_report(all_summaries)


if __name__ == "__main__":
    main()