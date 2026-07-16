import io
import json
from pathlib import Path

import pytest

from scripts.web_ui import (
    JobManager,
    build_pipeline_command,
    checkpoint_progress,
    create_app,
    safe_upload_name,
)


def test_safe_upload_name_blocks_traversal_and_unknown_extensions():
    assert safe_upload_name(r"..\轻音少女 01.mp4") == "轻音少女 01.mp4"
    with pytest.raises(ValueError):
        safe_upload_name("payload.exe")


def test_build_pipeline_command_is_shell_free_and_validated(tmp_path):
    command = build_pipeline_command(
        tmp_path / "input;still-video.mp4",
        tmp_path / "output",
        {"backend": "galtransl", "quality_check": True, "translation_batch_size": 6},
        python_executable="python-test",
    )
    assert command[0] == "python-test"
    assert command[2].endswith("input;still-video.mp4")
    assert command[command.index("--backend") + 1] == "galtransl"
    assert "--quality-check" in command
    assert command[command.index("--translation-batch-size") + 1] == "6"
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
    progress = checkpoint_progress(tmp_path / "output", quality_check=True)
    assert progress["completed"] == 2
    assert progress["total"] == 6
    assert progress["active_stage"] == "translate"
    assert progress["failed_stages"] == ["translate"]


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
        files={"video": ("轻音少女01.mp4", b"fake-video", "video/mp4")},
        data={
            "backend": "sakura",
            "quality_check": "true",
            "translation_batch_size": "6",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["options"]["quality_check"] is True
    record = manager._load(body["id"])
    assert Path(record["input_path"]).read_bytes() == b"fake-video"
