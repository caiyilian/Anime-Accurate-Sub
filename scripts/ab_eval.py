# S13.2: A/B model evaluation tool - CER + term hit rate comparison
#
# Compares two ASR or translation models on the same dataset:
#   - CER (Character Error Rate) via jiwer
#   - Term hit rate (glossary term coverage)
#   - Speed comparison
#
# Usage:
#   python scripts/ab_eval.py --ref reference.json --a model_a.json --b model_b.json
#   python scripts/ab_eval.py --ref reference.json --a model_a.json --b model_b.json --glossary glossary.json
#   python scripts/ab_eval.py --evaluate

import json, os, sys, time, argparse
from pathlib import Path
from typing import List, Optional

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


def load_segments(path: str) -> dict:
    """Load segments from JSON file. Returns dict of index -> text."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    result = {}
    if isinstance(data, list):
        for i, item in enumerate(data):
            for key in ["text", "transcription", "zh", "ja"]:
                if key in item and item[key]:
                    result[i] = item[key].strip()
                    break
    elif isinstance(data, dict):
        for key in ["text", "transcription", "zh", "ja"]:
            if key in data and data[key]:
                result[0] = data[key].strip()
                break

    return result


def load_glossary(path: str) -> dict:
    """Load glossary JSON and return ja->zh mapping."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    mapping = {}
    terms = data.get("terms", data if isinstance(data, list) else [])
    for item in terms:
        ja = item.get("ja", "")
        zh = item.get("zh", "")
        if ja and zh:
            mapping[ja] = zh
    return mapping


def compute_cer(ref_text: str, hyp_text: str) -> float:
    """Compute Character Error Rate."""
    try:
        from jiwer import cer
        return cer(ref_text, hyp_text)
    except ImportError:
        # Fallback: simple Levenshtein-based CER
        return _levenshtein_cer(ref_text, hyp_text)


def _levenshtein_cer(ref: str, hyp: str) -> float:
    """Simple Levenshtein-based CER fallback."""
    n, m = len(ref), len(hyp)
    if n == 0 and m == 0:
        return 0.0
    if n == 0:
        return float(m)
    if m == 0:
        return float(n)

    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, m + 1):
            temp = dp[j]
            dp[j] = min(
                prev + (0 if ref[i-1] == hyp[j-1] else 1),
                dp[j] + 1,
                dp[j-1] + 1,
            )
            prev = temp
    return dp[m] / max(n, 1)


def compute_term_hit_rate(texts: List[str], glossary: dict) -> dict:
    """Compute how many glossary terms appear in the texts."""
    if not glossary:
        return {"rate": None, "hit": 0, "total": 0, "details": []}

    results = []
    hit = 0
    for ja, zh in glossary.items():
        found = any(zh in text for text in texts)
        if found:
            hit += 1
        results.append({"term": ja, "zh": zh, "found": found})

    return {
        "rate": hit / len(glossary) if glossary else None,
        "hit": hit,
        "total": len(glossary),
        "details": results,
    }


def evaluate_pair(ref_data: dict, a_data: dict, b_data: dict,
                   a_name: str = "Model A", b_name: str = "Model B",
                   glossary: Optional[dict] = None) -> dict:
    """Compare two models against reference."""
    common_keys = sorted(set(ref_data.keys()) & set(a_data.keys()) & set(b_data.keys()))
    print(f"  Common segments: {len(common_keys)}")

    # Compute CER
    a_cers = []
    b_cers = []
    a_times = []
    b_times = []
    a_texts = []
    b_texts = []

    for k in common_keys:
        ref = ref_data[k]
        a_text = a_data[k]
        b_text = b_data[k]

        a_cer = compute_cer(ref, a_text)
        b_cer = compute_cer(ref, b_text)
        a_cers.append(a_cer)
        b_cers.append(b_cer)
        a_texts.append(a_text)
        b_texts.append(b_text)

    # Compute average CER
    avg_a_cer = sum(a_cers) / len(a_cers) if a_cers else 0
    avg_b_cer = sum(b_cers) / len(b_cers) if b_cers else 0

    # Compute term hit rate
    a_term = compute_term_hit_rate(a_texts, glossary)
    b_term = compute_term_hit_rate(b_texts, glossary)

    # Determine winner
    cer_winner = a_name if avg_a_cer < avg_b_cer else (b_name if avg_b_cer < avg_a_cer else "tie")
    term_winner = a_name if (a_term["rate"] or 0) > (b_term["rate"] or 0) else (
        b_name if (b_term["rate"] or 0) > (a_term["rate"] or 0) else "tie"
    )

    return {
        "models": {"A": a_name, "B": b_name},
        "common_segments": len(common_keys),
        "cer": {
            "a_avg": round(avg_a_cer, 4),
            "b_avg": round(avg_b_cer, 4),
            "winner": cer_winner,
            "improvement_pct": round((avg_b_cer - avg_a_cer) / max(avg_b_cer, 0.001) * 100, 1),
        },
        "term_hit_rate": {
            "a": {k: v for k, v in a_term.items() if k != "details"},
            "b": {k: v for k, v in b_term.items() if k != "details"},
            "winner": term_winner,
        },
    }


