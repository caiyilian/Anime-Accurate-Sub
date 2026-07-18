import json

import pytest

from scripts.checkpoint import Checkpoint
from scripts.review_agents import (
    ReviewConfig,
    _api_keys,
    parse_agent_response,
    review_segment,
    review_translation_file,
)


def _response(value):
    return json.dumps(value, ensure_ascii=False)


def _config(**overrides):
    values = {
        "host": "review-host",
        "review_model": "review-model",
        "editor_host": "editor-host",
        "editor_model": "editor-model",
        "max_workers": 1,
        "context_window": 1,
        "min_fix_votes": 2,
        "min_reviewer_confidence": 0.75,
        "min_editor_confidence": 0.8,
        "retries": 1,
    }
    values.update(overrides)
    return ReviewConfig(**values)


def test_prompt_echo_is_not_misclassified_as_ok():
    echoed = "如果没问题只输出 [OK]，需要修改则输出 [FIX]。"
    with pytest.raises(ValueError, match="not a JSON object"):
        parse_agent_response(echoed)


def test_single_missing_closing_brace_is_repaired_without_guessing_verdict():
    parsed = parse_agent_response(
        '{"verdict":"ok","suggested_zh":"","reason":"","confidence":0.99'
    )
    assert parsed["verdict"] == "ok"
    assert parsed["response_repaired"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"verdict": "ok", "suggested_zh": "", "reason": ""},
        {
            "verdict": "ok", "suggested_zh": "", "reason": "",
            "confidence": "0.9",
        },
        {
            "verdict": "ok", "suggested_zh": "", "reason": "",
            "confidence": 1.2,
        },
        {
            "verdict": "ok", "suggested_zh": "", "reason": "",
            "confidence": 0.9, "prompt_echo": "[OK]",
        },
    ],
)
def test_agent_schema_rejects_incomplete_or_untrusted_values(payload):
    with pytest.raises(ValueError):
        parse_agent_response(_response(payload))


def test_api_key_file_loads_multiple_accounts_without_exposing_values(tmp_path):
    key_file = tmp_path / "keys"
    key_file.write_text("key-a\n\nkey-b\nkey-a\n", encoding="utf-8")
    keys = _api_keys(str(key_file))
    assert len(keys) == 2
    assert keys == ["key-a", "key-b"]


def test_consensus_and_high_confidence_editor_apply_fix():
    def chat(messages, **kwargs):
        system = messages[0]["content"]
        if "字幕总编" in system:
            return _response({
                "decision": "replace",
                "corrected_zh": "今天也很有精神啊。",
                "reason": "保留语气并补全句末",
                "confidence": 0.93,
            })
        if "Accuracy Checker" in system or "Naturalness Checker" in system:
            return _response({
                "verdict": "fix",
                "suggested_zh": "今天也很有精神啊。",
                "reason": "原译语气不完整",
                "confidence": 0.91,
            })
        return _response({
            "verdict": "ok", "suggested_zh": "", "reason": "无问题",
            "confidence": 0.9,
        })

    segment = {"ja": "今日も元気だね", "text": "今天也很有精神呢"}
    result = review_segment(0, segment, "目标上下文", "元気 => 精神", _config(), chat)

    assert result["fix_votes"] == 2
    assert result["applied"] is True
    assert result["status"] == "corrected"
    assert result["final_zh"] == "今天也很有精神啊。"


def test_single_reviewer_cannot_trigger_editor_or_rewrite():
    editor_called = False

    def chat(messages, **kwargs):
        nonlocal editor_called
        system = messages[0]["content"]
        if "字幕总编" in system:
            editor_called = True
        verdict = "fix" if "Accuracy Checker" in system else "ok"
        return _response({
            "verdict": verdict,
            "suggested_zh": "候选修改" if verdict == "fix" else "",
            "reason": "测试",
            "confidence": 0.99,
        })

    segment = {"ja": "大丈夫", "text": "没关系"}
    result = review_segment(0, segment, "上下文", "", _config(), chat)

    assert result["fix_votes"] == 1
    assert result["applied"] is False
    assert result["status"] == "needs_review"
    assert editor_called is False


