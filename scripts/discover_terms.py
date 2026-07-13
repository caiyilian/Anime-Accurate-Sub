# S13.1: Proper noun discovery - extract high-frequency terms + LLM annotation
#
# Workflow:
#   1. Load Japanese ASR text from segments
#   2. Extract high-frequency words using morphological analysis
#   3. Filter candidates (length, frequency thresholds)
#   4. Use LLM to classify and annotate (character names, places, terms)
#   5. Generate candidate glossary in JSON format
#
# Usage:
#   python scripts/discover_terms.py --input asr_text.txt --output glossary.json
#   python scripts/discover_terms.py --input asr_segments.json --output glossary.json
#   python scripts/discover_terms.py --input asr_segments.json --output glossary.json --llm

import json, os, sys, time, argparse, re
from pathlib import Path
from collections import Counter
from typing import List, Optional
import urllib.request

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "172.31.102.189")
OLLAMA_URL = f"http://{OLLAMA_HOST}:11434/api"
LLM_MODEL = os.environ.get("LLM_MODEL", "crosery/sakura-14b-qwen2.5-v1.0-q6k:latest")

# Frequency threshold: a term must appear at least this many times
MIN_FREQ = 3
# Minimum length for candidate terms (characters)
MIN_TERM_LEN = 2


def load_text(input_path: str) -> str:
    """Load Japanese text from file or segments JSON."""
    path = Path(input_path)
    if not path.exists():
        return input_path  # Treat as raw text

    with open(path, encoding="utf-8") as f:
        raw = f.read()

    if input_path.endswith(".json"):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                # Try to extract ja/transcription/text fields
                texts = []
                for item in data:
                    for key in ["ja", "transcription", "text"]:
                        if key in item and item[key]:
                            texts.append(item[key])
                            break
                return "\n".join(texts)
            elif isinstance(data, dict):
                return json.dumps(data, ensure_ascii=False)
        except json.JSONDecodeError:
            pass

    return raw


def extract_candidates(text: str, min_freq: int = MIN_FREQ,
                        min_len: int = MIN_TERM_LEN) -> List[dict]:
    """Extract high-frequency term candidates from Japanese text.

    Uses simple frequency analysis (no morphological parser dependency).
    """
    # Split by common Japanese delimiters
    words = re.split(r"[\s、。！？「」『』（）【】　,./\\!?\"\'\[\]()\n\r]+", text)

    # Filter and count
    counter = Counter()
    for word in words:
        word = word.strip()
        # Filter criteria
        if len(word) < min_len:
            continue
        if word.isascii():
            continue  # Skip pure ASCII
        if word.isdigit():
            continue  # Skip pure numbers
        counter[word] += 1

    # Return candidates above threshold
    candidates = []
    for word, freq in counter.most_common(100):
        if freq >= min_freq:
            candidates.append({"ja": word, "freq": freq})

    return candidates


def annotate_with_llm(candidates: List[dict]) -> List[dict]:
    """Use LLM to classify and annotate candidate terms."""
    if not candidates:
        return []

    # Batch candidates for LLM
    candidate_text = "\n".join(
        f"{i+1}. {c['ja']} (freq={c['freq']})"
        for i, c in enumerate(candidates[:30])  # Limit to 30
    )

    prompt = (
        f"以下是从动漫日语文本中提取的高频词候选列表。请对每个词分类，并给出中文翻译。\n\n"
        f"{candidate_text}\n\n"
        f"分类标签：character（角色名）、place（地点）、term（专有术语）、other（其他）\n\n"
        f"输出格式（每行一个）：\n"
        f"词|分类|中文翻译\n"
        f"例如：\n"
        f"平沢唯|character|平泽唯\n"
        f"軽音部|term|轻音部\n"
    )

    system = "你是一个动漫专有名词分析专家。请对日语中的专有名词进行分类和翻译。"

    print(f"  Annotating {len(candidates)} candidates with LLM...")
    t0 = time.time()

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 1024},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/chat", data=data,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read().decode("utf-8"))
    response = result.get("message", {}).get("content", "").strip()

    elapsed = time.time() - t0
    print(f"  LLM annotation in {elapsed:.1f}s")

    # Parse LLM response
    annotated = []
    for line in response.split("\n"):
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) >= 3:
            ja = parts[0].strip()
            category = parts[1].strip()
            zh = parts[2].strip()
            # Find frequency
            freq = 0
            for c in candidates:
                if c["ja"] == ja:
                    freq = c["freq"]
                    break
            annotated.append({
                "ja": ja,
                "zh": zh,
                "category": category,
                "freq": freq,
                "source": "llm",
            })

    return annotated


