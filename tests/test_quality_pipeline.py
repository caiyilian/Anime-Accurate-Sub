import json

from scripts.anime_sub import PIPELINE_STAGES, process_video
from scripts.checkpoint import Checkpoint
from scripts.quality_check import (
    check_term_consistency,
    generate_report,
    segments_from_dicts,
)


def _translated_items():
    return [
        {
            "start": 1.0,
            "end": 3.0,
            "ja": "\u305d\u308d\u305d\u308d\u8d77\u304d\u306a\u3044\u3068\u3002",
            "text": "\u5dee\u4e0d\u591a\u8be5\u8d77\u5e8a\u4e86\u3002",
            "asr_confidence": 0.98,
        },
        {
            "start": 3.1,
            "end": 4.0,
            "ja": "\u3042\u3001\u3042\u3063\u3002",
            "text": "\u554a\u3002",
            "asr_confidence": 0.22,
        },
    ]


def test_segments_from_pipeline_dicts_preserves_asr_confidence():
    segments = segments_from_dicts(_translated_items())
    assert len(segments) == 2
    assert segments[0].index == 0
    assert segments[1].confidence == 0.22
    assert segments[1].ja == "\u3042\u3001\u3042\u3063\u3002"


def test_quality_report_contains_real_segments_and_review_queue(tmp_path):
    output = tmp_path / "quality.json"
    report = generate_report(segments_from_dicts(_translated_items()), [], str(output))

    assert report["stats"]["total_segments"] == 2
    assert report["stats"]["warnings"] >= 1
    low_confidence = [
        item for item in report["review_queue"] if item["rule"] == "low_asr_confidence"
    ]
    assert len(low_confidence) == 1
    assert low_confidence[0]["segment_index"] == 1
    assert low_confidence[0]["ja"] == "\u3042\u3001\u3042\u3063\u3002"
    assert low_confidence[0]["text"] == "\u554a\u3002"
    assert json.loads(output.read_text(encoding="utf-8"))["stats"] == report["stats"]


def test_quality_report_flags_translation_fallback(tmp_path):
    items = _translated_items()
    items[0]["translation_model"] = "crosery/GalTransl-7B-v2.6:Q6_k"
    items[0]["translation_fallback"] = True

    report = generate_report(
        segments_from_dicts(items), [], str(tmp_path / "fallback-quality.json")
    )
    fallback = [
        item for item in report["review_queue"]
        if item["rule"] == "translation_fallback"
    ]

    assert len(fallback) == 1
    assert fallback[0]["translation_model"] == "crosery/GalTransl-7B-v2.6:Q6_k"
    assert fallback[0]["translation_fallback"] is True


def test_short_kana_glossary_requires_a_left_boundary(tmp_path):
    glossary = tmp_path / "glossary.json"
    glossary.write_text(
        json.dumps({"terms": [{"ja": "\u3046\u3044", "zh": "\u5fe7"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    segments = segments_from_dicts([
        {
            "start": 0.0,
            "end": 1.0,
            "ja": "\u305d\u3046\u3044\u3046\u554f\u984c\u3058\u3083\u306d\u3048",
            "text": "\u95ee\u9898\u4e0d\u5728\u8fd9\u91cc",
        },
        {
            "start": 1.0,
            "end": 2.0,
            "ja": "\u3046\u3044\u3061\u3083\u3093 \u304a\u306f\u3088\u3046",
            "text": "\u65e9\u4e0a\u597d",
        },
        {
            "start": 2.0,
            "end": 3.0,
            "ja": "\u5e73\u6ca2\u3046\u3044\u3067\u3059",
            "text": "\u6211\u662f\u5e73\u6cfd\u5fe7",
        },
    ])

    issues = check_term_consistency(segments, str(glossary))

    assert [issue.segment_index for issue in issues] == [1]


def test_main_pipeline_quality_stage_reads_translated_json(tmp_path):
    video = tmp_path / "episode01.mp4"
    output_root = tmp_path / "output"
    work_dir = output_root / video.stem
    work_dir.mkdir(parents=True)
    translated_path = work_dir / "translated.json"
    translated_path.write_text(
        json.dumps(_translated_items(), ensure_ascii=False), encoding="utf-8"
    )

    checkpoint = Checkpoint(str(work_dir))
    for stage in PIPELINE_STAGES[:-1]:
        checkpoint.mark_completed(stage)

    result = process_video(
        str(video),
        str(output_root),
        config={},
        quality_check=True,
    )

    report = json.loads((work_dir / "quality_report.json").read_text(encoding="utf-8"))
    assert report["stats"]["total_segments"] == 2
    assert result["quality_stats"] == report["stats"]
    assert result["stages_completed"] == 6
    assert result["stages_total"] == 6
