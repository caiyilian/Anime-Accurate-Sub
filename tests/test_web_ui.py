import io
import json
from pathlib import Path

import pytest

from scripts.web_ui import (
    JobManager,
    build_pipeline_command,
    checkpoint_progress,
    create_app,
    safe_subtitle_name,
    safe_upload_name,
)


def test_safe_upload_name_blocks_traversal_and_unknown_extensions():
    assert safe_upload_name(r"..\轻音少女 01.mp4") == "轻音少女 01.mp4"
    with pytest.raises(ValueError):
        safe_upload_name("payload.exe")
    assert safe_subtitle_name(r"..\K-ON! S1E01.jp.srt") == "K-ON! S1E01.jp.srt"
    with pytest.raises(ValueError):
        safe_subtitle_name("subtitle.exe")


def test_build_pipeline_command_is_shell_free_and_validated(tmp_path):
    japanese_subtitle = tmp_path / "episode.jp.srt"
    japanese_subtitle.write_text("subtitle", encoding="utf-8")
    command = build_pipeline_command(
        tmp_path / "input;still-video.mp4",
        tmp_path / "output",
        {
            "backend": "galtransl",
            "quality_check": True,
            "multi_agent_review": True,
            "japanese_subtitle_path": str(japanese_subtitle),
            "translation_batch_size": 6,
        },
        python_executable="python-test",
    )
    assert command[0] == "python-test"
    assert command[2].endswith("input;still-video.mp4")
    assert command[command.index("--backend") + 1] == "galtransl"
    assert "--quality-check" in command
    assert "--multi-agent-review" in command
    assert command[command.index("--review-config") + 1].endswith(
        "quality_review.sensenova.json"
    )
    assert command[command.index("--translation-batch-size") + 1] == "6"
    assert command[command.index("--japanese-subtitle") + 1] == str(japanese_subtitle)
    with pytest.raises(ValueError):
        build_pipeline_command("video.mp4", "out", {"backend": "sakura && calc"})


def test_checkpoint_progress_reads_real_stage_state(tmp_path):
    episode = tmp_path / "output" / "episode"
    episode.mkdir(parents=True)
    (episode / "checkpoint.json").write_text(
        json.dumps(
            {
                "extract_audio": {"status": "completed"},
                "asr": {"status": "completed"},
                "translate": {"status": "failed"},
            }
        ),
        encoding="utf-8",
    )
    progress = checkpoint_progress(
        tmp_path / "output", quality_check=True, multi_agent_review=True
    )
    assert progress["completed"] == 2
    assert progress["total"] == 7
    assert progress["active_stage"] == "translate"
    assert progress["failed_stages"] == ["translate"]


def test_checkpoint_progress_replaces_audio_and_asr_for_japanese_source(tmp_path):
    episode = tmp_path / "output" / "episode"
    episode.mkdir(parents=True)
    (episode / "checkpoint.json").write_text(
        json.dumps(
            {
                "japanese_subtitle": {"status": "completed"},
                "translate": {"status": "completed"},
            }
        ),
        encoding="utf-8",
    )

    progress = checkpoint_progress(
        tmp_path / "output", quality_check=True, japanese_subtitle=True
    )
    assert progress["completed"] == 2
    assert progress["total"] == 5
    assert progress["active_stage"] == "subtitle"


def test_job_download_path_stays_inside_output(tmp_path):
    manager = JobManager(tmp_path / "jobs")
    record, input_path = manager.create_job("episode.mp4", {"backend": "sakura"})
    manager.save_upload(input_path, io.BytesIO(b"video"))
    output = Path(record["output_dir"])
    subtitle = output / "episode" / "episode.ass"
    subtitle.parent.mkdir()
    subtitle.write_text("subtitle", encoding="utf-8")
    assert manager.downloadable_path(record["id"], "episode/episode.ass") == subtitle
    with pytest.raises(FileNotFoundError):
        manager.downloadable_path(record["id"], "../../input/episode.mp4")
    copied_video = output / "episode" / "episode.mp4"
    copied_video.write_bytes(b"original")
    with pytest.raises(FileNotFoundError):
        manager.downloadable_path(record["id"], "episode/episode.mp4")


