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


class FakeFallbackAdapter:
    model = "fake-galtransl"

    def __init__(self, target="啊！"):
        self.target = target
        self.calls = []
        self.series_info = ""

    def translate_batch(self, texts, glossary_terms=None):
        self.calls.append((list(texts), list(glossary_terms or [])))
        return [self.target for _ in texts]

    def result_model(self, source):
        return self.model


class FakeContextAdapter(FakeAdapter):
    def translate_batch(
        self,
        texts,
        glossary_terms=None,
        context_before=None,
        context_after=None,
    ):
        self.calls.append(
            (
                list(texts),
                list(glossary_terms or []),
                list(context_before or []),
                list(context_after or []),
            )
        )
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
    assert result[0]["translation_model"] == "previous"
    assert result[0]["translation_fallback"] is False
    assert result[0]["asr_confidence"] == 0.9
    assert adapter.calls == [
        (["軽音部です", "よろしく"], [("軽音部", "轻音部")])
    ]
    assert len(json.loads(progress.read_text(encoding="utf-8"))) == 3
    assert TranslationMemory(str(memory_path)).count() == 3


def test_sakura_batch_parser_preserves_order_and_removes_numbering():
    raw = "1. 早上好\n2. 今天也请多关照"
    assert SakuraAdapter._parse_lines(raw, 2) == ["早上好", "今天也请多关照"]


def test_sakura_tagged_parser_restores_id_order_and_accepts_fullwidth_brackets():
    raw = "【L001】请不要在意。\n【L000】请陪我练习。"
    assert SakuraAdapter._parse_tagged_lines(raw, 2) == [
        "请陪我练习。",
        "请不要在意。",
    ]


def test_sakura_batch_uses_stable_ids_to_prevent_silent_line_swaps():
    adapter = SakuraAdapter(
        {"sakura": {"model": "fake", "host": "localhost", "max_retries": 1}}
    )
    calls = []

    def fake_call(messages, **kwargs):
        calls.append(messages)
        return "【L001】请不要在意。\n【L000】请陪我练习。"

    adapter._call = fake_call

    assert adapter.translate_batch(
        ["私の練習に付き合わせて", "全然気にしないでください。"]
    ) == [
        "请陪我练习。",
        "请不要在意。",
    ]
    assert "[[L000]] 私の練習に付き合わせて" in calls[0][1]["content"]


def test_sakura_tagged_parser_rejects_missing_or_duplicate_ids():
    assert SakuraAdapter._parse_tagged_lines("【L000】甲\n【L000】乙", 2) is None
    assert SakuraAdapter._parse_tagged_lines("【L000】甲", 2) is None


def test_pipeline_translator_only_sends_matching_glossary_terms():
    glossary = Glossary()
    glossary.add("軽音部", "轻音部")
    glossary.add("秋山澪", "秋山澪")
    engine = PipelineTranslator(FakeAdapter(), glossary=glossary)
    assert engine._matching_glossary_terms(["軽音部です"]) == [("軽音部", "轻音部")]


def test_pipeline_translator_passes_outer_context_at_batch_boundaries():
    adapter = FakeContextAdapter()
    segments = [
        {"start": index, "end": index + 1, "text": f"原文{index}"}
        for index in range(5)
    ]

    PipelineTranslator(
        adapter,
        batch_size=2,
        context_window=2,
    ).translate(segments)

    assert adapter.calls == [
        (["原文0"], [], [], []),
        (["原文1"], [], ["中:原文0"], []),
        (["原文2"], [], ["中:原文0", "中:原文1"], []),
        (["原文3"], [], ["中:原文1", "中:原文2"], []),
        (["原文4"], [], ["中:原文2", "中:原文3"], []),
    ]


def test_sakura_context_is_read_only_system_content_not_translation_input():
    context = SakuraAdapter._context_block(
        context_before=["昨日ギターを買った"],
        context_after=["一緒に練習しよう"],
    )
    prompt = SakuraAdapter._user_prompt(["そうなんだ"])

    assert "只供理解待翻译句子的指代、语气和省略信息" in context
    assert "已翻译前文（简体中文）：\n昨日ギターを買った" in context
    assert "参考下文：\n一緒に練習しよう" in context
    assert "待翻译日文逐行翻译" in prompt
    assert "昨日ギターを買った" not in prompt


def test_context_leak_markers_are_rejected():
    assert SakuraAdapter._valid_translation(
        "まだまだですけど、楽しいです！",
        "下文：那放学后一起练习吧。虽然还差得远，但很开心！",
    ) is False
    assert SakuraAdapter._valid_translation(
        "ちッ 遅刻 遅刻ッ",
        "迟到啦 小唯 只输出 user 消息中待翻译日文的简体中文译文。",
    ) is False


def test_merged_repeated_context_lines_are_rejected():
    assert SakuraAdapter._valid_translation(
        "入学おめでとうございま～す",
        "欢迎加入网球部 欢迎加入柔道部 欢迎加入茶道部",
    ) is False
    assert SakuraAdapter._valid_translation("わあ わあ わあ", "哇 哇 哇") is True


