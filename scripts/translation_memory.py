"""S9.3: Translation Memory system.

JSONL-based bilingual cache with exact-match lookup.

Format (JSONL):
  {"ja": "...", "zh": "...", "model": "...", "translation_fallback": false,
   "timestamp": "..."}

Usage:
  tm = TranslationMemory("data/translation_memory.jsonl")
  zh = tm.lookup("おはよう")       # Returns cached translation or None
  tm.store("おはよう", "早上好")   # Saves new translation
  tm.save()                        # Flush to disk
"""

import json, os, time
from pathlib import Path
from typing import Optional


class TranslationMemory:
    """Bilingual translation memory with JSONL persistence."""

    def __init__(self, path: Optional[str] = None, auto_save: bool = True):
        self.path = Path(path) if path else None
        self.auto_save = auto_save
        self._cache: dict[str, dict] = {}  # ja -> {zh, model, timestamp}
        self._dirty = False
        self._stats = {"hits": 0, "misses": 0, "stored": 0}
        if self.path and self.path.exists():
            self.load()

    def load(self):
        """Load translation memory from JSONL file."""
        if not self.path or not self.path.exists():
            return
        count = 0
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ja = entry.get("ja", "")
                    if ja:
                        self._cache[ja] = entry
                        count += 1
                except json.JSONDecodeError:
                    continue
        print(f"  TM loaded: {count} entries from {self.path}")

    def save(self):
        """Flush cache to JSONL file."""
        if not self.path or not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            for ja, entry in sorted(self._cache.items()):
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._dirty = False
        print(f"  TM saved: {len(self._cache)} entries to {self.path}")

    def lookup(self, ja: str) -> Optional[str]:
        """Look up translation. Returns zh or None."""
        entry = self.lookup_entry(ja)
        return entry.get("zh") if entry else None

    def lookup_entry(self, ja: str) -> Optional[dict]:
        """Look up a translation and retain model provenance."""
        entry = self._cache.get(ja)
        if entry:
            self._stats["hits"] += 1
            return dict(entry)
        self._stats["misses"] += 1
        return None

    def store(self, ja: str, zh: str, model: str = "", fallback: bool = False):
        """Store a translation pair."""
        if not ja or not zh:
            return
        # Preserve model provenance even when two models produce the same text.
        existing = self._cache.get(ja)
        if (
            existing
            and existing.get("zh") == zh
            and existing.get("model", "") == model
            and bool(existing.get("translation_fallback", False)) == fallback
        ):
            return
        self._cache[ja] = {
            "ja": ja,
            "zh": zh,
            "model": model,
            "translation_fallback": fallback,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self._dirty = True
        self._stats["stored"] += 1
        if self.auto_save:
            self.save()

    def contains(self, ja: str) -> bool:
        return ja in self._cache

    def count(self) -> int:
        return len(self._cache)

    def stats(self) -> dict:
        s = dict(self._stats)
        s["total"] = len(self._cache)
        hit_rate = s["hits"] / (s["hits"] + s["misses"]) * 100 if (s["hits"] + s["misses"]) > 0 else 0
        s["hit_rate"] = round(hit_rate, 1)
        return s

    def clear(self):
        """Clear all entries."""
        self._cache.clear()
        self._dirty = True

    def __repr__(self):
        return f"TranslationMemory({len(self._cache)} entries, path={self.path})"


# ======== Built-in test ========

def test():
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name

    tm = TranslationMemory(path)
    assert tm.count() == 0

    # Store and lookup
    tm.store("おはよう", "早上好", model="test")
    assert tm.lookup("おはよう") == "早上好"
    assert tm.count() == 1

    # Cross-session: reload
    tm2 = TranslationMemory(path)
    assert tm2.lookup("おはよう") == "早上好"
    assert tm2.stats()["hits"] == 1

    # Miss
    assert tm2.lookup("こんにちは") is None

    # Stats
    s = tm2.stats()
    print(f"Stats: {s}")

    os.unlink(path)
    print("All tests passed!")


if __name__ == "__main__":
    test()
