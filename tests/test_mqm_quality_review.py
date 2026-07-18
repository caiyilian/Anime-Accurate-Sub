import json

import pytest

from scripts.mqm_quality_review import (
    MQMConfig,
    MQM_DIMENSIONS,
    parse_judge_response,
    _context,
    _segment_key,
    review_segment,
    review_translation_file,
)


def _config(**overrides):
    values = {
        "provider": "ollama",
        "judge_models": ["flash-judge", "deepseek-judge"],
        "editor_model": "flash-editor",
        "max_workers": 1,
        "context_window": 1,
        "review_threshold": 80,
        "min_judge_confidence": 0.75,
        "min_editor_confidence": 0.85,
        "min_final_score": 80,
        "min_improvement": 5,
        "retries": 1,
    }
    values.update(overrides)
    return MQMConfig(**values).validate()


def _judge_payload(
    recommendation="keep",
    score=92,
    confidence=0.95,
    suggested_zh="",
    severity="none",
):
    errors = []
    if severity != "none":
        errors = [
            {
                "category": "accuracy",
                "severity": severity,
                "source_span": "私は猫です",
                "target_span": "今天天气很好",
                "explanation": "语义不符",
            }
        ]
    return {
        "dimensions": {
            name: {
                "score": score,
                "severity": severity if name == "accuracy" else "none",
                "reason": "测试依据",
            }
            for name in MQM_DIMENSIONS
        },
        "errors": errors,
        "recommendation": recommendation,
        "suggested_zh": suggested_zh,
        "confidence": confidence,
    }


def _response(value):
    return json.dumps(value, ensure_ascii=False)


@pytest.mark.parametrize(
    "payload",
    [
        "评分: 90\n理由: 正确",
        _response({**_judge_payload(), "prompt_echo": "评分: 90"}),
        _response(
            {
                **_judge_payload(),
                "dimensions": {
                    **_judge_payload()["dimensions"],
                    "accuracy": {
                        "score": "90",
                        "severity": "none",
                        "reason": "字符串分数",
                    },
                },
            }
        ),
    ],
)
def test_strict_mqm_parser_rejects_keyword_guessing_and_schema_violations(payload):
    with pytest.raises(ValueError):
        parse_judge_response(payload)


def test_dual_judges_editor_and_dual_rescore_apply_only_proven_improvement():
    calls = []

    def chat(messages, **kwargs):
        calls.append(kwargs["model"])
        system = messages[0]["content"]
        prompt = messages[1]["content"]
        if "质量总编" in system:
            return _response(
                {
                    "decision": "revise",
                    "corrected_zh": "我是猫。",
                    "reason": "修正完全错误的语义",
                    "confidence": 0.98,
                }
            )
        if "原中文：我是猫。" in prompt or "目标中文：我是猫。" in prompt:
            return _response(_judge_payload(score=94))
        return _response(
            _judge_payload(
                recommendation="revise",
                score=20,
                suggested_zh="我是猫。",
                severity="critical",
            )
        )

    result = review_segment(
        0,
        {"ja": "私は猫です。", "text": "今天天气很好。"},
        "目标上下文",
        "",
        _config(),
        chat,
    )

    assert result["issue_votes"] == 2
    assert result["baseline_score"] == 20
    assert result["final_score"] == 94
    assert result["eligible_for_application"] is True
    assert result["status"] == "corrected"
    assert result["final_zh"] == "我是猫。"
    assert calls.count("flash-judge") == 2
    assert calls.count("deepseek-judge") == 2
    assert calls.count("flash-editor") == 1


def test_clean_translation_does_not_call_editor_or_rewrite():
    def chat(messages, **kwargs):
        if kwargs["model"] == "flash-editor":
            raise AssertionError("editor should not run")
        return _response(_judge_payload(score=92))

    result = review_segment(
        0, {"ja": "おはよう", "text": "早上好"}, "上下文", "", _config(), chat
    )

    assert result["status"] == "approved"
    assert result["issue_votes"] == 0
    assert result["eligible_for_application"] is False


def test_low_score_triggers_editor_even_if_judge_recommendation_is_inconsistent():
    editor_calls = 0

    def chat(messages, **kwargs):
        nonlocal editor_calls
        if kwargs["model"] == "flash-editor":
            editor_calls += 1
            return _response(
                {
                    "decision": "keep", "corrected_zh": "",
                    "reason": "证据不足", "confidence": 0.9,
                }
            )
        return _response(_judge_payload(recommendation="keep", score=70))

    result = review_segment(
        0, {"ja": "原文", "text": "译文"}, "上下文", "", _config(), chat
    )

    assert result["issue_votes"] == 2
    assert editor_calls == 1
    assert result["status"] == "needs_review"


