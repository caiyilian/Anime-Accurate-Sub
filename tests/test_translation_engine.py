import json

from scripts.glossary import Glossary
from scripts.translation_engine import PipelineTranslator
from scripts.translation_memory import TranslationMemory
from scripts.translator_adapter import DEFAULT_CONFIG, GalTranslAdapter, SakuraAdapter


class FakeAdapter:
    model = "fake-sakura"
    batch_size = 8

    def __init__(self):
        self.calls = []

    def name(self):
        return self.model

    def translate_batch(self, texts, glossary_terms=None):
        self.calls.append((list(texts), list(glossary_terms or [])))
        return [f"中:{text}" for text in texts]


def test_pipeline_translator_uses_memory_glossary_and_progress(tmp_path):
    memory_path = tmp_path / "tm.jsonl"
    memory = TranslationMemory(str(memory_path), auto_save=False)
    memory.store("おはよう", "早上好", model="previous")
    memory.save()
    glossary = Glossary()
    glossary.add("軽音部", "轻音部")
    adapter = FakeAdapter()
    progress = tmp_path / "translated.json"
    segments = [
        {"start": 0, "end": 1, "text": "おはよう", "confidence": 0.9},
        {"start": 1, "end": 2, "text": "軽音部です"},
        {"start": 2, "end": 3, "text": "よろしく"},
    ]

    result = PipelineTranslator(adapter, glossary, memory, batch_size=3).translate(
        segments, progress
    )

    assert [item["text"] for item in result] == ["早上好", "中:軽音部です", "中:よろしく"]
    assert result[0]["translation_cached"] is True
    assert result[0]["asr_confidence"] == 0.9
    assert adapter.calls == [
        (["軽音部です", "よろしく"], [("軽音部", "轻音部")])
    ]
    assert len(json.loads(progress.read_text(encoding="utf-8"))) == 3
    assert TranslationMemory(str(memory_path)).count() == 3


def test_sakura_batch_parser_preserves_order_and_removes_numbering():
    raw = "1. 早上好\n2. 今天也请多关照"
    assert SakuraAdapter._parse_lines(raw, 2) == ["早上好", "今天也请多关照"]


def test_pipeline_translator_only_sends_matching_glossary_terms():
    glossary = Glossary()
    glossary.add("軽音部", "轻音部")
    glossary.add("秋山澪", "秋山澪")
    engine = PipelineTranslator(FakeAdapter(), glossary=glossary)
    assert engine._matching_glossary_terms(["軽音部です"]) == [("軽音部", "轻音部")]


def test_sakura_batch_falls_back_to_smaller_requests():
    adapter = SakuraAdapter(
        {
            "backend": "sakura",
            "sakura": {"model": "fake", "host": "localhost", "max_retries": 1},
        }
    )
    responses = iter(["只返回一行", "甲", "乙"])
    adapter._call = lambda *args, **kwargs: next(responses)
    assert adapter.translate_batch(["あ", "い"]) == ["甲", "乙"]


def test_ollama_adapter_accepts_custom_port_and_context_size():
    adapter = SakuraAdapter(
        {
            "sakura": {
                "model": "local-sakura",
                "host": "127.0.0.1:11435",
                "num_ctx": 4096,
            }
        }
    )
    assert adapter.api_url == "http://127.0.0.1:11435/api/chat"
    assert adapter.num_ctx == 4096


def test_galtransl_uses_model_specific_sampling_defaults():
    adapter = GalTranslAdapter(DEFAULT_CONFIG)
    assert adapter.batch_size == 10
    assert adapter.temperature == 0.2
    assert adapter.top_p == 0.8
    assert adapter.repeat_penalty == 1.1


def test_punctuation_only_output_is_rejected():
    source = "\u8efd\u97f3\u90e8\u3063\u3066\u4f55\uff1f"
    assert SakuraAdapter._valid_translation(source, "......") is False


def test_nonverbal_punctuation_cue_is_allowed():
    source = "\u2015\u2015\u30c3!?"
    assert SakuraAdapter._valid_translation(source, "\u2014\u2014\uff01\uff1f") is True


def test_fullwidth_tilde_nonverbal_cue_is_allowed():
    source = "\uff5e\uff5e\u3063\u2026\u2026"
    assert SakuraAdapter._valid_translation(source, "\uff5e\uff5e\u2026\u2026") is True


def test_recursive_batches_drop_unrelated_glossary_terms():
    texts = ["\u8efd\u97f3\u90e8", "\u79cb\u5c71\u6faa"]
    terms = [
        ("\u8efd\u97f3\u90e8", "\u8f7b\u97f3\u90e8"),
        ("\u5e73\u6ca2\u552f", "\u5e73\u6cfd\u552f"),
    ]
    assert SakuraAdapter._matching_terms(texts, terms) == [terms[0]]


def test_invalid_prompt_leak_is_rejected():
    assert SakuraAdapter._valid_translation("おはよう", "早上好") is True
    assert SakuraAdapter._valid_translation("おはよう", "将下面的日文翻译") is False