def generate_glossary(annotated: List[dict]) -> str:
    """Generate glossary JSON from annotated terms."""
    terms = []
    for item in annotated:
        if item["category"] in ("character", "place", "term"):
            terms.append({
                "ja": item["ja"],
                "zh": item["zh"],
                "category": item["category"],
                "freq": item["freq"],
            })

    glossary = {
        "generated_by": "discover_terms.py",
        "model": LLM_MODEL,
        "total_candidates": len(annotated),
        "terms": terms,
    }

    return json.dumps(glossary, ensure_ascii=False, indent=2)


# ============ Evaluate ============

def evaluate():
    print("\n============================================================")
    print("S13.1 TERM DISCOVERY EVALUATION")
    print("============================================================")

    # Test data: K-On! ASR text samples
    test_text = """おはよう 唯 おはよう
澪 ちゃん 一緒に 練習 しない 澪
今日 も 元気 だ ね 唯
ありがとう 唯 じゃあ 放課後 ね
軽音部 に 入りたい です
私 は 秋山澪 です ベース 担当 です
田井中律 ドラム 担当 です
琴吹紬 キーボード 担当 です
平沢唯 ギター 担当 です
武道館 で 演奏 したい です
文化祭 の 準備 を しよう
音楽室 で お茶 を 飲み ましょう
さわ子 先生 が 来た
憂 ちゃん が お弁当 を 作って くれた
真鍋和 は 生徒会長 です
軽音部 軽音部 軽音部
唯 澪 律 紬
武道館 武道館
文化祭 文化祭
"""

    print(f"\nTest text length: {len(test_text)} chars")

    # Test 1: Candidate extraction
    print("\n--- Test 1: Candidate extraction ---")
    candidates = extract_candidates(test_text, min_freq=2, min_len=2)
    print(f"  Found {len(candidates)} candidates:")
    for c in candidates[:10]:
        print(f"    {c['ja']} (freq={c['freq']})")
    assert len(candidates) > 0
    print("  Candidate extraction: OK")

    # Test 2: Frequency filtering
    print("\n--- Test 2: Frequency filtering ---")
    frequent = [c for c in candidates if c["freq"] >= 2]
    print(f"  Candidates with freq>=2: {len(frequent)}")
    has_keit = any("軽音部" in c["ja"] for c in frequent)
    print(f"  '軽音部' captured: {has_keit}")
    assert has_keit, "軽音部 should be captured"
    print("  Frequency filtering: OK")

    # Test 3: LLM annotation
    print("\n--- Test 3: LLM annotation ---")
    try:
        annotated = annotate_with_llm(candidates[:15])
        if annotated:
            print(f"  Annotated {len(annotated)} terms:")
            for a in annotated[:8]:
                print(f"    {a['ja']} [{a['category']}] -> {a['zh']}")
            assert len(annotated) > 0
            print("  LLM annotation: OK")
        else:
            print("  LLM annotation: no results (model may be unavailable)")
    except Exception as e:
        print(f"  LLM annotation: SKIPPED ({e})")
        annotated = [{"ja": c["ja"], "zh": c["ja"], "category": "term",
                       "freq": c["freq"], "source": "rule"}
                      for c in candidates[:10]]

    # Test 4: Glossary generation
    print("\n--- Test 4: Glossary generation ---")
    glossary_json = generate_glossary(annotated)
    glossary = json.loads(glossary_json)
    print(f"  Generated glossary: {glossary['total_candidates']} terms")
    for t in glossary["terms"][:5]:
        print(f"    {t['ja']} [{t['category']}] -> {t['zh']}")
    print("  Glossary generation: OK")

    # Save results
    out_path = project_root / "docs" / "evaluation" / "S13.1_discovery_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "test": "S13.1 Term Discovery",
            "candidates": candidates[:20],
            "annotated": annotated,
            "glossary": glossary,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved: {out_path}")

    print("\n============================================================")
    print("EVALUATION COMPLETE")
    print("============================================================")


# ============ CLI ============

def main():
    parser = argparse.ArgumentParser(description="S13.1 Term Discovery")
    parser.add_argument("--input", type=str, help="Input text file or segments JSON")
    parser.add_argument("--output", type=str, default="", help="Output glossary JSON")
    parser.add_argument("--llm", action="store_true", help="Use LLM for annotation")
    parser.add_argument("--min-freq", type=int, default=MIN_FREQ, help="Minimum frequency")
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()

    if args.evaluate:
        evaluate()
        return

    if args.input:
        text = load_text(args.input)
        print(f"Loaded text: {len(text)} chars")

        candidates = extract_candidates(text, min_freq=args.min_freq)
        print(f"Found {len(candidates)} candidates")

        if args.llm:
            annotated = annotate_with_llm(candidates)
        else:
            annotated = [{"ja": c["ja"], "zh": c["ja"], "category": "candidate",
                           "freq": c["freq"], "source": "rule"}
                          for c in candidates]

        glossary_json = generate_glossary(annotated)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(glossary_json)
            print(f"Glossary saved: {args.output}")
        else:
            print(glossary_json)
        return

    parser.print_help()


if __name__ == "__main__":
    main()