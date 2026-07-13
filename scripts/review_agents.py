# S11.2: Multi-Agent review - 5 parallel agents + editor merge + auto-fix
#
# 5 review agents (parallel Ollama calls):
#   1. Consistency - character names, term consistency
#   2. Naturalness - translation fluency, natural Chinese
#   3. Accuracy - faithfulness to Japanese original
#   4. ASR Check - suspicious ASR output detection
#   5. Style - tone, formality, speaking style
#
# Editor agent: merges conflicts, produces final corrected version
#
# Usage:
#   python scripts/review_agents.py --input segments.json --output reviewed.json
#   python scripts/review_agents.py --input segments.json --output reviewed.json --dry-run

import json, os, sys, time, argparse, urllib.request
from pathlib import Path
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "localhost")
OLLAMA_URL = f"http://{OLLAMA_HOST}:11434/api"
MODEL = os.environ.get("REVIEW_MODEL", "EasonONLINE/Sakura-qwen2.5-v1.0:7b")


def ollama_chat(messages, temperature=0.3):
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


# ============ Agent Definitions ============

AGENTS = {
    "consistency": {
        "name": "Consistency Checker",
        "system": "你是一个字幕一致性审查专家。检查翻译中的角色名、术语是否一致。"
                  "如果发现不一致，请指出并给出修正建议。"
                  "输出格式：每一行用 [OK] 或 [FIX] 开头。",
        "prompt_template": (
            "请检查以下翻译中角色名和术语的一致性：\n\n"
            "日文原文：{ja}\n中文翻译：{zh}\n\n"
            "检查点：\n"
            "1. 角色名是否与上下文一致\n"
            "2. 同一角色在不同地方是否用相同译名\n"
            "3. 术语（如乐器名、地点名）翻译是否一致\n\n"
            "如果没问题，只输出 [OK]。如果需要修改，输出 [FIX] 并给出修正后的完整翻译。"
        ),
    },
    "naturalness": {
        "name": "Naturalness Checker",
        "system": "你是一个中文表达自然度审查专家。检查翻译是否通顺、自然、符合口语习惯。"
                  "输出格式：每一行用 [OK] 或 [FIX] 开头。",
        "prompt_template": (
            "请检查以下中文翻译的自然度：\n\n"
            "日文原文：{ja}\n中文翻译：{zh}\n\n"
            "检查点：\n"
            "1. 是否通顺自然\n"
            "2. 是否符合中文口语习惯\n"
            "3. 是否有生硬或翻译腔\n\n"
            "如果没问题，只输出 [OK]。如果需要修改，输出 [FIX] 并给出修正后的翻译。"
        ),
    },
    "accuracy": {
        "name": "Accuracy Checker",
        "system": "你是一个翻译准确性审查专家。检查中文翻译是否忠实反映日文原文的含义。"
                  "输出格式：每一行用 [OK] 或 [FIX] 开头。",
        "prompt_template": (
            "请检查以下翻译的准确性：\n\n"
            "日文原文：{ja}\n中文翻译：{zh}\n\n"
            "检查点：\n"
            "1. 是否准确传达了原文意思\n"
            "2. 是否有漏译或过度翻译\n"
            "3. 语气和情感是否匹配\n\n"
            "如果没问题，只输出 [OK]。如果需要修改，输出 [FIX] 并给出修正后的翻译。"
        ),
    },
    "asr_check": {
        "name": "ASR Quality Checker",
        "system": "你是一个 ASR 输出审查专家。检查日文原文是否可能是 ASR 识别错误。"
                  "输出格式：每一行用 [OK] 或 [FIX] 或 [SUSPICIOUS] 开头。",
        "prompt_template": (
            "请检查以下 ASR 输出是否合理：\n\n"
            "日文原文：{ja}\n中文翻译：{zh}\n\n"
            "检查点：\n"
            "1. 日文原文是否通顺合理\n"
            "2. 是否有重复、断裂或奇怪的片段\n"
            "3. 翻译是否与日文原文匹配\n\n"
            "如果没问题，输出 [OK]。\n"
            "如果翻译需要微调，输出 [FIX] 并给出修正。\n"
            "如果日文原文可疑但可推测含义，输出 [SUSPICIOUS] 并给出最佳推测翻译。"
        ),
    },
    "style": {
        "name": "Style Checker",
        "system": "你是一个动漫翻译风格审查专家。检查翻译是否符合角色性格和场景氛围。"
                  "输出格式：每一行用 [OK] 或 [FIX] 开头。",
        "prompt_template": (
            "请检查以下翻译的风格是否合适：\n\n"
            "日文原文：{ja}\n中文翻译：{zh}\n\n"
            "检查点：\n"
            "1. 语气是否符合角色性格\n"
            "2. 用词是否适合动漫场景\n"
            "3. 是否有更自然的表达方式\n\n"
            "如果没问题，只输出 [OK]。如果需要修改，输出 [FIX] 并给出修正后的翻译。"
        ),
    },
}


