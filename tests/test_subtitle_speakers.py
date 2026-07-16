import json

import pysubs2

from scripts.subtitle_gen import generate, load_speaker_map
from scripts.translation_engine import PipelineTranslator


class FakeAdapter:
    model = "fake"
    batch_size = 8

    def name(self):
        return self.model

    def translate_batch(self, texts, glossary_terms=None):
        return [f"译:{text}" for text in texts]


def test_translation_engine_preserves_speaker_metadata():
    result = PipelineTranslator(FakeAdapter()).translate(
        [{"start": 0, "end": 1, "text": "おはよう", "speaker": "SPEAKER_00"}]
    )
    assert result[0]["speaker"] == "SPEAKER_00"


def test_load_speaker_map_assigns_default_color():
    roles = load_speaker_map({"SPEAKER_00": "唯"})
    assert roles["SPEAKER_00"].name == "唯"
    assert roles["SPEAKER_00"].color.startswith("#")


def test_ass_uses_role_prefix_and_per_speaker_color(tmp_path):
    source = tmp_path / "translated.json"
    output = tmp_path / "roles.ass"
    source.write_text(
        json.dumps(
            [
                {"start": 0, "end": 2, "text": "早上好", "speaker": "SPEAKER_00"},
                {"start": 2, "end": 4, "text": "早", "speaker": "SPEAKER_01"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    generate(
        source,
        output,
        style="anime",
        speaker_map={
            "SPEAKER_00": {"name": "唯", "color": "#FF80C0"},
            "SPEAKER_01": {"name": "澪", "color": "#80C0FF"},
        },
    )
    subs = pysubs2.load(str(output), encoding="utf-8")

    assert [event.text for event in subs.events] == ["唯：早上好", "澪：早"]
    assert subs.events[0].style != subs.events[1].style
    assert subs.styles[subs.events[0].style].primarycolor == pysubs2.Color(255, 128, 192)
    assert subs.styles[subs.events[1].style].primarycolor == pysubs2.Color(128, 192, 255)


def test_srt_keeps_name_prefix_without_ass_markup(tmp_path):
    source = tmp_path / "translated.json"
    output = tmp_path / "roles.srt"
    source.write_text(
        json.dumps([{"start": 0, "end": 2, "text": "早上好", "speaker": "spk"}]),
        encoding="utf-8",
    )
    generate(source, output, speaker_map={"spk": {"name": "唯", "color": "#FFFFFF"}})

    text = output.read_text(encoding="utf-8-sig")
    assert "唯：早上好" in text
    assert "{\\c" not in text