def test_any_reviewer_error_blocks_automatic_rewrite():
    def chat(messages, **kwargs):
        system = messages[0]["content"]
        if "ASR Quality Checker" in system:
            raise RuntimeError("review provider unavailable")
        if "字幕总编" in system:
            return _response({
                "decision": "replace", "corrected_zh": "正确译文",
                "reason": "共识", "confidence": 0.99,
            })
        verdict = "fix" if (
            "Accuracy Checker" in system or "Naturalness Checker" in system
        ) else "ok"
        return _response({
            "verdict": verdict,
            "suggested_zh": "正确译文" if verdict == "fix" else "",
            "reason": "测试", "confidence": 0.99,
        })

    result = review_segment(
        0, {"ja": "原文", "text": "错误译文"}, "上下文", "", _config(), chat
    )
    assert result["fix_votes"] == 2
    assert result["editor_result"]["decision"] == "replace"
    assert result["applied"] is False
    assert result["status"] == "error"


def test_file_review_preserves_metadata_and_resumes_progress(tmp_path):
    source = tmp_path / "translated.json"
    reviewed = tmp_path / "reviewed.json"
    report = tmp_path / "review.json"
    progress = tmp_path / "review.progress.jsonl"
    segments = [
        {"start": 1.0, "end": 2.0, "ja": "はい", "text": "好的", "custom": 1},
        {"start": 2.1, "end": 3.0, "ja": "行こう", "text": "走吧", "custom": 2},
    ]
    source.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")
    calls = 0

    def all_ok(messages, **kwargs):
        nonlocal calls
        calls += 1
        return _response({
            "verdict": "ok", "suggested_zh": "", "reason": "正确",
            "confidence": 0.95,
        })

    first = review_translation_file(
        str(source), str(reviewed), str(report),
        progress_path=str(progress), config=_config(), chat_fn=all_ok,
    )
    assert calls == 10
    assert first["summary"] == {
        "total": 2, "approved": 2, "corrected": 0,
        "needs_review": 0, "errors": 0, "applied": 0,
    }
    output = json.loads(reviewed.read_text(encoding="utf-8"))
    assert output[0]["custom"] == 1
    assert output[1]["text"] == "走吧"
    assert output[0]["multi_agent_review"]["status"] == "approved"

    def must_not_run(*args, **kwargs):
        raise AssertionError("completed progress should be resumed")

    second = review_translation_file(
        str(source), str(reviewed), str(report),
        progress_path=str(progress), config=_config(), chat_fn=must_not_run,
    )
    assert second["summary"]["approved"] == 2


def test_pipeline_regenerates_downstream_files_from_reviewed_json(tmp_path, monkeypatch):
    from scripts import anime_sub

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

    def fake_review(input_path, reviewed_path, report_path, **kwargs):
        items = json.loads(open(input_path, encoding="utf-8").read())
        items[0]["text"] = "好的"
        with open(reviewed_path, "w", encoding="utf-8") as file:
            json.dump(items, file, ensure_ascii=False)
        with open(report_path, "w", encoding="utf-8") as file:
            json.dump({"summary": {"corrected": 1}}, file)
        return {"summary": {"corrected": 1}}

    generated_inputs = []

    def fake_generate(input_path, output_path, **kwargs):
        generated_inputs.append(input_path)
        with open(output_path, "w", encoding="utf-8") as file:
            file.write("subtitle")

    def fake_embed(video_path, subtitle_path, output_path):
        with open(output_path, "wb") as file:
            file.write(b"reviewed-video")

    monkeypatch.setattr(anime_sub, "review_translation_file", fake_review)
    monkeypatch.setattr(anime_sub, "generate_subtitles", fake_generate)
    monkeypatch.setattr(anime_sub, "embed_subtitle", fake_embed)

    result = anime_sub.process_video(
        str(video), str(output_root), config={}, multi_agent_review=True,
    )

    assert result["multi_agent_review"] == {"corrected": 1}
    assert result["stages_completed"] == 6
    assert result["stages_total"] == 6
    assert len(generated_inputs) == 2
    assert all(path.endswith("reviewed.json") for path in generated_inputs)
    saved = json.loads((work_dir / "reviewed.json").read_text(encoding="utf-8"))
    assert saved[0]["text"] == "好的"
