"""S9.2: Glossary system for translation consistency.

Loads term mappings from JSON or text format, injects into translation prompts.

Formats supported:
  JSON: {"terms": [{"ja": "平沢唯", "zh": "平泽唯"}, ...]}
  Text: 平沢唯-平泽唯, 秋山澪-秋山澪  (JAVTrans compatible)

Usage:
  from glossary import Glossary
  g = Glossary("data/glossary/k-on_glossary.json")
  g.inject_prompt("将下面的日语文本翻译成中文：{text}")
"""

import json, re, os
from pathlib import Path
from typing import List, Optional, Tuple


class Glossary:
    """Term glossary for translation consistency."""

    def __init__(self, source: Optional[str] = None):
        self.terms: List[Tuple[str, str]] = []
        self._ja_to_zh: dict = {}
        if source:
            self.load(source)

    def load(self, source: str):
        """Load glossary from JSON file or text string."""
        path = Path(source)
        if path.exists():
            with open(path, encoding="utf-8") as f:
                raw = f.read()
            if source.endswith(".json"):
                self._load_json(raw)
            else:
                self._load_text(raw)
        else:
            self._load_text(source)

    def _load_json(self, raw: str):
        data = json.loads(raw)
        if isinstance(data, list):
            terms = data
        elif isinstance(data, dict):
            terms = data.get("terms", data.get("entries", []))
        else:
            raise ValueError(f"Unknown glossary format: {type(data)}")

        for item in terms:
            if isinstance(item, dict):
                ja = item.get("ja", item.get("source", item.get("japanese", "")))
                zh = item.get("zh", item.get("target", item.get("chinese", "")))
            elif isinstance(item, (list, tuple)):
                ja, zh = item[0], item[1]
            else:
                continue
            if ja and zh:
                self.add(ja.strip(), zh.strip())

    def _load_text(self, raw: str):
        """Parse JAVTrans-compatible text format:  source-target, ..."""
        for item in re.split(r"[,，\n]+", raw):
            item = item.strip()
            if not item:
                continue
            for sep in ["→", "->", "-"]:
                if sep in item:
                    parts = item.split(sep, 1)
                    ja, zh = parts[0].strip(), parts[1].strip()
                    if ja and zh:
                        self.add(ja, zh)
                    break

    def add(self, ja: str, zh: str):
        """Add a single term mapping."""
        self.terms.append((ja, zh))
        self._ja_to_zh[ja] = zh

    def get(self, ja: str) -> Optional[str]:
        """Get Chinese translation for a Japanese term."""
        return self._ja_to_zh.get(ja)

    def to_prompt_block(self) -> str:
        """Format glossary as prompt block for injection."""
        if not self.terms:
            return ""
        lines = ["以下术语表的翻译必须严格遵守："]
        for ja, zh in self.terms:
            lines.append(f"  {ja} -> {zh}")
        return "\n".join(lines)

    def to_text(self) -> str:
        """Export to JAVTrans-compatible text format."""
        return ", ".join(f"{ja}-{zh}" for ja, zh in self.terms)

    def to_json(self) -> str:
        """Export to JSON format."""
        return json.dumps([{"ja": ja, "zh": zh} for ja, zh in self.terms],
                          ensure_ascii=False, indent=2)

    def inject_into_prompt(self, prompt: str, position: str = "before") -> str:
        """Inject glossary into a translation prompt.

        Args:
            prompt: Original prompt
            position: "before" (prepend) or "after" (append)

        Returns:
            Prompt with glossary injected
        """
        block = self.to_prompt_block()
        if not block:
            return prompt
        if position == "before":
            return f"{block}\n\n{prompt}"
        else:
            return f"{prompt}\n\n{block}"

    def count(self) -> int:
        return len(self.terms)

    def __len__(self):
        return self.count()

    def __repr__(self):
        return f"Glossary({self.count()} terms)"


# ======== Built-in test ========

def test_glossary():
    """Test glossary functionality."""
    # Test JSON format
    g = Glossary()
    g.add("平沢唯", "平泽唯")
    g.add("秋山澪", "秋山澪")
    g.add("田井中律", "田井中律")
    g.add("琴吹紬", "琴吹䌷")
    assert g.count() == 4
    assert g.get("平沢唯") == "平泽唯"

    # Test prompt injection
    prompt = "将下面的日语文本翻译成中文：おはよう、唯"
    injected = g.inject_into_prompt(prompt)
    assert "术语表" in injected
    assert "平沢唯" in injected
    print(f"Original: {prompt}")
    print(f"Injected: {injected[:100]}...")

    # Test text format (JAVTrans compatible)
    text = g.to_text()
    print(f"Text: {text}")

    # Test JSON export
    print(f"JSON: {g.to_json()[:100]}...")

    print("All tests passed!")


if __name__ == "__main__":
    test_glossary()