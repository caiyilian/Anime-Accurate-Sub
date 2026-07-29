import json

from scripts.adjudicate_fansub_review import (
    _parse_decision,
    adjudicate_case,
    apply_report,
    build_report,
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
