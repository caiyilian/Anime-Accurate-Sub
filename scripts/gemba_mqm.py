# S11.3: GEMBA-MQM translation quality evaluation
#
# MQM (Multidimensional Quality Metrics) framework:
#   - 4 dimensions: accuracy, fluency, terminology, style
#   - Each scored 0-100
#   - Overall score = weighted average
#   - Low-scoring segments (< 60) trigger automatic re-translation
#
# Usage:
#   python scripts/gemba_mqm.py --input segments.json --output scored.json
#   python scripts/gemba_mqm.py --input segments.json --output scored.json --retranslate

import json, os, sys, time, argparse, urllib.request
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "localhost")
OLLAMA_URL = f"http://{OLLAMA_HOST}:11434/api"
MODEL = os.environ.get("MQM_MODEL", "EasonONLINE/Sakura-qwen2.5-v1.0:7b")
RETRANSLATE_MODEL = os.environ.get("TRANSLATION_MODEL", MODEL)

# Score threshold for re-translation
SCORE_THRESHOLD = 60  # Below this = needs re-translation

# MQM dimensions and weights
MQM_DIMENSIONS = {
    "accuracy": {"weight": 0.35, "name": "Accuracy", "desc": "是否准确传达了原文含义"},
    "fluency": {"weight": 0.25, "name": "Fluency", "desc": "中文是否通顺自然"},
    "terminology": {"weight": 0.20, "name": "Terminology", "desc": "术语和角色名是否一致"},
    "style": {"weight": 0.20, "name": "Style", "desc": "语气风格是否适合角色和场景"},
}


def ollama_chat(messages, temperature=0.1):
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": 512},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/chat", data=data,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read().decode("utf-8"))
    return result.get("message", {}).get("content", "").strip()


