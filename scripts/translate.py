"""S9.1: Context window translation module.

Translates Japanese anime dialogue to Chinese using Ollama Sakura models,
with optional surrounding context for better consistency.

Usage:
  python scripts/translate.py --text "日本語のテキスト"
  python scripts/translate.py --text "日本語" --context-before "前の文" --context-after "後の文"
  python scripts/translate.py --batch examples.json --context-window 3
  python scripts/translate.py --evaluate  # Run context vs no-context comparison
"""

import json, os, sys, time, argparse, re
from pathlib import Path
import urllib.request

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from scripts.glossary import Glossary
from scripts.translation_memory import TranslationMemory

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "localhost")
OLLAMA_URL = f"http://{OLLAMA_HOST}:11434/api"
DEFAULT_MODEL = os.environ.get("TRANSLATION_MODEL", "EasonONLINE/Sakura-qwen2.5-v1.0:7b")
DEFAULT_GLOSSARY = os.environ.get("GLOSSARY_FILE", "")
DEFAULT_TM = os.environ.get("TM_FILE", "")


def ollama_chat(model, messages, temperature=0.1):
    """Send chat request to Ollama."""
    payload = {
        "model": model,
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


def translate(text, context_before=None, context_after=None, model=DEFAULT_MODEL,
              glossary=None, tm=None):
    """Translate Japanese text to Chinese with optional context, glossary, and TM.

    Args:
        text: Japanese text to translate
        context_before: Previous sentences
        context_after: Next sentences
        model: Ollama model name
        glossary: Glossary object or path
        tm: TranslationMemory object or path

    Returns:
        Translated Chinese text
    """
    # Load glossary if path provided
    if isinstance(glossary, (str, Path)):
        g = Glossary(str(glossary))
    elif isinstance(glossary, Glossary):
        g = glossary
    else:
        g = None

    # Load TM if path provided
    if isinstance(tm, (str, Path)):
        tm_obj = TranslationMemory(str(tm))
    elif isinstance(tm, TranslationMemory):
        tm_obj = tm
    else:
        tm_obj = None

    # Check TM first
    if tm_obj:
        cached = tm_obj.lookup(text)
        if cached:
            return cached

    # Build prompt
    context_parts = []

    if context_before:
        if isinstance(context_before, str):
            context_before = [context_before]
        ctx = "\n".join(context_before)
        context_parts.append(f"上文：\n{ctx}")

    context_parts.append(f"当前：\n{text}")

    if context_after:
        if isinstance(context_after, str):
            context_after = [context_after]
        ctx = "\n".join(context_after)
        context_parts.append(f"下文：\n{ctx}")

    if context_before or context_after:
        # Build conversation history as context
        ctx_lines = []
        if context_before:
            ctx_lines.append("对话历史：")
            for line in context_before if isinstance(context_before, list) else [context_before]:
                ctx_lines.append(f"- {line}")
        
        ctx_lines.append(f"当前句子：{text}")
        
        if context_after:
            ctx_lines.append("后续句子（仅供参考）：")
            for line in context_after if isinstance(context_after, list) else [context_after]:
                ctx_lines.append(f"- {line}")
        
        full_input = "\n".join(ctx_lines)
        
        # Inject glossary
        if g:
            full_input = g.inject_into_prompt(full_input, position="before")
        
        prompt = f"请翻译当前句子。只输出翻译结果，不要重复上下文。\n\n{full_input}"
        system_msg = "你是一个轻小说翻译模型，将日语翻译成中文。只输出翻译结果，不要输出其他内容。"
    else:
        # Simple translation
        user_text = text
        if g:
            user_text = g.inject_into_prompt(text, position="before")
        system_msg = "你是一个轻小说翻译模型，可以将日语翻译成中文。"
        prompt = f"将下面的日语文本翻译成中文：{user_text}"

    messages = []
    if system_msg:
        messages.append({"role": "system", "content": system_msg})
    messages.append({"role": "user", "content": prompt})

    result = ollama_chat(model, messages)

    # Store in TM
    if tm_obj and result:
        tm_obj.store(text, result, model=model)

    return result


def translate_batch(sentences, context_window=3, model=DEFAULT_MODEL):
    """Translate a batch of sentences with context window.

    Args:
        sentences: List of dicts with at least {"ja": "..."}
                  Optionally {"ja": "...", "zh_ref": "..."}
        context_window: Number of preceding/following sentences to include
        model: Ollama model name

    Returns:
        List of dicts with added "zh" and "zh_no_context" fields
    """
    results = []
    n = len(sentences)

    for i, sent in enumerate(sentences):
        ja = sent["ja"]

        # Build context
        before = []
        for j in range(max(0, i - context_window), i):
            before.append(sentences[j].get("ja_orig", sentences[j]["ja"]))

        after = []
        for j in range(i + 1, min(n, i + context_window + 1)):
            after.append(sentences[j].get("ja_orig", sentences[j]["ja"]))

        # With context
        t0 = time.time()
        zh = translate(ja, context_before=before, context_after=after, model=model)
        t_with = time.time() - t0

        # Without context (for comparison, run occasionally)
        zh_no_context = None
        t_without = None
        if i % 3 == 0:  # Compare every 3rd sentence
            t0 = time.time()
            zh_no_context = translate(ja, model=model)
            t_without = time.time() - t0

        result = {
            "index": i,
            "ja": ja,
            "zh": zh,
            "zh_no_context": zh_no_context,
            "zh_ref": sent.get("zh_ref"),
            "context_before": before if before else None,
            "context_after": after if after else None,
            "time_with_context_s": round(t_with, 2),
            "time_without_context_s": round(t_without, 2) if t_without else None,
        }
        results.append(result)

        status = "✓" if zh else "✗"
        print(f"  [{i+1}/{n}] {ja[:30]} -> {zh[:40]} ({t_with:.1f}s) {status}")

    return results


# ======== Test data ========

SEQUENTIAL_TEST_DATA = [
    {"ja": "おはよう、唯", "zh_ref": "早安，唯"},
    {"ja": "あ、おはようございます！", "zh_ref": "啊，早上好！"},
    {"ja": "今日も元気だね", "zh_ref": "今天也很有精神呢"},
    {"ja": "はい！昨日新しいギターの練習したんです", "zh_ref": "是的！昨天练习了新吉他"},
    {"ja": "そうなんだ。上手くなった？", "zh_ref": "这样啊。有进步吗？"},
    {"ja": "まだまだですけど、楽しいです！", "zh_ref": "还差得远，但是很开心！"},
    {"ja": "澪ちゃん、一緒に練習しない？", "zh_ref": "小澪，要不要一起练习？"},
    {"ja": "いいよ。でも私、まだベース下手だから", "zh_ref": "好啊。不过我的贝斯还弹得很差"},
    {"ja": "そんなことないよ！澪ちゃんは上手だよ", "zh_ref": "没那回事！小澪弹得很好"},
    {"ja": "ありがとう、唯。じゃあ放課後ね", "zh_ref": "谢谢，唯。那放学后见"},
]


# ======== Evaluation ========

def evaluate_context(glossary=None):
    """Compare translations with vs without context."""
    print(f"{'='*70}")
    print("CONTEXT WINDOW EVALUATION")
    print(f"{'='*70}")
    print(f"\nModel: {DEFAULT_MODEL}")
    print(f"Samples: {len(SEQUENTIAL_TEST_DATA)}")
    print(f"Context window: 3 before + 3 after")
    if glossary:
        print(f"Glossary: {glossary}")

    results = translate_batch(
        SEQUENTIAL_TEST_DATA,
        context_window=3,
        model=DEFAULT_MODEL,
    )

    # Compare
    print(f"\n{'='*70}")
    print("COMPARISON: With Context vs Without Context")
    print(f"{'='*70}")

    for r in results:
        if r["zh_no_context"] is None:
            continue
        print(f"\n  JA: {r['ja']}")
        if r["zh_ref"]:
            print(f"  REF: {r['zh_ref']}")
        print(f"  WITH ctx: {r['zh']}")
        print(f"  NO  ctx: {r['zh_no_context']}")

    # Save results
    out_path = project_root / "docs" / "evaluation" / "S9.1_context_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "model": DEFAULT_MODEL,
            "samples": results,
            "config": {"context_window": 3},
        }, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out_path}")
    return results


