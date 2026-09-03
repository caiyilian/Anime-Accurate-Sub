# Accuracy evaluation: ASR CER + translation quality + pipeline sampling
#
# 1. ASR: Run Anime Whisper on 200 gold standard clips, compute CER
# 2. Translate: Run GEMBA-MQM on sampled K-On! subtitle segments
# 3. Compare against Sprint 3 baseline
#
# Usage:
#   python scripts/eval_accuracy.py

import json, os, sys, time, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jiwer import cer
from faster_whisper import WhisperModel

project_root = Path(__file__).resolve().parent.parent
RESULTS_DIR = project_root / "docs" / "evaluation"
TEST_DIR = project_root / "data" / "test"
MANIFEST = TEST_DIR / "manifest.json"
MODEL_PATH = project_root / ".omo" / "anime-whisper-ct2"
OLLAMA_HOST = "172.31.102.189"
MQM_MODEL = "crosery/sakura-14b-qwen2.5-v1.0-q6k:latest"


def load_manifest():
    with open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def normalize_text(text):
    import re
    return re.sub(r"\s+", "", text).strip()


def eval_asr(sample_limit=None):
    """Run ASR on gold standard test set and compute CER."""
    manifest = load_manifest()
    if sample_limit:
        manifest = manifest[:sample_limit]

    print(f"Loading ASR model...")
    t0 = time.time()
    model = WhisperModel(str(MODEL_PATH), device="cuda", compute_type="int8_float16", num_workers=1)
    print(f"  Loaded in {time.time()-t0:.1f}s")

    results = []
    total_cer = 0
    total_time = 0

    for i, item in enumerate(manifest):
        audio_path = TEST_DIR / item["audio_file"]
        ref = item["transcription"]

        t0 = time.time()
        segments, info = model.transcribe(str(audio_path), language="ja", beam_size=5, vad_filter=False)
        elapsed = time.time() - t0

        hyp = " ".join(s.text.strip() for s in segments)
        c = cer(normalize_text(ref), normalize_text(hyp))
        total_cer += c
        total_time += elapsed
        results.append({"file": item["audio_file"], "ref": ref, "hyp": hyp, "cer": round(c, 4), "time_s": round(elapsed, 2)})

        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(manifest)}] avg CER so far: {total_cer/(i+1):.4f}")

    avg_cer = total_cer / len(results) if results else 0
    avg_time = total_time / len(results) if results else 0

    print(f"\nASR Results on {len(results)} samples:")
    print(f"  Avg CER: {avg_cer:.4f}")
    print(f"  Avg time per clip: {avg_time:.2f}s")
    print(f"  Total time: {total_time:.1f}s")

    return {"model": "Anime Whisper CT2", "samples": len(results), "avg_cer": round(avg_cer, 4), "avg_time_s": round(avg_time, 2), "results": results}


def eval_translation_quality(sample_path=None, num_samples=20):
    """Score translation quality using GEMBA-MQM."""
    from scripts.gemba_mqm import score_segment, MQM_DIMENSIONS

    # Load translation segments from one of the K-On! episodes
    if sample_path:
        with open(sample_path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        # Use the first available translated.json
        output_dir = project_root / "output"
        ep_dirs = sorted(output_dir.glob("k-on_ep*"))
        if not ep_dirs:
            print("No episode output found")
            return None
        first_ep = ep_dirs[0]
        trans_path = first_ep / "translated.json"
        if not trans_path.exists():
            print(f"No translated.json in {first_ep}")
            return None
        with open(trans_path, encoding="utf-8") as f:
            data = json.load(f)

    # Sample segments
    data = data[:num_samples]
    print(f"Scoring {len(data)} translation segments via GEMBA-MQM...")

    results = []
    scores = []
    for i, seg in enumerate(data):
        ja = seg.get("ja", "")
        zh = seg.get("text", "")
        if not ja or not zh:
            continue
        result = score_segment(ja, zh)
        results.append({"ja": ja, "zh": zh, "score": result["overall"], "dimensions": {k: v["score"] for k, v in result["dimensions"].items()}})
        scores.append(result["overall"])
        if (i + 1) % 5 == 0:
            print(f"  [{i+1}/{len(data)}] avg score: {sum(scores)/len(scores):.1f}")

    avg_score = sum(scores) / len(scores) if scores else 0
    print(f"\nTranslation Quality (GEMBA-MQM):")
    print(f"  Samples: {len(scores)}")
    print(f"  Avg Score: {avg_score:.1f}/100")

    return {"samples": len(scores), "avg_score": round(avg_score, 1), "results": results}


def main():
    parser = argparse.ArgumentParser(description="Accuracy Evaluation")
    parser.add_argument("--asr-samples", type=int, default=200, help="Number of ASR test samples")
    parser.add_argument("--trans-samples", type=int, default=20, help="Number of translation samples")
    parser.add_argument("--trans-path", type=str, default="", help="Path to translated.json")
    parser.add_argument("--output", type=str, default="accuracy_report.json")
    args = parser.parse_args()

    print("=" * 60)
    print("ACCURACY EVALUATION")
    print("=" * 60)

    report = {}

    # 1. ASR
    print(f"\n{'='*60}")
    print("PART 1: ASR CER on Gold Standard")
    print(f"{'='*60}")
    asr_result = eval_asr(sample_limit=args.asr_samples)
    report["asr"] = asr_result

    # 2. Translation quality
    print(f"\n{'='*60}")
    print("PART 2: Translation Quality (GEMBA-MQM)")
    print(f"{'='*60}")
    trans_result = eval_translation_quality(
        sample_path=args.trans_path if args.trans_path else None,
        num_samples=args.trans_samples,
    )
    report["translation"] = trans_result

    # 3. Compare with Sprint 3 baseline
    print(f"\n{'='*60}")
    print("PART 3: Comparison with Sprint 3 Baseline")
    print(f"{'='*60}")
    s3_baseline_cer = 0.1299
    if asr_result:
        improvement = (s3_baseline_cer - asr_result["avg_cer"]) / s3_baseline_cer * 100
        print(f"  Sprint 3 baseline CER: {s3_baseline_cer}")
        print(f"  Current ASR CER: {asr_result['avg_cer']}")
        print(f"  Change: {improvement:.1f}% ({'better' if improvement > 0 else 'worse'})")
        report["comparison"] = {
            "sprint3_baseline_cer": s3_baseline_cer,
            "current_cer": asr_result["avg_cer"],
            "change_pct": round(improvement, 1),
        }

    # Save
    out_path = project_root / "docs" / "evaluation" / args.output
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nReport saved: {out_path}")

    print(f"\n{'='*60}")
    print("EVALUATION COMPLETE")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()