def test_fastapi_health_and_empty_job_list(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    client = TestClient(create_app(tmp_path / "jobs"))
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/jobs").json() == []
    page = client.get("/")
    assert page.status_code == 200
    assert "Anime Accurate Sub" in page.text


def test_fastapi_upload_saves_video_and_starts_job(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    app = create_app(tmp_path / "jobs")
    manager = app.state.job_manager

    def fake_start(job_id):
        record = manager._load(job_id)
        record["status"] = "pending"
        manager._save(record)
        return manager._public_record(record)

    monkeypatch.setattr(manager, "start_job", fake_start)
    client = TestClient(app)
    response = client.post(
        "/api/jobs",
        files={
            "video": ("轻音少女01.mp4", b"fake-video", "video/mp4"),
            "japanese_subtitle": (
                "K-ON! S1E01.jp.srt",
                "1\n00:00:01,000 --> 00:00:02,000\nおはよう\n".encode("utf-8"),
                "application/x-subrip",
            ),
        },
        data={
            "backend": "sakura",
            "quality_check": "true",
            "multi_agent_review": "true",
            "translation_batch_size": "6",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["options"]["quality_check"] is True
    assert body["options"]["multi_agent_review"] is True
    assert body["options"]["japanese_subtitle_path"].endswith("K-ON! S1E01.jp.srt")
    record = manager._load(body["id"])
    assert Path(record["input_path"]).read_bytes() == b"fake-video"
    assert Path(record["options"]["japanese_subtitle_path"]).read_text(
        encoding="utf-8"
    ).endswith("おはよう\n")


def test_fastapi_proofreading_updates_json_and_regenerates_subtitles(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    app = create_app(tmp_path / "jobs")
    manager = app.state.job_manager
    record, input_path = manager.create_job("episode.mp4", {"backend": "sakura"})
    manager.save_upload(input_path, io.BytesIO(b"video"))
    episode_dir = Path(record["output_dir"]) / "episode"
    episode_dir.mkdir()
    translated = episode_dir / "translated.json"
    translated.write_text(
        json.dumps(
            [{"start": 0, "end": 2, "ja": "おはよう", "text": "早上好"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client = TestClient(app)

    sheet_response = client.get(f"/api/jobs/{record['id']}/proofread")
    assert sheet_response.status_code == 200
    sheet = sheet_response.json()
    correction = {
        **sheet["items"][0],
        "corrected_text": "早安",
        "note": "Web test",
    }
    save_response = client.put(
        f"/api/jobs/{record['id']}/proofread",
        json={
            "schema": sheet["schema"],
            "source_sha256": sheet["source_sha256"],
            "items": [correction],
        },
    )

    assert save_response.status_code == 200
    assert save_response.json()["applied"] == 1
    assert json.loads(translated.read_text(encoding="utf-8"))[0]["text"] == "早安"
    assert (episode_dir / "episode.srt").exists()
    assert (episode_dir / "episode.ass").exists()
    assert "人工校对" in client.get(f"/api/jobs/{record['id']}").text
    page = client.get(f"/proofread/{record['id']}")
    assert page.status_code == 200
    assert "保存修正并重建字幕" in page.text


def test_fastapi_video_preview_page_and_api(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    app = create_app(tmp_path / "jobs")
    manager = app.state.job_manager
    record, input_path = manager.create_job("episode.mp4", {"backend": "sakura"})
    manager.save_upload(input_path, io.BytesIO(b"video"))
    episode_dir = Path(record["output_dir"]) / "episode"
    episode_dir.mkdir()
    (episode_dir / "episode.ass").write_text("subtitle", encoding="utf-8")

    def fake_render(video, subtitle, output, options):
        output.write_bytes(b"preview")
        return {
            "output": str(output),
            "output_bytes": len(b"preview"),
            "elapsed_s": 0.01,
            "options": {"duration": options.duration},
        }

    monkeypatch.setattr("scripts.web_ui.render_video_preview", fake_render)
    client = TestClient(app)
    page = client.get(f"/preview/{record['id']}")
    assert page.status_code == 200
    assert "字幕效果预览" in page.text

    response = client.post(
        f"/api/jobs/{record['id']}/preview",
        json={"start": 10, "duration": 5, "width": 640},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["duration"] == 5
    assert result["preview_url"].endswith("episode/episode_preview.mp4")
    assert client.get(result["preview_url"]).content == b"preview"
    assert "字幕预览" in client.get(f"/api/jobs/{record['id']}").text
