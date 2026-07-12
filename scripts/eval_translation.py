"""S8.1: Sakura-7B vs Sakura-14B translation evaluation.

Compares translation quality, speed, and VRAM usage between Sakura models.

Usage:
  # Test Sakura-7B
  python scripts/eval_translation.py --model EasonONLINE/Sakura-qwen2.5-v1.0:7b
  
  # Test Sakura-14B (server)
  python scripts/eval_translation.py --model crosery/sakura-14b-qwen2.5-v1.0-q6k
  
  # Run comparison
  python scripts/eval_translation.py --compare
  
  # Generate report
  python scripts/eval_translation.py --report
"""

import json, os, sys, time, argparse, re
from pathlib import Path
import urllib.request

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

RESULTS_DIR = project_root / "docs" / "evaluation"
DATA_DIR = project_root / "data"


# ======== Test data ========

def load_test_data():
    """Load Japanese test sentences with reference translations."""
    samples = []

    # 1. Load gold standard ASR transcriptions (200 sentences)
    manifest_path = DATA_DIR / "test" / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        for item in manifest:
            samples.append({
                "source": "asr_gold",
                "ja": item["transcription"],
                "zh_ref": None,  # No reference for most
            })

    # 2. Load K-On! bilingual data (properly aligned sentences)
    bilingual_path = DATA_DIR / "test" / "k-on_bilingual.json"
    if bilingual_path.exists():
        with open(bilingual_path, encoding="utf-8") as f:
            bilingual = json.load(f)
        for item in bilingual:
            ja = item.get("ja", "").strip()
            zh = item.get("zh", "").strip()
            # Only include if both are reasonable length (not lyrics/song names)
            if ja and zh and len(ja) > 5 and len(zh) > 5 and len(ja) < 100:
                # Filter out song lyric lines (contain special markers)
                if not any(c in ja for c in ["", "♪", "～"]):
                    samples.append({
                        "source": "k-on_subtitle",
                        "ja": ja,
                        "zh_ref": zh,
                    })

    print(f"Loaded {len(samples)} test samples")
    print(f"  ASR gold: {sum(1 for s in samples if s['source'] == 'asr_gold')}")
    print(f"  Bilingual: {sum(1 for s in samples if s['source'] == 'k-on_subtitle')}")
    return samples[:50]  # Use first 50 for quick evaluation


# ======== Ollama API ========

OLLAMA_URL = "http://localhost:11434/api"