def test_any_judge_failure_blocks_editor_and_application():
    def chat(messages, **kwargs):
        if kwargs["model"] == "deepseek-judge":
            raise RuntimeError("judge unavailable")
        if kwargs["model"] == "flash-editor":
            raise AssertionError("editor must not run with a missing judge")
        return _response(
            _judge_payload(
                recommendation="revise",
                score=30,
                suggested_zh="我是猫。",
                severity="major",
            )
        )

    result = review_segment(
        0,
        {"ja": "私は猫です。", "text": "今天天气很好。"},
        "上下文",
        "",
        _config(),
        chat,
    )

    assert result["status"] == "error"
    assert result["eligible_for_application"] is False
    assert result["editor"] is None


def test_editor_candidate_is_rejected_when_rescore_does_not_meet_both_gates():
    judge_call_count = {"flash-judge": 0, "deepseek-judge": 0}

    def chat(messages, **kwargs):
        model = kwargs["model"]
        if model == "flash-editor":
            return _response(
                {
                    "decision": "revise",
                    "corrected_zh": "候选译文",
                    "reason": "尝试修正",
                    "confidence": 0.95,
                }
            )
        judge_call_count[model] += 1
        if judge_call_count[model] == 1:
            return _response(
                _judge_payload(
                    recommendation="revise",
                    score=60,
                    suggested_zh="候选译文",
                    severity="major",
                )
            )
        score = 90 if model == "flash-judge" else 78
        recommendation = "keep" if model == "flash-judge" else "revise"
        return _response(
            _judge_payload(
                recommendation=recommendation,
                score=score,
                suggested_zh="更好的译文" if recommendation == "revise" else "",
                severity="minor" if recommendation == "revise" else "none",
            )
        )

    result = review_segment(
        0, {"ja": "原文", "text": "错误译文"}, "上下文", "", _config(), chat
    )

    assert result["status"] == "needs_review"
    assert result["final_score"] == 78
    assert result["eligible_for_application"] is False
    assert result["final_zh"] == "错误译文"


