# S14.2: Series memory - cross-episode consistency for character names/speech/relationships
#
# series_memory.json format:
# {
#   "series_name": "K-On!",
#   "characters": {
#     "Yui": {
#       "full_name_ja": "平沢唯",
#       "full_name_zh": "平泽唯",
#       "nicknames": ["唯", "小唯"],
#       "speech_style": "genki, casual, sometimes airheaded",
#       "relationships": {"Mio": "friend", "Ritsu": "friend", "Tsumugi": "friend"},
#       "catchphrases": ["ふにゃふにゃ"]
#     }
#   },
#   "terms": {
#     "軽音部": {"zh": "轻音部", "description": "club name"},
#     "放課後": {"zh": "放学后", "description": "time reference"}
#   },
#   "notes": "First-year high school girls in light music club."
# }
#
# Usage:
#   python scripts/series_memory.py --create --series "K-On!" --output memory.json
#   python scripts/series_memory.py --add-char memory.json --name "Yui" --ja "平沢唯" --zh "平泽唯"
#   python scripts/series_memory.py --view memory.json
#   python scripts/series_memory.py --inject memory.json --prompt "将下面的日语文本翻译成中文：..."

import json, os, sys, argparse
from pathlib import Path
from typing import Optional

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
K_ON_MEMORY_PATH = project_root / "data" / "series_memory" / "k-on_s1.json"