def ollama_chat(model, messages):
    """Send chat request to Ollama API and return response."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 512,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read().decode("utf-8"))
    return result.get("message", {}).get("content", "").strip()


def translate_sakura(model, ja_text):
    """Translate Japanese text to Chinese using Sakura model."""
    messages = [
        {"role": "system", "content": "你是一个轻小说翻译模型，可以将日语翻译成中文。"},
        {"role": "user", "content": f"将下面的日语文本翻译成中文：{ja_text}"},
    ]
    return ollama_chat(model, messages)


def check_model_available(model):
    """Check if model is available in Ollama."""
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/show", data=json.dumps({"name": model}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False


# ======== Evaluation ========

def evaluate_model(model, samples, num_samples=None):
    """Evaluate a single model on translation samples."""
    if num_samples:
        samples = samples[:num_samples]

    if not check_model_available(model):
        return {"model": model, "error": f"Model {model} not found in Ollama"}

    results = []
    total_time = 0
    total_chars = 0
    vr_usages = []

    print(f"\n{'='*60}")
    print(f"Evaluating: {model}")
    print(f"{'='*60}")

    for i, sample in enumerate(samples):
        ja = sample["ja"]
        zh_ref = sample.get("zh_ref")

        print(f"\n  [{i+1}/{len(samples)}] {ja[:40]}...")

        t0 = time.time()
        try:
            translation = translate_sakura(model, ja)
            elapsed = time.time() - t0
            total_time += elapsed
            total_chars += len(ja)

            result = {
                "index": i,
                "ja": ja,
                "zh_translated": translation,
                "zh_ref": zh_ref,
                "time_s": round(elapsed, 2),
                "ja_chars": len(ja),
            }

            # Check character name preservation
            char_names = ["唯", "澪", "律", "紬", "忧", "和"]
            ja_has_names = [n for n in char_names if n in ja]
            zh_has_names = [n for n in char_names if n in translation]
            if ja_has_names:
                result["char_names_ja"] = ja_has_names
                result["char_names_zh"] = zh_has_names
                result["char_names_preserved"] = all(n in translation for n in ja_has_names)

            results.append(result)

            # Try to get VRAM info
            try:
                vr = urllib.request.urlopen(f"{OLLAMA_URL}/gpu", timeout=3)
                vr_data = json.loads(vr.read().decode("utf-8"))
                vr_usages.append(vr_data)
            except Exception:
                pass

            status = "✓" if zh_ref is None or len(translation) > 0 else "✗"
            print(f"    -> {translation[:50]}... ({elapsed:.1f}s) {status}")

        except Exception as e:
            print(f"    ERROR: {e}")
            results.append({"index": i, "ja": ja, "error": str(e)})

    # Compute stats
    successful = [r for r in results if "error" not in r]
    avg_time = total_time / len(successful) if successful else 0
    avg_chars_per_sec = total_chars / total_time if total_time > 0 else 0

    # Character name preservation
    name_preserved = sum(1 for r in successful if r.get("char_names_preserved"))
    name_total = sum(1 for r in successful if "char_names_ja" in r)

    stats = {
        "model": model,
        "samples_total": len(samples),
        "samples_success": len(successful),
        "samples_failed": len(samples) - len(successful),
        "total_time_s": round(total_time, 2),
        "avg_time_per_sample_s": round(avg_time, 2),
        "avg_chars_per_sec": round(avg_chars_per_sec, 2),
        "char_name_preservation": {
            "total_with_names": name_total,
            "preserved": name_preserved,
            "rate": round(name_preserved / name_total, 4) if name_total > 0 else None,
        },
    }

    return {"model": model, "stats": stats, "samples": results}


def print_comparison(results_list):
    """Print comparison of multiple models."""
    print(f"\n\n{'='*70}")
    print("SAKURA TRANSLATION COMPARISON")
    print(f"{'='*70}")

    for res in results_list:
        if "error" in res:
            print(f"\n  [{res['model']}] ERROR: {res['error']}")
            continue
        s = res["stats"]
        print(f"\n  [{s['model']}]")
        print(f"    Success: {s['samples_success']}/{s['samples_total']}")
        print(f"    Avg time: {s['avg_time_per_sample_s']}s")
        print(f"    Speed: {s['avg_chars_per_sec']} chars/s")
        if s['char_name_preservation']['rate'] is not None:
            print(f"    Character name preservation: {s['char_name_preservation']['rate']:.1%}")

    # Side-by-side comparison for first few samples
    print(f"\n{'='*70}")
    print("SIDE-BY-SIDE COMPARISON (first 5)")
    print(f"{'='*70}")

    models = [r for r in results_list if "error" not in r]
    if len(models) >= 1:
        for i in range(min(5, len(models[0].get("samples", [])))):
            ja = models[0]["samples"][i].get("ja", "")
            ref = models[0]["samples"][i].get("zh_ref", "")
            print(f"\n  JA: {ja[:50]}")
            if ref:
                print(f"  REF: {ref[:50]}")
            for m in models:
                zh = m["samples"][i].get("zh_translated", "ERROR")
                print(f"  [{m['stats']['model'][:20]}]: {zh[:50]}")


# ======== Main ========

def main():
    parser = argparse.ArgumentParser(description="S8.1 Sakura Translation Evaluation")
    parser.add_argument("--model", type=str, help="Ollama model name to test")
    parser.add_argument("--compare", action="store_true", help="Compare all Sakura models")
    parser.add_argument("--num-samples", type=int, default=20, help="Number of test samples")
    parser.add_argument("--report", action="store_true", help="Print report from saved results")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    if args.report:
        for rf in sorted(RESULTS_DIR.glob("S8.1_*_results.json")):
            with open(rf) as f:
                data = json.load(f)
            print_comparison([data])
        return

    # Load test data
    samples = load_test_data()

    if args.model:
        # Single model test
        result = evaluate_model(args.model, samples, args.num_samples)
        if args.output:
            out_path = Path(args.output)
        else:
            model_name = args.model.replace("/", "_").replace(":", "_")
            out_path = RESULTS_DIR / f"S8.1_{model_name}_results.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\nSaved: {out_path}")

    elif args.compare:
        models_to_test = [
            "EasonONLINE/Sakura-qwen2.5-v1.0:7b",
            "crosery/sakura-14b-qwen2.5-v1.0-q6k",
        ]
        results = []
        for model in models_to_test:
            if check_model_available(model):
                result = evaluate_model(model, samples, args.num_samples)
                results.append(result)
            else:
                print(f"\nSKIPPING {model} (not available)")
                results.append({"model": model, "error": "Not available"})

        print_comparison(results)

        out_path = RESULTS_DIR / "S8.1_comparison_results.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"models": results, "test_date": time.strftime("%Y-%m-%d")}, f, ensure_ascii=False, indent=2)
        print(f"\nComparison saved: {out_path}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()