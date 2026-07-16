import json
from pathlib import Path

import pysubs2
import pytest

import scripts.anime_sub as anime_sub
from scripts.plugin_system import PluginRegistry, plugin_registry
from scripts.subtitle_gen import generate
from scripts.translation_engine import PipelineTranslator
from scripts.translator_adapter import TranslatorAdapter


class EchoTranslator:
    model = "echo-plugin"
    batch_size = 4

    def translate(self, text, context_before=None, context_after=None):
        return f"中:{text}"

    def translate_batch(self, texts, glossary_terms=None):
        return [self.translate(text) for text in texts]

    def name(self):
        return self.model


class FakeASR:
    def __init__(self, config):
        self.marker = config.get("fake_asr", {}).get("marker", "ok")

    def transcribe(self, audio_path):
        return [{"start": 0, "end": 1, "text": self.marker}]


def test_registry_rejects_duplicate_and_broken_contracts():
    registry = PluginRegistry()
    registry.register("translator", "echo_test", lambda config: EchoTranslator())
    with pytest.raises(ValueError, match="已注册"):
        registry.register("translator", "echo_test", lambda config: EchoTranslator())
    registry.register("asr", "broken_asr", lambda config: object())
    with pytest.raises(TypeError, match="transcribe"):
        registry.create("asr", "broken_asr", {})


def test_load_trusted_local_file_registers_all_plugin_kinds(tmp_path):
    plugin = tmp_path / "local_plugin.py"
    plugin.write_text(
        """
class Translator:
    def translate(self, text, context_before=None, context_after=None): return 'P:' + text
    def translate_batch(self, texts, glossary_terms=None): return [self.translate(x) for x in texts]
    def name(self): return 'local'
class ASR:
    def transcribe(self, path): return [{'start': 0, 'end': 1, 'text': 'local'}]
def register_plugins(registry):
    registry.register('translator', 'local_translator', lambda config: Translator(), source=__file__)
    registry.register('asr', 'local_asr', lambda config: ASR(), source=__file__)
    registry.register('subtitle_style', 'local_style', lambda config: {'fontname': 'Arial'}, source=__file__)
""",
        encoding="utf-8",
    )
    registry = PluginRegistry()

    source = registry.load_file(plugin)

    assert source.startswith("file:")
    assert registry.create("translator", "local_translator", {}).translate("x") == "P:x"
    assert registry.create("asr", "local_asr", {}).transcribe("audio")[0]["text"] == "local"
    assert registry.create("subtitle_style", "local_style", {})["fontname"] == "Arial"
    assert registry.load_file(plugin) == source


def test_translator_factory_uses_registered_plugin():
    plugin_registry.register(
        "translator", "echo_test", lambda config: EchoTranslator(), replace=True
    )
    try:
        adapter = TranslatorAdapter.from_config({"backend": "echo_test"})
        translated = PipelineTranslator(adapter).translate(
            [{"start": 0, "end": 1, "text": "おはよう"}]
        )
        assert translated[0]["text"] == "中:おはよう"
        assert translated[0]["translation_model"] == "echo-plugin"
    finally:
        plugin_registry.unregister("translator", "echo_test")


def test_asr_pipeline_uses_registered_plugin(tmp_path):
    plugin_registry.register("asr", "fake_asr", FakeASR, replace=True)
    anime_sub._ASR_ENGINES.clear()
    try:
        result = anime_sub.run_asr(
            str(tmp_path / "audio.wav"),
            str(tmp_path),
            backend="fake_asr",
            config={"fake_asr": {"marker": "插件识别"}},
        )
        assert result[0]["text"] == "插件识别"
    finally:
        anime_sub._ASR_ENGINES.clear()
        plugin_registry.unregister("asr", "fake_asr")


def test_subtitle_generator_uses_registered_style(tmp_path):
    source = tmp_path / "translated.json"
    output = tmp_path / "plugin.ass"
    source.write_text(
        json.dumps([{"start": 0, "end": 2, "text": "插件样式"}], ensure_ascii=False),
        encoding="utf-8",
    )
    style = {
        "fontname": "Arial",
        "fontsize": 35,
        "primarycolor": pysubs2.Color(10, 20, 30),
        "outlinecolor": pysubs2.Color(0, 0, 0),
        "backcolor": pysubs2.Color(0, 0, 0),
        "alignment": 2,
    }
    plugin_registry.register(
        "subtitle_style", "test_style", lambda config: style, replace=True
    )
    try:
        generate(source, output, style="test_style")
        subtitles = pysubs2.load(str(output), encoding="utf-8")
        assert subtitles.styles["test_style"].fontsize == 35
        assert subtitles.styles["test_style"].primarycolor == pysubs2.Color(10, 20, 30)
    finally:
        plugin_registry.unregister("subtitle_style", "test_style")