def test_file_review_preserves_metadata_supports_dry_run_and_resumes(tmp_path):
    source = tmp_path / "reviewed.json"
    output = tmp_path / "mqm_reviewed.json"
    report = tmp_path / "mqm_report.json"
    progress = tmp_path / "mqm.progress.jsonl"
    source.write_text(
        json.dumps(
            [
                {
                    "start": 1.0,
                    "end": 2.0,
                    "ja": "私は猫です。",
                    "text": "今天天气很好。",
                    "source": "external_japanese_subtitle",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls = 0

    def chat(messages, **kwargs):
        nonlocal calls
        calls += 1
        system = messages[0]["content"]
        prompt = messages[1]["content"]
        if "质量总编" in system:
            return _response(
                {
                    "decision": "revise", "corrected_zh": "我是猫。",
                    "reason": "语义修正", "confidence": 0.99,
                }
            )
        if "目标中文：我是猫。" in prompt:
            return _response(_judge_payload(score=95))
        return _response(
            _judge_payload(
                recommendation="revise", score=10, suggested_zh="我是猫。",
                severity="critical",
            )
        )

    first = review_translation_file(
        str(source),
        str(output),
        str(report),
        progress_path=str(progress),
        config=_config(),
        apply_fixes=False,
        chat_fn=chat,
    )
    assert first["summary"]["eligible"] == 1
    assert first["summary"]["applied"] == 0
    saved = json.loads(output.read_text(encoding="utf-8"))[0]
    assert saved["text"] == "今天天气很好。"
    assert saved["source"] == "external_japanese_subtitle"
    assert saved["mqm_review"]["eligible_for_application"] is True
    first_call_count = calls

    def must_not_run(*args, **kwargs):
        raise AssertionError("matching MQM progress should resume")

    second = review_translation_file(
        str(source),
        str(output),
        str(report),
        progress_path=str(progress),
        config=_config(),
        apply_fixes=True,
        chat_fn=must_not_run,
    )
    assert calls == first_call_count
    assert second["summary"]["applied"] == 1
    assert json.loads(output.read_text(encoding="utf-8"))[0]["text"] == "我是猫。"


def test_file_review_retries_error_progress_without_repeating_success(tmp_path):
    source = tmp_path / "reviewed.json"
    output = tmp_path / "mqm_reviewed.json"
    report = tmp_path / "mqm_report.json"
    progress = tmp_path / "mqm.progress.jsonl"
    source.write_text(
        json.dumps(
            [
                {"ja": "おはよう", "text": "早上好"},
                {"ja": "こんばんは", "text": "晚上好"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    deepseek_calls = 0
    successful_segment_calls = 0

    def transient_failure(messages, **kwargs):
        nonlocal deepseek_calls, successful_segment_calls
        prompt = messages[1]["content"]
        if "目标日文：こんばんは" in prompt:
            successful_segment_calls += 1
        if (
            kwargs["model"] == "deepseek-judge"
            and "目标日文：おはよう" in prompt
        ):
            deepseek_calls += 1
            if deepseek_calls == 1:
                raise RuntimeError("temporary empty response")
        return _response(_judge_payload(score=92))

    result = review_translation_file(
        str(source), str(output), str(report),
        progress_path=str(progress), config=_config(), chat_fn=transient_failure,
    )

    assert result["summary"]["approved"] == 2
    assert result["summary"]["errors"] == 0
    assert deepseek_calls == 2
    assert successful_segment_calls == 2
    statuses = [
        json.loads(line)["status"]
        for line in progress.read_text(encoding="utf-8").splitlines()
    ]
    assert statuses == ["error", "approved", "approved"]

    def must_not_run(*args, **kwargs):
        raise AssertionError("successful retry should be resumed")

    review_translation_file(
        str(source), str(output), str(report),
        progress_path=str(progress), config=_config(), chat_fn=must_not_run,
    )


def test_file_review_blocks_completion_after_persistent_errors(tmp_path):
    source = tmp_path / "reviewed.json"
    output = tmp_path / "mqm_reviewed.json"
    report = tmp_path / "mqm_report.json"
    source.write_text(
        json.dumps([{"ja": "おはよう", "text": "早上好"}], ensure_ascii=False),
        encoding="utf-8",
    )

    def persistent_failure(messages, **kwargs):
        if kwargs["model"] == "deepseek-judge":
            raise RuntimeError("provider unavailable")
        return _response(_judge_payload(score=92))

    with pytest.raises(RuntimeError, match="incomplete segment"):
        review_translation_file(
            str(source), str(output), str(report),
            config=_config(), chat_fn=persistent_failure,
        )

    assert json.loads(report.read_text(encoding="utf-8"))["summary"]["errors"] == 1


def test_progress_key_changes_when_neighboring_context_changes():
    config = _config()
    first = [
        {"ja": "前文", "text": "原前文"},
        {"ja": "目标", "text": "目标译文"},
    ]
    changed = [
        {"ja": "前文", "text": "已修正前文"},
        {"ja": "目标", "text": "目标译文"},
    ]

    first_key = _segment_key(1, first[1], config.signature(), _context(first, 1, 1))
    changed_key = _segment_key(
        1, changed[1], config.signature(), _context(changed, 1, 1)
    )

    assert first_key != changed_key


def test_pipeline_regenerates_subtitles_from_mqm_reviewed_output(tmp_path, monkeypatch):
    from pathlib import Path

    from scripts import anime_sub
    from scripts.checkpoint import Checkpoint

    video = tmp_path / "episode.mp4"
    video.write_bytes(b"video")
    output_root = tmp_path / "output"
    work_dir = output_root / video.stem
    work_dir.mkdir(parents=True)
    translated = [{"start": 0.0, "end": 1.0, "ja": "はい", "text": "好"}]
    (work_dir / "translated.json").write_text(
        json.dumps(translated, ensure_ascii=False), encoding="utf-8"
    )
    checkpoint = Checkpoint(str(work_dir))
    for stage in ("extract_audio", "asr", "translate", "subtitle", "embed_subtitle"):
        checkpoint.mark_completed(stage)

    def fake_mqm(input_path, output_path, report_path, **kwargs):
        items = json.loads(Path(input_path).read_text(encoding="utf-8"))
        items[0]["text"] = "好的"
        Path(output_path).write_text(
            json.dumps(items, ensure_ascii=False), encoding="utf-8"
        )
        Path(report_path).write_text(
            json.dumps({"summary": {"corrected": 1}}), encoding="utf-8"
        )
        return {"summary": {"corrected": 1}}

    generated_inputs = []

    def fake_generate(input_path, output_path, **kwargs):
        generated_inputs.append(input_path)
        Path(output_path).write_text("subtitle", encoding="utf-8")

    def fake_embed(video_path, subtitle_path, output_path):
        Path(output_path).write_bytes(b"mqm-video")

    monkeypatch.setattr(anime_sub, "review_mqm_translation_file", fake_mqm)
    monkeypatch.setattr(anime_sub, "generate_subtitles", fake_generate)
    monkeypatch.setattr(anime_sub, "embed_subtitle", fake_embed)

    result = anime_sub.process_video(
        str(video), str(output_root), config={}, mqm_quality_review=True
    )

    assert result["mqm_quality_review"] == {"corrected": 1}
    assert result["stages_completed"] == 6
    assert result["stages_total"] == 6
    assert len(generated_inputs) == 2
    assert all(path.endswith("mqm_reviewed.json") for path in generated_inputs)
