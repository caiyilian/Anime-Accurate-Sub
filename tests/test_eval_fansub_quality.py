from scripts.eval_fansub_quality import (
    Segment,
    _discover_prediction_files,
    align_segments,
    asr_health,
    char_f1,
    chrf,
    clean_subtitle_text,
)


def test_discovery_prefers_the_most_reviewed_episode_output(tmp_path):
    episode1 = tmp_path / "episode01"
    episode2 = tmp_path / "episode02"
    episode3 = tmp_path / "episode03"
    for episode in (episode1, episode2, episode3):
        episode.mkdir()
        (episode / "translated.json").write_text("[]", encoding="utf-8")
    (episode1 / "reviewed.json").write_text("[]", encoding="utf-8")
    (episode1 / "mqm_reviewed.json").write_text("[]", encoding="utf-8")
    (episode2 / "reviewed.json").write_text("[]", encoding="utf-8")

    discovered = _discover_prediction_files(tmp_path)

    assert discovered == [
        episode1 / "mqm_reviewed.json",
        episode2 / "reviewed.json",
        episode3 / "translated.json",
    ]


def test_clean_subtitle_text_removes_ass_markup():
    assert clean_subtitle_text(r"{\pos(10,20)}你好\N世界") == "你好 世界"


def test_reference_metrics_accept_identical_text():
    assert char_f1("早上好，唯！", "早上好唯") == 1.0
    assert chrf("早上好，唯！", "早上好唯") == 1.0


def test_alignment_ignores_different_segmentation():
    predictions = [Segment(1.0, 4.0, "早上好 唯", source="おはよう、唯")]
    references = [
        Segment(1.0, 2.0, "早上好"),
        Segment(2.1, 4.0, "唯"),
    ]
    alignments, matched = align_segments(predictions, references)
    assert matched == {0, 1}
    assert len(alignments) == 1
    assert alignments[0].chrf == 1.0


def test_asr_health_flags_long_segments_and_replacement_characters():
    health = asr_health(
        [
            Segment(0.0, 30.0, "译文", source="壊れた�テキスト"),
            Segment(30.0, 31.0, "译文", source="正常"),
        ]
    )
    assert health["segments_over_20s"] == 1
    assert health["replacement_characters"] == 1
