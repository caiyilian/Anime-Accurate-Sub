"""
S3.1 ASR 主力评估脚本
比较 faster-whisper large-v3-turbo 与 Anime Whisper 社区模型在日语动漫语音上的 CER

用法:
  # 测试 large-v3-turbo 基线
  python scripts/eval_asr.py --model large-v3-turbo --output docs/evaluation/S3.1_results_large-v3-turbo.json
  
  # 测试 Anime Whisper (需要先转换CT2格式)
  python scripts/eval_asr.py --model efwkjn/whisper-ja-anime-v0.3 --output docs/evaluation/S3.1_results_anime-whisper.json
  
  # 生成报告
  python scripts/eval_asr.py --report
"""

import json
import os
import sys
import time
import argparse
from pathlib import Path

import numpy as np
from jiwer import cer, wer

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Gold standard test set
TEST_DATA_DIR = project_root / "data" / "test"
MANIFEST_PATH = TEST_DATA_DIR / "manifest.json"
RESULTS_DIR = project_root / "docs" / "evaluation"


def load_gold_standard():
    """Load gold standard test set from manifest.json"""
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    
    samples = []
    for item in manifest:
        audio_path = TEST_DATA_DIR / item["audio_file"]
        if not audio_path.exists():
            print(f"  WARNING: Audio file not found: {audio_path}")
            continue
        samples.append({
            "audio_path": str(audio_path),
            "reference": item["transcription"]
        })
    
    print(f"Loaded {len(samples)} gold standard samples from {MANIFEST_PATH}")
    return samples


def normalize_text(text):
    """Normalize Japanese text for CER calculation"""
    import re
    # Remove extra whitespace
    text = re.sub(r'\s+', '', text)
    # Remove punctuation that might cause CER inflation
    # (keeping Japanese punctuation since it matters for accuracy)
    return text.strip()