class SeriesMemory:
    """Cross-episode consistency memory for a series."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path) if path else None
        self.data = self._default()
        if self.path and self.path.exists():
            self.load()

    def _default(self):
        return {
            "series_name": "",
            "characters": {},
            "terms": {},
            "notes": "",
            "version": "1.0",
        }

    def load(self):
        with open(self.path, encoding="utf-8") as f:
            loaded = json.load(f)
            for key in self._default():
                if key not in loaded:
                    loaded[key] = self._default()[key]
            self.data = loaded
        print(f"Loaded memory: {self.path.name} ({len(self.data['characters'])} characters, {len(self.data['terms'])} terms)")

    def save(self):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        print(f"Saved: {self.path} ({len(self.data['characters'])} characters)")

    def add_character(self, name_key: str, full_name_ja: str, full_name_zh: str,
                       nicknames: list = None, speech_style: str = "",
                       relationships: dict = None, catchphrases: list = None):
        self.data["characters"][name_key] = {
            "full_name_ja": full_name_ja,
            "full_name_zh": full_name_zh,
            "nicknames": nicknames or [],
            "speech_style": speech_style,
            "relationships": relationships or {},
            "catchphrases": catchphrases or [],
        }
        self.save()

    def add_term(self, ja: str, zh: str, description: str = ""):
        self.data["terms"][ja] = {"zh": zh, "description": description}
        self.save()

    def get_character(self, name_key: str) -> dict:
        return self.data["characters"].get(name_key, {})

    def get_term(self, ja: str) -> Optional[str]:
        term = self.data["terms"].get(ja)
        return term["zh"] if term else None

    def to_prompt_block(self) -> str:
        """Format series memory as prompt block for injection."""
        lines = []
        lines.append(f"[系列：{self.data['series_name']}]")

        if self.data["notes"]:
            lines.append("\n系列说明：")
            lines.append(f"  {self.data['notes']}")

        if self.data["characters"]:
            lines.append("\n角色与说话风格：")
            for name, info in self.data["characters"].items():
                nick = ", ".join(info["nicknames"]) if info["nicknames"] else ""
                style = f" ({info['speech_style']})" if info["speech_style"] else ""
                rels = "; ".join(f"{k}: {v}" for k, v in info["relationships"].items()) if info["relationships"] else ""
                catchphrases = ", ".join(info["catchphrases"]) if info["catchphrases"] else ""
                lines.append(f"  {info['full_name_zh']} ({info['full_name_ja']}){style}")
                if nick:
                    lines.append(f"    称呼映射: {nick}")
                if rels:
                    lines.append(f"    关系: {rels}")
                if catchphrases:
                    lines.append(f"    固定说法: {catchphrases}")

        if self.data["terms"]:
            lines.append("\n系列固定术语：")
            for ja, info in sorted(
                self.data["terms"].items(),
                key=lambda item: len(item[0]),
                reverse=True,
            ):
                desc = f" ({info['description']})" if info["description"] else ""
                lines.append(f"  {ja} -> {info['zh']}{desc}")

        return "\n".join(lines)

    def inject_into_prompt(self, prompt: str) -> str:
        """Inject series memory into a translation prompt."""
        block = self.to_prompt_block()
        return f"{block}\n\n{prompt}"

    def merge(self, other: "SeriesMemory"):
        """Merge another SeriesMemory into this one."""
        for name_key, info in other.data["characters"].items():
            if name_key not in self.data["characters"]:
                self.data["characters"][name_key] = info
        for ja, info in other.data["terms"].items():
            if ja not in self.data["terms"]:
                self.data["terms"][ja] = info
        self.save()


def create_k_on_memory() -> SeriesMemory:
    """Load the production K-On! season-one memory shipped with the project."""
    if not K_ON_MEMORY_PATH.exists():
        raise FileNotFoundError(f"K-On! series memory is missing: {K_ON_MEMORY_PATH}")
    return SeriesMemory(str(K_ON_MEMORY_PATH))


# ============ Evaluate ============

def evaluate():
    print("\n============================================================")
    print("S14.2 SERIES MEMORY EVALUATION")
    print("============================================================")

    # Test 1: Create K-On! memory
    print("\n--- Test 1: Create K-On! memory ---")
    mem = create_k_on_memory()
    print(f"  Characters: {len(mem.data['characters'])}")
    print(f"  Terms: {len(mem.data['terms'])}")
    assert len(mem.data["characters"]) == 9
    assert len(mem.data["terms"]) == 20
    print("  Memory creation: OK")

    # Test 2: Prompt injection
    print("\n--- Test 2: Prompt injection ---")
    prompt = "将下面的日语文本翻译成中文：おはよう"
    injected = mem.inject_into_prompt(prompt)
    assert "平泽唯" in injected
    assert "轻音部" in injected
    assert "将下面的日语文本翻译成中文" in injected
    print(f"  Injected length: {len(injected)} chars")
    print(f"  Contains characters: {'平泽唯' in injected}")
    print(f"  Contains terms: {'軽音部' in injected}")
    print("  Prompt injection: OK")

    # Test 3: Save and reload
    print("\n--- Test 3: Save and reload ---")
    import tempfile
    tmp_path = Path(tempfile.mkdtemp()) / "k-on_memory.json"
    mem.path = tmp_path
    mem.save()

    mem2 = SeriesMemory(str(tmp_path))
    assert len(mem2.data["characters"]) == 9
    assert len(mem2.data["terms"]) == 20
    assert mem2.get_term("軽音部") == "轻音部"
    print("  Save and reload: OK")

    # Test 4: Get character info
    print("\n--- Test 4: Character info ---")
    mio = mem2.get_character("Mio")
    assert mio["full_name_zh"] == "秋山澪"
    assert "害羞" in mio["speech_style"]
    print(f"  Mio: {mio['full_name_zh']}, speech: {mio['speech_style']}")
    print("  Character info: OK")

    # Test 5: Prompt block format
    print("\n--- Test 5: Prompt block ---")
    block = mem2.to_prompt_block()
    print(f"  Block length: {len(block)} chars")
    print(f"  First 5 lines:\n{chr(10).join(block.split(chr(10))[:5])}")
    print("  Prompt block: OK")

    # Cleanup
    import shutil
    shutil.rmtree(tmp_path.parent, ignore_errors=True)

    print("\n============================================================")
    print("ALL TESTS PASSED")
    print("============================================================")


# ============ CLI ============

def main():
    parser = argparse.ArgumentParser(description="S14.2 Series Memory")
    parser.add_argument("--create", action="store_true", help="Create new series memory")
    parser.add_argument("--series", type=str, help="Series name")
    parser.add_argument("--output", type=str, default="series_memory.json", help="Output file")
    parser.add_argument("--input", type=str, help="Input memory file")
    parser.add_argument("--add-char", nargs=4, metavar=("KEY", "JA", "ZH", "STYLE"),
                        help="Add character: KEY JA ZH STYLE")
    parser.add_argument("--add-term", nargs=3, metavar=("JA", "ZH", "DESC"),
                        help="Add term: JA ZH DESC")
    parser.add_argument("--view", type=str, help="View memory file")
    parser.add_argument("--inject", type=str, help="Inject memory into prompt; use with --prompt")
    parser.add_argument("--prompt", type=str, help="Translation prompt")
    parser.add_argument("--sample", action="store_true", help="Create K-On! sample memory")
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()

    if args.evaluate:
        evaluate()
        return

    if args.sample:
        mem = create_k_on_memory()
        mem.path = Path(args.output)
        mem.save()
        return

    if args.create and args.series:
        mem = SeriesMemory()
        mem.data["series_name"] = args.series
        mem.path = Path(args.output)
        mem.save()
        print(f"Created empty memory for '{args.series}'")
        return

    if args.add_char and args.input:
        mem = SeriesMemory(args.input)
        mem.add_character(args.add_char[0], args.add_char[1], args.add_char[2],
                           speech_style=args.add_char[3])
        return

    if args.add_term and args.input:
        mem = SeriesMemory(args.input)
        mem.add_term(args.add_term[0], args.add_term[1], args.add_term[2])
        return

    if args.view:
        mem = SeriesMemory(args.view)
        print(mem.to_prompt_block())
        return

    if args.inject and args.prompt:
        mem = SeriesMemory(args.inject)
        result = mem.inject_into_prompt(args.prompt)
        print(result)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