# ======== CLI ========

def main():
    parser = argparse.ArgumentParser(description="S9.1 Context Window Translation")
    parser.add_argument("--text", type=str, help="Japanese text to translate")
    parser.add_argument("--context-before", type=str, help="Previous sentence(s)")
    parser.add_argument("--context-after", type=str, help="Next sentence(s)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--glossary", type=str, default=DEFAULT_GLOSSARY,
                        help="Glossary file path (JSON or text)")
    parser.add_argument("--evaluate", action="store_true", help="Run context comparison")
    parser.add_argument("--batch", type=str, help="JSON file with batch sentences")
    parser.add_argument("--context-window", type=int, default=3)
    args = parser.parse_args()

    # Load glossary if specified
    glossary = None
    if args.glossary:
        glossary = Glossary(args.glossary)
        print(f"Loaded glossary: {glossary}")

    if args.evaluate:
        evaluate_context(glossary=glossary)
        return

    if args.text:
        cb = args.context_before.split("||") if args.context_before else None
        ca = args.context_after.split("||") if args.context_after else None
        result = translate(args.text, cb, ca, args.model, glossary)
        print(result)
        return

    if args.batch:
        with open(args.batch, encoding="utf-8") as f:
            sentences = json.load(f)
        results = translate_batch(sentences, args.context_window, args.model)
        print(f"\nDone: {len(results)} sentences")
        return

    parser.print_help()


if __name__ == "__main__":
    main()