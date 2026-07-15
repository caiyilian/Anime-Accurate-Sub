from pathlib import Path

from scripts.asr_engine import ASRSettings, TimedWord, resolve_model_path, segment_timed_words


def test_segment_timed_words_splits_on_sentence_end_and_pause():
    words = [
        TimedWord(0.0, 0.4, "おはよう"),
        TimedWord(0.4, 0.7, "。"),
        TimedWord(1.6, 2.0, "今日"),
        TimedWord(2.0, 2.4, "も"),
        TimedWord(2.4, 2.9, "元気"),
    ]
    segments = segment_timed_words(words)
    assert [segment["text"] for segment in segments] == ["おはよう。", "今日も元気"]
    assert segments[0]["start"] == 0.0
    assert segments[1]["start"] == 1.6


def test_segment_timed_words_enforces_readable_length():
    settings = ASRSettings(max_chars=4, max_duration_s=30)
    words = [
        TimedWord(0.0, 0.3, "軽音"),
        TimedWord(0.3, 0.6, "楽部"),
        TimedWord(0.6, 0.9, "です"),
    ]
    segments = segment_timed_words(words, settings)
    assert [segment["text"] for segment in segments] == ["軽音楽部", "です"]


def test_short_fragment_merges_with_previous_segment():
    settings = ASRSettings(min_duration_s=0.5, pause_split_s=0.7)
    words = [
        TimedWord(0.0, 0.8, "はい!"),
        TimedWord(0.9, 1.0, "え"),
    ]
    segments = segment_timed_words(words, settings)
    assert [segment["text"] for segment in segments] == ["はい!え"]


def test_single_bad_word_timestamp_is_clamped():
    settings = ASRSettings(max_duration_s=6)
    segments = segment_timed_words([TimedWord(10.0, 40.0, "長い時間戳")], settings)
    assert segments == [{"start": 10.0, "end": 16.0, "text": "長い時間戳"}]


def test_resolve_model_path_accepts_explicit_ct2_directory(tmp_path: Path):
    (tmp_path / "model.bin").write_bytes(b"model")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    assert resolve_model_path(tmp_path) == tmp_path.resolve()