def run_faster_whisper_eval(model_name, samples, compute_cer=True, 
                            beam_size=5, language="ja", device="auto"):
    """Run ASR evaluation using faster-whisper"""
    from faster_whisper import WhisperModel
    
    print(f"\n{'='*60}")
    print(f"Loading model: {model_name}")
    print(f"{'='*60}")
    
    # Determine compute type
    import torch
    if torch.cuda.is_available():
        compute_type = "float16"
    else:
        compute_type = "int8"
    
    start_time = time.time()
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    load_time = time.time() - start_time
    print(f"Model loaded in {load_time:.1f}s (compute_type={compute_type})")
    
    results = []
    total_asr_time = 0.0
    total_audio_duration = 0.0
    
    for i, sample in enumerate(samples):
        audio_path = sample["audio_path"]
        reference = sample["reference"]
        
        # Run ASR
        asr_start = time.time()
        segments, info = model.transcribe(
            audio_path,
            language=language,
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        
        # Collect transcription
        transcription = " ".join([seg.text.strip() for seg in segments])
        asr_time = time.time() - asr_start
        
        # Get audio duration from info
        audio_duration = info.duration if info.duration else 0
        
        total_asr_time += asr_time
        total_audio_duration += audio_duration
        
        # Calculate CER
        cer_score = cer(normalize_text(reference), normalize_text(transcription)) if compute_cer else None
        
        results.append({
            "sample": os.path.basename(audio_path),
            "reference": reference,
            "transcription": transcription,
            "cer": cer_score,
            "asr_time": asr_time,
            "audio_duration": audio_duration,
        })
        
        if (i + 1) % 50 == 0:
            avg_cer = np.mean([r["cer"] for r in results if r["cer"] is not None])
            print(f"  Progress: {i+1}/{len(samples)}, avg CER so far: {avg_cer:.4f}")
    
    # Aggregate results
    cers = [r["cer"] for r in results if r["cer"] is not None]
    avg_cer = np.mean(cers) if cers else None
    median_cer = np.median(cers) if cers else None
    p90_cer = np.percentile(cers, 90) if cers else None
    
    total_rtf = total_asr_time / total_audio_duration if total_audio_duration > 0 else 0
    
    summary = {
        "model": model_name,
        "compute_type": compute_type,
        "beam_size": beam_size,
        "language": language,
        "num_samples": len(results),
        "load_time_seconds": load_time,
        "total_asr_time_seconds": total_asr_time,
        "total_audio_duration_seconds": total_audio_duration,
        "real_time_factor": total_rtf,
        "avg_cer": avg_cer,
        "median_cer": median_cer,
        "p90_cer": p90_cer,
        "results": results,
    }
    
    print(f"\n{'='*60}")
    print(f"Results for {model_name}")
    print(f"{'='*60}")
    print(f"Samples: {len(results)}")
    print(f"Avg CER: {avg_cer:.4f}" if avg_cer else "Avg CER: N/A")
    print(f"Median CER: {median_cer:.4f}" if median_cer else "")
    print(f"P90 CER: {p90_cer:.4f}" if p90_cer else "")
    print(f"Total ASR time: {total_asr_time:.1f}s")
    print(f"Total audio: {total_audio_duration:.1f}s")
    print(f"RTF: {total_rtf:.3f}")
    
    return summary


def save_results(summary, output_path):
    """Save evaluation results to JSON"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Convert numpy types to native Python types for JSON serialization
    def convert(obj):
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return obj
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=convert)
    
    print(f"Results saved to {output_path}")


def generate_report():
    """Generate the final evaluation report from saved results"""
    report_path = RESULTS_DIR / "S3.1_ASR_Evaluation.md"
    
    # Load all result files
    result_files = sorted(RESULTS_DIR.glob("S3.1_results_*.json"))
    
    if not result_files:
        print("No result files found. Run evaluations first.")
        return
    
    all_summaries = []
    for rf in result_files:
        with open(rf, "r", encoding="utf-8") as f:
            all_summaries.append(json.load(f))
    
    # Build report
    lines = []
    lines.append("# S3.1 ASR 主力评估报告")
    lines.append("")
    lines.append(f"> 日期: 2026-07-11")
    lines.append(f"> 测试集: {all_summaries[0]['num_samples'] if all_summaries else 0} 条日语语音片段")
    lines.append(f"> 测试环境: Python 3.13 + torch 2.11.0+cu128, RTX 3060 12GB")
    lines.append("")
    lines.append("## 测试集")
    lines.append("")
    lines.append("| 属性 | 值 |")
    lines.append("|------|-----|")
    lines.append("| 来源 | 自制数据集 (audio-visual novel 语音片段) |")
    lines.append("| 样本数 | 200 条 |")
    lines.append("| 平均时长 | ~5 秒/条 |")
    lines.append("| 总时长 | ~16 分钟 |")
    lines.append("| 语言 | 日语 |")
    lines.append("| 标注 | 人工听写标注 (manifest.json) |")
    lines.append("")
    lines.append("## 评测模型")
    lines.append("")
    lines.append("| 模型 | 大小 | 说明 |")
    lines.append("|------|------|------|")
    lines.append("| large-v3-turbo | ~1.5GB | faster-whisper 官方最佳速度/精度平衡模型 |")
    for s in all_summaries:
        if s["model"] != "large-v3-turbo":
            size = "可变"
            lines.append(f"| {s['model']} | {size} | 社区动漫微调版 |")
    lines.append("")
    lines.append("## 结果汇总")
    lines.append("")
    lines.append("| 模型 | CER ↓ | Med CER | P90 CER | RTF | 加载时间 |")
    lines.append("|------|:-----:|:-------:|:-------:|:---:|:-------:|")
    
    for s in all_summaries:
        model_name = s["model"]
        avg_cer = f"{s['avg_cer']:.4f}" if s.get("avg_cer") else "N/A"
        med_cer = f"{s['median_cer']:.4f}" if s.get("median_cer") else "N/A"
        p90_cer = f"{s['p90_cer']:.4f}" if s.get("p90_cer") else "N/A"
        rtf = f"{s['real_time_factor']:.3f}" if s.get("real_time_factor") else "N/A"
        load_time = f"{s['load_time_seconds']:.1f}s" if s.get("load_time_seconds") else "N/A"
        lines.append(f"| {model_name} | {avg_cer} | {med_cer} | {p90_cer} | {rtf} | {load_time} |")
    
    lines.append("")
    lines.append("## 详细分析")
    lines.append("")
    
    # Find worst/best samples for each model
    for s in all_summaries:
        if not s.get("results"):
            continue
        model_name = s["model"]
        results = s["results"]
        
        # Sort by CER
        sorted_results = sorted(results, key=lambda r: r["cer"] if r["cer"] is not None else 999)
        
        lines.append(f"### {model_name}")
        lines.append("")
        lines.append(f"- 样本数: {len(results)}")
        lines.append(f"- 平均 CER: {s['avg_cer']:.4f}" if s.get("avg_cer") else "")
        lines.append(f"- 中位数 CER: {s['median_cer']:.4f}" if s.get("median_cer") else "")
        lines.append("")
        
        # Best 5
        lines.append("**最佳 5 条 (最低 CER):**")
        lines.append("")
        lines.append("| 样本 | 参考文本 | ASR 输出 | CER |")
        lines.append("|------|---------|---------|:---:|")
        for r in sorted_results[:5]:
            ref = r["reference"][:30]
            hyp = r["transcription"][:30]
            cer_val = f"{r['cer']:.4f}" if r.get("cer") is not None else "N/A"
            lines.append(f"| {r['sample']} | {ref}... | {hyp}... | {cer_val} |")
        
        lines.append("")
        lines.append("**最差 5 条 (最高 CER):**")
        lines.append("")
        lines.append("| 样本 | 参考文本 | ASR 输出 | CER |")
        lines.append("|------|---------|---------|:---:|")
        for r in reversed(sorted_results[-5:]):
            ref = r["reference"][:30]
            hyp = r["transcription"][:30]
            cer_val = f"{r['cer']:.4f}" if r.get("cer") is not None else "N/A"
            lines.append(f"| {r['sample']} | {ref}... | {hyp}... | {cer_val} |")
        
        lines.append("")
    
    lines.append("## 结论")
    lines.append("")
    
    # Find best model
    valid = [s for s in all_summaries if s.get("avg_cer") is not None]
    if valid:
        best = min(valid, key=lambda s: s["avg_cer"])
        lines.append(f"**最佳 ASR 模型**: {best['model']} (CER={best['avg_cer']:.4f})")
        lines.append("")
    
    lines.append("### 推荐")
    lines.append("")
    lines.append("根据评测结果，选定接下来的 ASR 方案：")
    lines.append("")
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    print(f"Report generated: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="S3.1 ASR Evaluation")
    parser.add_argument("--model", type=str, default=None,
                        help="Model name/path to evaluate")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON path")
    parser.add_argument("--report", action="store_true",
                        help="Generate report from saved results")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--device", type=str, default="auto")
    
    args = parser.parse_args()
    
    if args.report:
        generate_report()
        return
    
    if not args.model:
        parser.print_help()
        return
    
    # Load gold standard
    samples = load_gold_standard()
    if not samples:
        print("ERROR: No samples loaded!")
        return
    
    # Run evaluation
    summary = run_faster_whisper_eval(
        model_name=args.model,
        samples=samples,
        beam_size=args.beam_size,
        device=args.device,
    )
    
    # Save results
    output_path = args.output or str(RESULTS_DIR / f"S3.1_results_{Path(args.model).name}.json")
    save_results(summary, output_path)


if __name__ == "__main__":
    main()