def ollama_generate(model, prompt, temperature=0.1):
    """Simple generate for re-translation."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一个轻小说翻译模型，可以将日语翻译成中文。"},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": temperature, "num_predict": 256},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/chat", data=data,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read().decode("utf-8"))
    return result.get("message", {}).get("content", "").strip()


# ============ MQM Scoring ============

def score_segment(ja: str, zh: str) -> dict:
    """Score a single translation segment using MQM framework."""
    dim_scores = {}
    total_weight = 0
    weighted_sum = 0

    for dim_id, dim_info in MQM_DIMENSIONS.items():
        prompt = (
            f"日文原文：{ja}\n"
            f"中文翻译：{zh}\n\n"
            f"请评估翻译的「{dim_info['name']}」维度（{dim_info['desc']}）。\n"
            f"评分标准：\n"
            f"  90-100：完美，无需修改\n"
            f"  70-89：良好，有微小改进空间\n"
            f"  50-69：一般，有明显问题\n"
            f"  0-49：差，需要大幅修改\n\n"
            f"请先给出评分，再简要说明理由。\n"
            f"格式：评分: XX\n理由: ..."
        )

        t0 = time.time()
        try:
            response = ollama_chat([
                {"role": "system", "content": f"你是一个翻译质量评估专家。请评估翻译的{dim_info['name']}。"},
                {"role": "user", "content": prompt},
            ])
        except Exception as e:
            response = f"评分: 50\n理由: 评估出错: {e}"
        elapsed = time.time() - t0

        # Parse score from response
        score = parse_score(response)
        dim_scores[dim_id] = {
            "score": score,
            "reason": response[:200],
            "time_s": round(elapsed, 2),
        }

        weighted_sum += score * dim_info["weight"]
        total_weight += dim_info["weight"]

    overall = round(weighted_sum / total_weight, 1) if total_weight > 0 else 0

    return {
        "ja": ja,
        "zh": zh,
        "overall": overall,
        "dimensions": dim_scores,
        "needs_retranslation": overall < SCORE_THRESHOLD,
    }


def parse_score(response: str) -> float:
    """Extract numeric score from LLM response."""
    import re
    # Try to find "评分: XX" pattern
    match = re.search(r"评分\s*[:：]\s*(\d+)", response)
    if match:
        return min(100, max(0, float(match.group(1))))
    # Try to find bare number at start
    match = re.search(r"^(\d+)", response.strip())
    if match:
        return min(100, max(0, float(match.group(1))))
    return 50.0  # Default middle score


# ============ Re-translation ============

def retranslate(ja: str) -> str:
    """Re-translate a low-scoring segment."""
    prompt = f"将下面的日语文本翻译成中文：{ja}"
    return ollama_generate(RETRANSLATE_MODEL, prompt)


# ============ Batch Processing ============

def process_batch(segments: list, retranslate_enabled: bool = False) -> list:
    """Process a batch of segments through MQM evaluation."""
    results = []
    total = len(segments)

    for i, seg in enumerate(segments):
        ja = seg.get("ja", seg.get("ja", ""))
        zh = seg.get("text", seg.get("zh", ""))

        print(f"  [{i+1}/{total}] Scoring: {ja[:30]}...", end=" ")

        result = score_segment(ja, zh)
        score = result["overall"]

        # Re-translate if needed
        if retranslate_enabled and result["needs_retranslation"]:
            print(f"score={score}, retranslating...", end=" ")
            new_zh = retranslate(ja)
            result["retranslated_zh"] = new_zh
            # Re-score the new translation
            rescore = score_segment(ja, new_zh)
            result["rescore"] = rescore["overall"]
            result["improved"] = rescore["overall"] > score
            print(f"new_score={rescore['overall']}")
        else:
            print(f"score={score}")

        results.append(result)

    return results


# ============ Test Data ============

def create_test_data():
    return [
        {"ja": "おはよう、唯", "zh": "早安，唯"},
        {"ja": "今日も元気だね", "zh": "今天也很有精神呢"},
        {"ja": "澪ちゃん、一緒に練習しない？", "zh": "澪，要不要一起练习？"},
        {"ja": "ありがとう、唯。じゃあ放課後ね", "zh": "谢谢你，唯。那放学后见"},
        {"ja": "ごめん、遅刻した", "zh": "对不起我迟到了今天早上闹钟没响"},  # intentionally bad translation
    ]


# ============ Evaluate ============

def evaluate():
    print("\n============================================================")
    print("S11.3 GEMBA-MQM EVALUATION")
    print("============================================================")
    print(f"Model: {MODEL}")
    print(f"Dimensions: {len(MQM_DIMENSIONS)}")
    for dim_id, info in MQM_DIMENSIONS.items():
        print(f"  {dim_id}: weight={info['weight']}, {info['desc']}")
    print(f"Threshold: {SCORE_THRESHOLD}")

    segments = create_test_data()
    print(f"\nTesting with {len(segments)} segments...")

    results = process_batch(segments, retranslate_enabled=True)

    # Print summary
    print(f"\n--- Results ---")
    for r in results:
        dims = ", ".join(f"{k}={v['score']:.0f}" for k, v in r["dimensions"].items())
        retranslated = r.get("retranslated_zh", "")
        improved = r.get("improved", False)
        print(f"\n  JA: {r['ja'][:30]}")
        print(f"  ZH: {r['zh'][:40]}")
        print(f"  Score: {r['overall']:.1f} ({dims})")
        if retranslated:
            print(f"  RETRANSLATED: {retranslated[:40]} (improved={improved})")
            if r.get("rescore"):
                print(f"  NEW SCORE: {r['rescore']:.1f}")

    # Stats
    scores = [r["overall"] for r in results]
    retranslated_count = sum(1 for r in results if r["needs_retranslation"])
    print(f"\n--- Stats ---")
    print(f"  Average score: {sum(scores)/len(scores):.1f}")
    print(f"  Min score: {min(scores):.1f}")
    print(f"  Max score: {max(scores):.1f}")
    print(f"  Below threshold ({SCORE_THRESHOLD}): {retranslated_count}/{len(results)}")

    # Save results
    out_path = project_root / "docs" / "evaluation" / "S11.3_gemba_mqm_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"model": MODEL, "results": results}, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved: {out_path}")

    print("\n============================================================")
    print("EVALUATION COMPLETE")
    print("============================================================")


# ============ CLI ============

def main():
    parser = argparse.ArgumentParser(description="S11.3 GEMBA-MQM Translation Quality Evaluation")
    parser.add_argument("--input", type=str, help="Input JSON segments file")
    parser.add_argument("--output", type=str, default="", help="Output scored JSON file")
    parser.add_argument("--retranslate", action="store_true", help="Enable auto re-translation for low scores")
    parser.add_argument("--threshold", type=int, default=60, help="Score threshold for re-translation")
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()

    SCORE_THRESHOLD = args.threshold

    if args.evaluate:
        evaluate()
        return

    if args.input:
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)
        results = process_batch(data, args.retranslate)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"Saved: {args.output}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()