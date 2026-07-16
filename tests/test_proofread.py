import json

import pysubs2
import pytest

from scripts.proofread import (
    SHEET_SCHEMA,
    apply_corrections,
    build_proofread_sheet,
    export_sheet,
    regenerate_subtitles,
)
from scripts.quality_check import generate_report, segments_from_dicts


def _write_segments(path):
    path.write_text(
        json.dumps(
            [
                {"start": 1.0, "end": 2.0, "ja": "おはよう", "text": "早上好"},
                {
                    "start": 2.0,
                    "end": 3.0,
                    "ja": "あっ",
                    "text": "Ah,",
                    "translation_fallback": True,
                    "translation_model": "fallback",
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_export_sheet_merges_quality_review_reasons(tmp_path):
    translated = tmp_path / "translated.json"
    quality = tmp_path / "quality.json"
    sheet_path = tmp_path / "review.json"
    _write_segments(translated)
    generate_report(
        segments_from_dicts(json.loads(translated.read_text(encoding="utf-8"))),
        [],
        str(quality),
    )

    sheet = export_sheet(translated, sheet_path, quality, only_review=True)

    assert sheet["schema"] == SHEET_SCHEMA
    assert sheet["source_sha256"]
    fallback = next(item for item in sheet["items"] if item["index"] == 1)
    assert fallback["translated_text"] == "Ah,"
    assert any(reason["rule"] == "translation_fallback" for reason in fallback["reasons"])
    assert json.loads(sheet_path.read_text(encoding="utf-8"))["items"] == sheet["items"]


def test_apply_corrections_creates_backup_metadata_and_audit(tmp_path):
    translated = tmp_path / "translated.json"
    _write_segments(translated)
    sheet = build_proofread_sheet(translated)
    sheet["items"] = [
        {
            **sheet["items"][1],
            "corrected_text": "啊！",
            "note": "人工确认语气词",
        }
    ]

    result = apply_corrections(translated, sheet, operator="tester")
    updated = json.loads(translated.read_text(encoding="utf-8"))
    history = [
        json.loads(line)
        for line in (tmp_path / "proofread_history.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert result["applied"] == 1
    assert result["indexes"] == [1]
    assert updated[1]["text"] == "啊！"
    assert updated[1]["translation_fallback"] is True
    assert updated[1]["proofread_status"] == "corrected"
    assert updated[1]["proofread_history"][0]["previous_text"] == "Ah,"
    assert history[0]["operator"] == "tester"
    assert result["backup_file"] and result["backup_file"] != str(translated)


def test_apply_rejects_stale_sheet_without_modifying_source(tmp_path):
    translated = tmp_path / "translated.json"
    _write_segments(translated)
    sheet = build_proofread_sheet(translated)
    sheet["items"][0]["corrected_text"] = "早安"
    before = translated.read_bytes()
    changed = json.loads(translated.read_text(encoding="utf-8"))
    changed[0]["text"] = "你好"
    translated.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    externally_changed = translated.read_bytes()

    with pytest.raises(ValueError, match="SHA-256"):
        apply_corrections(translated, sheet)

    assert translated.read_bytes() == externally_changed
    assert translated.read_bytes() != before
    assert not (tmp_path / "proofread_history.jsonl").exists()


def test_regenerate_subtitles_uses_corrected_text(tmp_path):
    translated = tmp_path / "translated.json"
    _write_segments(translated)
    sheet = build_proofread_sheet(translated)
    sheet["items"] = [{**sheet["items"][1], "corrected_text": "啊！"}]
    apply_corrections(translated, sheet, create_backup=False)

    outputs = regenerate_subtitles(translated, tmp_path / "episode")
    srt = pysubs2.load(outputs["srt"], encoding="utf-8")
    ass = pysubs2.load(outputs["ass"], encoding="utf-8")
    assert srt.events[1].text == "啊！"
    assert ass.events[1].text == "啊！"


def test_quality_report_treats_human_corrected_fallback_as_resolved(tmp_path):
    items = [
        {
            "start": 0,
            "end": 2,
            "ja": "あっ",
            "text": "啊！",
            "translation_fallback": True,
            "proofread_status": "corrected",
        }
    ]
    report = generate_report(
        segments_from_dicts(items), [], str(tmp_path / "quality.json")
    )
    assert not any(issue["rule"] == "translation_fallback" for issue in report["issues"])