# ============ Review Functions ============

def run_agent(agent_id: str, ja: str, zh: str) -> dict:
    """Run a single review agent."""
    agent = AGENTS[agent_id]
    prompt = agent["prompt_template"].format(ja=ja, zh=zh)

    t0 = time.time()
    try:
        response = ollama_chat([
            {"role": "system", "content": agent["system"]},
            {"role": "user", "content": prompt},
        ])
    except Exception as e:
        response = f"[ERROR] {e}"
    elapsed = time.time() - t0

    # Parse response - be lenient
    response_lower = response.lower()
    is_ok = any(x in response_lower for x in ["[ok]", "没有问题", "没问题", "不需要修改"])
    is_fix = response.startswith("[FIX]")
    is_suspicious = response.startswith("[SUSPICIOUS]")

    verdict = "ok"
    if is_fix:
        verdict = "fix"
    elif is_suspicious:
        verdict = "suspicious"
    elif not response or response.startswith("[ERROR]"):
        verdict = "error"
    elif len(response) < 3:
        verdict = "error"

    # Extract fixed translation if [FIX]
    fixed_zh = None
    if is_fix:
        # Try to extract the fixed translation from the response
        lines = response.split("\n")
        for line in lines:
            line = line.strip()
            if line and not line.startswith("[") and len(line) > 2:
                fixed_zh = line
                break

    return {
        "agent": agent_id,
        "agent_name": agent["name"],
        "ja": ja,
        "zh": zh,
        "response": response,
        "verdict": "ok" if is_ok else ("fix" if is_fix else ("suspicious" if is_suspicious else "error")),
        "fixed_zh": fixed_zh,
        "time_s": round(elapsed, 2),
    }


def review_segment(ja: str, zh: str) -> dict:
    """Run all 5 agents in parallel on one segment, then run editor."""
    results = {}

    # Run all 5 agents in parallel
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(run_agent, agent_id, ja, zh): agent_id
            for agent_id in AGENTS
        }
        for future in as_completed(futures):
            agent_id = futures[future]
            try:
                results[agent_id] = future.result()
            except Exception as e:
                results[agent_id] = {"agent": agent_id, "error": str(e)}

    # Check if any agent requested a fix
    needs_fix = any(
        r.get("verdict") in ("fix", "suspicious")
        for r in results.values()
    )

    # Collect fixed versions
    fixes = {
        aid: r["fixed_zh"]
        for aid, r in results.items()
        if r.get("fixed_zh")
    }

    # Run editor if fixes exist
    editor_result = None
    if fixes:
        editor_result = run_editor(ja, zh, results)

    return {
        "ja": ja,
        "zh": zh,
        "agent_results": results,
        "needs_fix": needs_fix,
        "fixes": fixes,
        "editor_result": editor_result,
    }