def test_translation_memory_separates_the_same_line_by_context(tmp_path):
    path = tmp_path / "context-memory.jsonl"
    memory = TranslationMemory(str(path), auto_save=False)
    before = ["昨日ギターを買ったんだ。"]
    after = ["一緒に練習しよう。"]
    memory.store(
        "そうなんだ。",
        "这样啊。",
        model="fake-sakura",
        context_before=before,
        context_after=after,
    )
    memory.save()

    reloaded = TranslationMemory(str(path))
    assert reloaded.lookup("そうなんだ。", before, after) == "这样啊。"
    assert reloaded.lookup("そうなんだ。", ["雨が降っている。"], after) is None
    assert reloaded.lookup("そうなんだ。") is None
    entry = reloaded.lookup_entry("そうなんだ。", before, after)
    assert entry["context_version"] == 1
    assert entry["context_before"] == before


def test_pipeline_reuses_memory_only_when_neighboring_context_matches(tmp_path):
    path = tmp_path / "pipeline-context-memory.jsonl"
    first_adapter = FakeContextAdapter()
    segments = [
        {"start": 0, "end": 1, "text": "昨日ギターを買った。"},
        {"start": 1, "end": 2, "text": "そうなんだ。"},
        {"start": 2, "end": 3, "text": "一緒に練習しよう。"},
    ]
    PipelineTranslator(
        first_adapter,
        memory=TranslationMemory(str(path), auto_save=False),
        context_window=1,
    ).translate(segments)

    same_context_adapter = FakeContextAdapter()
    PipelineTranslator(
        same_context_adapter,
        memory=TranslationMemory(str(path), auto_save=False),
        context_window=1,
    ).translate(segments)
    assert same_context_adapter.calls == []

    changed_context_adapter = FakeContextAdapter()
    changed = [dict(item) for item in segments]
    changed[0]["text"] = "外は雨だ。"
    PipelineTranslator(
        changed_context_adapter,
        memory=TranslationMemory(str(path), auto_save=False),
        context_window=1,
    ).translate(changed)
    requested = [call[0][0] for call in changed_context_adapter.calls]
    assert "そうなんだ。" in requested


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


def test_invalid_single_line_recovers_with_constrained_retry():
    adapter = SakuraAdapter(
        {
            "sakura": {
                "model": "fake-sakura",
                "host": "localhost",
                "validation_retries": 2,
            }
        }
    )
    responses = iter(["“", "啊！"])
    adapter._call = lambda *args, **kwargs: next(responses)

    assert adapter.translate_batch(["――あ!……"]) == ["啊！"]
    assert adapter.result_model("――あ!……") == "fake-sakura"
    assert adapter.result_is_fallback("――あ!……") is False


def test_invalid_single_line_uses_configured_galtransl_fallback():
    adapter = SakuraAdapter(DEFAULT_CONFIG)
    fallback = FakeFallbackAdapter()
    adapter.fallback_adapter = fallback
    adapter.validation_retries = 2
    adapter._call = lambda *args, **kwargs: "“"

    assert adapter.translate_batch(["――あ!……"]) == ["啊！"]
    assert fallback.calls == [(["――あ!……"], [])]
    assert adapter.result_model("――あ!……") == "fake-galtransl"
    assert adapter.result_is_fallback("――あ!……") is True


def test_pipeline_persists_fallback_model_provenance(tmp_path):
    adapter = SakuraAdapter(DEFAULT_CONFIG)
    adapter.fallback_adapter = FakeFallbackAdapter(target="啊！")
    adapter.validation_retries = 0
    adapter._call = lambda *args, **kwargs: "“"
    memory_path = tmp_path / "fallback.jsonl"
    memory = TranslationMemory(str(memory_path), auto_save=False)
    segments = [{"start": 0, "end": 1, "text": "――あ!……"}]

    first = PipelineTranslator(adapter, memory=memory).translate(segments)
    second = PipelineTranslator(FakeAdapter(), memory=TranslationMemory(str(memory_path))).translate(
        segments
    )

    assert first[0]["translation_model"] == "fake-galtransl"
    assert first[0]["translation_fallback"] is True
    assert second[0]["translation_cached"] is True
    assert second[0]["translation_model"] == "fake-galtransl"
    assert second[0]["translation_fallback"] is True


def test_translation_memory_updates_provenance_for_unchanged_text(tmp_path):
    memory = TranslationMemory(str(tmp_path / "provenance.jsonl"), auto_save=False)
    memory.store("――あ!……", "——啊！……", model="fake-sakura", fallback=False)
    memory.store("――あ!……", "——啊！……", model="fake-galtransl", fallback=True)

    entry = memory.lookup_entry("――あ!……")
    assert entry["model"] == "fake-galtransl"
    assert entry["translation_fallback"] is True


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


def test_unicode_quotes_and_math_symbols_are_nonverbal():
    source = "\u226a\u2026\u2026"
    assert SakuraAdapter._valid_translation(source, "\u300c\u2026\u2026") is True


def test_spoken_kana_with_punctuation_is_not_nonverbal():
    assert SakuraAdapter._valid_translation("\u306f?\u2026\u2026", "\u300c\u2026\u2026") is False


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
