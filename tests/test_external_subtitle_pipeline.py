import json
from pathlib import Path

import pytest

from scripts.checkpoint import Checkpoint
from scripts.extract_subs import (
    find_japanese_sidecar,
    load_japanese_subtitle,
    select_japanese_track,
)
from scripts.translation_engine import PipelineTranslator


def _write_srt(path: Path, text: str = "お姉ちゃん、起きて！") -> None:
    path.write_text(
        f"1\n00:00:01,000 --> 00:00:02,500\n{text}\n",
        encoding="utf-8",
    )


def test_load_japanese_subtitle_preserves_timing_and_provenance(tmp_path):
    source = tmp_path / "episode.jp.srt"
    _write_srt(source)

    segments = load_japanese_subtitle(source)

    assert segments == [
        {
            "start": 1.0,
            "end": 2.5,
            "text": "お姉ちゃん、起きて！",
            "confidence": 1.0,
            "source": "external_japanese_subtitle",
            "subtitle_index": 0,
        }
    ]


def test_chinese_reference_cannot_be_used_as_japanese_source(tmp_path):
    source = tmp_path / "episode.zh.srt"
    _write_srt(source, "姐姐，快起床！")

    with pytest.raises(ValueError, match="does not appear to contain Japanese"):
        load_japanese_subtitle(source)


def test_sidecar_matching_requires_one_valid_episode_match(tmp_path):
    video = tmp_path / "轻音少女_第02集.mp4"
    video.write_bytes(b"video")
    _write_srt(tmp_path / "K-ON! S1E01.jp.srt")
    expected = tmp_path / "K-ON! S1E02.jp.srt"
    _write_srt(expected, "みんな、練習しよう。")

    assert find_japanese_sidecar(video, tmp_path) == expected

    _write_srt(tmp_path / "K-ON! S1E02.ja.srt", "もう一度、練習しよう。")
    with pytest.raises(ValueError, match="Multiple Japanese subtitles"):
        find_japanese_sidecar(video, tmp_path)


def test_embedded_track_selection_never_uses_chinese_or_bitmap_tracks():
    tracks = [
        {"index": 1, "language": "zho", "codec": "ass", "title": "中文"},
        {
            "index": 2,
            "language": "jpn",
            "codec": "hdmv_pgs_subtitle",
            "title": "日本語 PGS",
        },
        {"index": 3, "language": "jpn", "codec": "ass", "title": "日本語"},
    ]

    assert select_japanese_track(tracks)["index"] == 3


def test_translation_preserves_external_source_audit_fields():
    class Adapter:
        model = "test-model"

        def name(self):
            return "test"

        def translate_batch(self, texts, glossary_terms=None):
            return ["早上好" for _ in texts]

    source = {
        "start": 1.0,
        "end": 2.0,
        "text": "おはよう",
        "confidence": 1.0,
        "source": "external_japanese_subtitle",
        "subtitle_index": 12,
    }

    translated = PipelineTranslator(Adapter()).translate([source])[0]

    assert translated["source"] == "external_japanese_subtitle"
    assert translated["subtitle_index"] == 12
    assert translated["asr_confidence"] == 1.0


def test_pipeline_skips_asr_and_invalidates_downstream_when_source_changes(
    tmp_path, monkeypatch
):
    from scripts import anime_sub

    video = tmp_path / "轻音少女_第01集.mp4"
    video.write_bytes(b"video")
    source = tmp_path / "K-ON! S1E01.jp.srt"
    _write_srt(source)
    output_root = tmp_path / "output"
    work_dir = output_root / video.stem
    work_dir.mkdir(parents=True)

    old_checkpoint = Checkpoint(str(work_dir))
    for stage in ("extract_audio", "asr", "translate", "subtitle", "embed_subtitle"):
        old_checkpoint.mark_completed(stage)

    monkeypatch.setattr(
        anime_sub,
        "extract_audio",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("audio must be skipped")),
    )
    monkeypatch.setattr(
        anime_sub,
        "run_asr",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ASR must be skipped")),
    )
    monkeypatch.setattr(anime_sub.TranslatorAdapter, "from_config", lambda config: object())
    translated_sources = []

    def fake_translate(segments, adapter, *args, progress_path="", **kwargs):
        translated_sources.append([segment["text"] for segment in segments])
        output = [
            {
                "start": segment["start"],
                "end": segment["end"],
                "ja": segment["text"],
                "text": "测试译文",
                "asr_confidence": segment["confidence"],
            }
            for segment in segments
        ]
        Path(progress_path).write_text(
            json.dumps(output, ensure_ascii=False), encoding="utf-8"
        )
        return output

    def fake_generate(input_path, output_path, **kwargs):
        Path(output_path).write_text("subtitle", encoding="utf-8")

    def fake_embed(video_path, subtitle_path, output_path):
        Path(output_path).write_bytes(b"reviewed-video")

    monkeypatch.setattr(anime_sub, "translate_segments", fake_translate)
    monkeypatch.setattr(anime_sub, "generate_subtitles", fake_generate)
    monkeypatch.setattr(anime_sub, "embed_subtitle", fake_embed)

    first = anime_sub.process_video(
        str(video),
        str(output_root),
        config={},
        japanese_subtitle_path=str(source),
    )
    assert first["stages_completed"] == 4
    assert first["stages_total"] == 4
    assert translated_sources == [["お姉ちゃん、起きて！"]]
    asr = json.loads((work_dir / "asr_results.json").read_text(encoding="utf-8"))
    assert asr[0]["source"] == "external_japanese_subtitle"
    assert json.loads((work_dir / "japanese_source.json").read_text(encoding="utf-8"))[
        "sha256"
    ]

    anime_sub.process_video(
        str(video),
        str(output_root),
        config={},
        japanese_subtitle_path=str(source),
    )
    assert len(translated_sources) == 1

    _write_srt(source, "みんな、練習しよう。")
    anime_sub.process_video(
        str(video),
        str(output_root),
        config={},
        japanese_subtitle_path=str(source),
    )
    assert translated_sources[-1] == ["みんな、練習しよう。"]
    assert len(translated_sources) == 2


def test_switching_from_external_source_invalidates_audio_asr_and_downstream(tmp_path):
    from scripts.anime_sub import _reset_source_downstream

    checkpoint = Checkpoint(
        str(tmp_path),
        stages=[
            "extract_audio",
            "asr",
            "japanese_subtitle",
            "translate",
            "subtitle",
            "embed_subtitle",
        ],
    )
    for stage in checkpoint.stages:
        checkpoint.mark_completed(stage)

    _reset_source_downstream(checkpoint, include_asr=True)

    assert checkpoint.is_completed("japanese_subtitle")
    for stage in ("extract_audio", "asr", "translate", "subtitle", "embed_subtitle"):
        assert not checkpoint.is_completed(stage)
