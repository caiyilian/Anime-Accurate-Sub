import json
import sys

from scripts.adjudicate_fansub_review import (
    _parse_decision,
    adjudicate_case,
    apply_manual_overrides,
    apply_report,
    build_report,
    main,
)


def _case(tmp_path):
    return {
        "case_id": "E01:2:test",
        "episode": 1,
        "episode_dir": str(tmp_path / "轻音少女_第01集"),
        "index": 2,
        "selection": "needs_review",
        "start": 1.0,
        "end": 2.0,
        "ja": "しまった",
        "current_zh": "糟 糕了",
        "context_before": [],
        "context_after": [],
        "fansub_reference": "糟糕了",
        "fansub_alignment": {"chrf": 0.8},
        "mqm_evidence": {},
    }


def test_parse_decision_requires_correction_for_revision():
    parsed = _parse_decision(
        json.dumps(
            {
                "decision": "revise",
                "corrected_zh": "糟糕了",
                "severity": "minor",
                "reason": "删除词内空格",
                "confidence": 0.98,
                "reference_reliability": "high",
            }
        )
    )
    assert parsed["corrected_zh"] == "糟糕了"


def test_adjudicate_case_preserves_independent_and_final_evidence(tmp_path):
    responses = iter(
        [
            '{"decision":"revise","corrected_zh":"糟糕了","severity":"minor",'
            '"reason":"排版错误","confidence":0.98,"reference_reliability":"high"}',
            '{"decision":"revise","corrected_zh":"糟糕了","severity":"minor",'
            '"reason":"词内不应空格","confidence":0.96,"reference_reliability":"high"}',
            '{"decision":"revise","corrected_zh":"糟糕了","severity":"minor",'
            '"reason":"两方证据一致","confidence":0.99,"reference_reliability":"high"}',
        ]
    )
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append((messages, kwargs))
        return next(responses)

    config = {
        "provider": "openai",
        "review_models": ["flash", "deepseek"],
        "review_fallback_models": {},
        "adjudicator_model": "flash",
        "retries": 1,
    }
    result = adjudicate_case(_case(tmp_path), config, chat_fn=fake_chat)

    assert result["adjudication"]["corrected_zh"] == "糟糕了"
    assert [item["model"] for item in result["reviews"]] == ["flash", "deepseek"]
    assert len(calls) == 3


def test_apply_report_backs_up_and_applies_only_confident_revision(tmp_path):
    case = _case(tmp_path)
    episode_dir = tmp_path / "轻音少女_第01集"
    episode_dir.mkdir()
    path = episode_dir / "mqm_reviewed.json"
    path.write_text(
        json.dumps(
            [
                {"ja": "前", "text": "前"},
                {"ja": "中", "text": "中"},
                {"ja": "しまった", "text": "糟 糕了"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = {
        "case_id": case["case_id"],
        "status": "ok",
        "adjudication": {
            "decision": "revise",
            "corrected_zh": "糟糕了",
            "confidence": 0.99,
            "reason": "删除词内空格",
            "model": "flash",
        },
    }
    report = build_report([case], [result], {"min_apply_confidence": 0.9})

    applied = apply_report(report, min_confidence=0.9)

    updated = json.loads(path.read_text(encoding="utf-8"))
    assert applied["applied"] == 1
    assert updated[2]["text"] == "糟糕了"
    assert updated[2]["final_adjudication"]["decision"] == "revise"
    assert path.with_suffix(".before-final-adjudication.json").exists()
    summary_path = episode_dir / "final_adjudication_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))["summary"]
    assert summary["resolved_needs_review"] == 1
    assert summary["needs_review_revised"] == 1

    repeated = apply_report(report, min_confidence=0.9)
    assert repeated["applied"] == 0
    assert repeated["summary_files"] == [str(summary_path)]
    repeated_summary = json.loads(summary_path.read_text(encoding="utf-8"))["summary"]
    assert repeated_summary["applied_revisions"] == 1
    assert repeated_summary["changed_this_run"] == 0


def test_manual_overrides_replace_decision_and_add_unselected_segment(tmp_path):
    case = _case(tmp_path)
    episode_dir = tmp_path / "轻音少女_第01集"
    episode_dir.mkdir()
    path = episode_dir / "mqm_reviewed.json"
    path.write_text(
        json.dumps(
            [
                {"ja": "前", "text": "错译"},
                {"ja": "中", "text": "中"},
                {"ja": "しまった", "text": "糟 糕了"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = {
        "case_id": case["case_id"],
        "status": "ok",
        "adjudication": {
            "decision": "revise",
            "corrected_zh": "错误建议",
            "confidence": 0.99,
            "reason": "模型判断",
            "model": "flash",
        },
    }
    report = build_report([case], [result], {"min_apply_confidence": 0.9})
    overrides = {
        "schema": "fansub-final-manual-overrides-v1",
        "reviewer": "qc",
        "overrides": [
            {
                "episode": 1,
                "index": 2,
                "ja": "しまった",
                "current_zh": "糟 糕了",
                "decision": "keep",
                "reason": "人工否决模型建议",
            },
            {
                "episode": 1,
                "index": 0,
                "ja": "前",
                "current_zh": "错译",
                "decision": "revise",
                "corrected_zh": "正确",
                "reason": "人工发现抽样外错译",
            },
        ],
    }

    reviewed = apply_manual_overrides(report, overrides)
    applied = apply_report(reviewed, min_confidence=0.9)

    updated = json.loads(path.read_text(encoding="utf-8"))
    assert reviewed["summary"]["manual_overrides"] == 2
    assert reviewed["summary"]["total"] == 2
    assert applied["applied"] == 1
    assert updated[0]["text"] == "正确"
    assert updated[2]["text"] == "糟 糕了"
    assert updated[2]["final_adjudication"]["model"] == "manual:qc"


def test_manual_override_rejects_stale_translation(tmp_path):
    case = _case(tmp_path)
    report = build_report([], [], {"min_apply_confidence": 0.9})
    report["cases"] = [case]
    overrides = {
        "schema": "fansub-final-manual-overrides-v1",
        "overrides": [
            {
                "episode": 1,
                "index": 2,
                "ja": "しまった",
                "current_zh": "已经变化",
                "decision": "keep",
                "reason": "人工复核",
            }
        ],
    }

    try:
        apply_manual_overrides(report, overrides)
    except ValueError as error:
        assert "Stale manual translation" in str(error)
    else:
        raise AssertionError("stale override must be rejected")


def test_main_applies_existing_report_without_model_pipeline(tmp_path, monkeypatch):
    case = _case(tmp_path)
    episode_dir = tmp_path / "轻音少女_第01集"
    episode_dir.mkdir()
    translated = episode_dir / "mqm_reviewed.json"
    translated.write_text(
        json.dumps(
            [
                {"ja": "前", "text": "前"},
                {"ja": "中", "text": "中"},
                {"ja": "しまった", "text": "糟糕了"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = {
        "case_id": case["case_id"],
        "status": "ok",
        "adjudication": {
            "decision": "revise",
            "corrected_zh": "糟糕了",
            "confidence": 0.99,
            "reason": "删除词内空格",
            "model": "flash",
        },
    }
    report_path = tmp_path / "reviewed.json"
    report_path.write_text(
        json.dumps(
            build_report([case], [result], {"min_apply_confidence": 0.9}),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "adjudicate_fansub_review.py",
            "--report-input",
            str(report_path),
            "--apply",
        ],
    )

    assert main() == 0
    assert (episode_dir / "final_adjudication_summary.json").exists()
