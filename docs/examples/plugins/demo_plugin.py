"""Trusted local plugin example: translator, sidecar ASR, and pink ASS style."""

import json
from pathlib import Path

import pysubs2

from scripts.translator_adapter import TranslatorAdapter


class DemoPrefixTranslator(TranslatorAdapter):
    def __init__(self, config):
        super().__init__(config)
        self.prefix = config.get("demo_prefix", {}).get("prefix", "示例：")
        self.model = "demo-prefix"

    def translate(self, text, context_before=None, context_after=None):
        return self.prefix + text

    def name(self):
        return "Demo prefix translator"


class SidecarJsonASR:
    """Read precomputed segments from <audio>.json or a configured path."""

    def __init__(self, config):
        self.path = config.get("sidecar_json", {}).get("path", "")

    def transcribe(self, audio_path):
        path = Path(self.path) if self.path else Path(audio_path).with_suffix(".json")
        segments = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(segments, list):
            raise ValueError("Sidecar ASR JSON must contain a segment list")
        return segments


def demo_pink_style(config):
    return {
        "fontname": config.get("fontname", "Microsoft YaHei"),
        "fontsize": config.get("fontsize", 30),
        "primarycolor": pysubs2.Color(255, 180, 220),
        "secondarycolor": pysubs2.Color(255, 255, 255),
        "outlinecolor": pysubs2.Color(20, 20, 30),
        "backcolor": pysubs2.Color(0, 0, 0),
        "bold": True,
        "borderstyle": 1,
        "outline": 2,
        "shadow": 1,
        "alignment": 2,
        "marginl": 20,
        "marginr": 20,
        "marginv": 16,
        "encoding": 1,
    }


def register_plugins(registry):
    registry.register(
        "translator",
        "demo_prefix",
        DemoPrefixTranslator,
        source=__file__,
        description="Prefixes source text for plugin smoke tests",
    )
    registry.register(
        "asr",
        "sidecar_json",
        SidecarJsonASR,
        source=__file__,
        description="Reads precomputed ASR segments from a JSON sidecar",
    )
    registry.register(
        "subtitle_style",
        "demo_pink",
        demo_pink_style,
        source=__file__,
        description="Pink bold ASS subtitle style",
    )