def run_editor(ja: str, zh: str, agent_results: dict) -> dict:
    """Editor agent: merges agent feedback into final corrected version."""
    # Collect all feedback
    feedback_lines = []
    for aid, result in agent_results.items():
        verdict = result.get("verdict", "ok")
        response = result.get("response", "")
        feedback_lines.append(f"[{aid}] {verdict}: {response[:200]}")

    feedback = "\n".join(feedback_lines)

    system = "你是一个字幕审查总编。多个审查 Agent 对翻译提出了修改意见，请综合所有意见，给出最终修正版本。"
    prompt = (
        f"日文原文：{ja}\n"
        f"原始翻译：{zh}\n\n"
        f"审查意见：\n{feedback}\n\n"
        f"请综合所有意见，输出最终修正后的中文翻译。只输出翻译结果，不要输出任何说明。"
    )

    t0 = time.time()
    try:
        response = ollama_chat([
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ], temperature=0.2)
    except Exception as e:
        response = zh  # Fallback to original
    elapsed = time.time() - t0

    return {
        "original_zh": zh,
        "corrected_zh": response.strip(),
        "time_s": round(elapsed, 2),
    }


# ============ Batch Review ============

def review_batch(segments: list, max_workers: int = 3) -> list:
    """Review a batch of segments."""
    results = []
    total = len(segments)

    print(f"Reviewing {total} segments with {len(AGENTS)} agents each...")
    print(f"Model: {MODEL}")

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(review_segment, s["ja"], s["zh"]): i
            for i, s in enumerate(segments)
        }
        for future in as_completed(futures):
            i = futures[future]
            try:
                result = future.result()
                results.append(result)
                ja = result["ja"][:30]
                needs = "FIX" if result["needs_fix"] else "OK"
                editor = ""
                if result.get("editor_result"):
                    editor = f" -> {result['editor_result']['corrected_zh'][:30]}"
                print(f"  [{i+1}/{total}] {needs}: {ja}...{editor}")
            except Exception as e:
                print(f"  [{i+1}/{total}] ERROR: {e}")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print(f"  Segments needing fix: {sum(1 for r in results if r['needs_fix'])}/{total}")

    # Sort by original index
    results.sort(key=lambda r: segments.index(
        next(s for s in segments if s["ja"] == r["ja"])))

    return results


# ============ Test Data ============

def create_test_segments():
    return [
        {"ja": "おはよう、唯", "zh": "早安，唯"},
        {"ja": "今日も元気だね", "zh": "今天也很有精神呢"},
        {"ja": "澪ちゃん、一緒に練習しない？", "zh": "澪，要不要一起练习？"},
        {"ja": "ありがとう、唯。じゃあ放課後ね", "zh": "谢谢你，唯。那放学后见"},
    ]


# ============ Evaluate ============

def evaluate():
    print("\n============================================================")
    print("S11.2 MULTI-AGENT REVIEW EVALUATION")
    print("============================================================")
    print(f"Agents: {len(AGENTS)}")
    for aid, info in AGENTS.items():
        print(f"  {aid}: {info['name']}")
    print(f"\nTesting with {len(create_test_segments())} segments...\n")

    segments = create_test_segments()
    results = review_batch(segments, max_workers=2)

    # Save results
    out_path = project_root / "docs" / "evaluation" / "S11.2_review_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "model": MODEL,
            "agents": list(AGENTS.keys()),
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved: {out_path}")

    # Print summary
    print("\n--- Review Summary ---")
    for r in results:
        print(f"\n  JA: {r['ja']}")
        print(f"  ZH: {r['zh']}")
        if r.get("editor_result"):
            print(f"  CORRECTED: {r['editor_result']['corrected_zh']}")
        for aid, ar in r["agent_results"].items():
            verdict_icon = {"ok": "OK", "fix": "FIX", "suspicious": "?", "error": "ERR"}.get(ar.get("verdict", ""), "?")
            print(f"    [{verdict_icon}] {ar['agent_name']}")

    print("\n============================================================")
    print("EVALUATION COMPLETE")
    print("============================================================")


def main():
    parser = argparse.ArgumentParser(description="S11.2 Multi-Agent Review")
    parser.add_argument("--input", type=str, help="Input JSON segments file")
    parser.add_argument("--output", type=str, default="", help="Output JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Run agents but don't apply fixes")
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()

    if args.evaluate:
        evaluate()
        return

    if args.input:
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)
        results = review_batch(data)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"Saved: {args.output}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()