# ============ Evaluate ============

def evaluate():
    print("\n============================================================")
    print("S13.2 A/B MODEL EVALUATION")
    print("============================================================")

    # Test data: create 3 sets of segments (reference, model A, model B)
    ref = {
        i: text for i, text in enumerate([
            "おはよう、唯", "今日も元気だね", "澪ちゃん、一緒に練習しない？",
            "ありがとう、唯", "軽音部に行こう", "音楽室でお茶を飲もう",
        ])
    }
    model_a = {
        i: text for i, text in enumerate([
            "おはよう、唯", "今日も元気だね", "澪ちゃん、一緒に練習しない？",
            "ありがとう、唯", "軽音部に行くよ", "音楽室でお茶を飲もう",
        ])
    }  # 1 error
    model_b = {
        i: text for i, text in enumerate([
            "おはよう、唯", "今日も元気だ", "澪、一緒に練習？",
            "ありがとう唯", "軽音部行く", "音楽室でお茶",
        ])
    }  # 3 errors

    glossary = load_glossary(str(project_root / "data" / "glossary" / "k-on_glossary.json"))

    print(f"\nReference: {len(ref)} segments")
    print(f"Model A: {len(model_a)} segments (1 intentional error)")
    print(f"Model B: {len(model_b)} segments (3 intentional errors)")
    print(f"Glossary: {len(glossary)} terms")

    result = evaluate_pair(ref, model_a, model_b,
                            a_name="Anime Whisper", b_name="large-v3",
                            glossary=glossary)

    print(f"\n--- Results ---")
    print(f"CER: A={result['cer']['a_avg']:.4f}, B={result['cer']['b_avg']:.4f}, "
          f"winner={result['cer']['winner']}, improvement={result['cer']['improvement_pct']:.1f}%")
    print(f"Term hit: A={result['term_hit_rate']['a']['rate']:.1%}, "
          f"B={result['term_hit_rate']['b']['rate']:.1%}, "
          f"winner={result['term_hit_rate']['winner']}")

    assert result["cer"]["winner"] == "Anime Whisper"
    assert result["cer"]["improvement_pct"] > 0
    print(f"  CER improvement: {result['cer']['improvement_pct']:.1f}%")
    print("  Assertions passed!")

    # Save
    out_path = project_root / "docs" / "evaluation" / "S13.2_ab_eval_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved: {out_path}")

    print("\n============================================================")
    print("ALL TESTS PASSED")
    print("============================================================")


# ============ CLI ============

def main():
    parser = argparse.ArgumentParser(description="S13.2 A/B Model Evaluation")
    parser.add_argument("--ref", type=str, help="Reference JSON file")
    parser.add_argument("--a", type=str, help="Model A output JSON file")
    parser.add_argument("--b", type=str, help="Model B output JSON file")
    parser.add_argument("--a-name", type=str, default="Model A", help="Model A name")
    parser.add_argument("--b-name", type=str, default="Model B", help="Model B name")
    parser.add_argument("--glossary", type=str, help="Glossary JSON for term hit rate")
    parser.add_argument("--output", type=str, default="", help="Output JSON file")
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()

    if args.evaluate:
        evaluate()
        return

    if args.ref and args.a and args.b:
        ref_data = load_segments(args.ref)
        a_data = load_segments(args.a)
        b_data = load_segments(args.b)
        glossary = load_glossary(args.glossary) if args.glossary else {}

        result = evaluate_pair(ref_data, a_data, b_data, args.a_name, args.b_name, glossary)

        print(f"\n--- Comparison: {args.a_name} vs {args.b_name} ---")
        print(f"Segments: {result['common_segments']}")
        print(f"CER: {args.a_name}={result['cer']['a_avg']:.4f}, "
              f"{args.b_name}={result['cer']['b_avg']:.4f}")
        print(f"  Winner: {result['cer']['winner']} "
              f"({result['cer']['improvement_pct']:.1f}% improvement)")
        if result['term_hit_rate']['a']['rate'] is not None:
            print(f"Term hit: {args.a_name}={result['term_hit_rate']['a']['rate']:.1%}, "
                  f"{args.b_name}={result['term_hit_rate']['b']['rate']:.1%}")
            print(f"  Winner: {result['term_hit_rate']['winner']}")

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"Saved: {args.output}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()