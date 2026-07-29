import json
import os
import time

import pytest

from scripts.season_monitor import SeasonProgressMonitor
from scripts.web_ui import create_app


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_season_monitor_reports_weighted_review_progress_and_redacts_logs(tmp_path):
    root = tmp_path / "season"
    episode1 = root / "轻音少女_第01集"
    episode2 = root / "轻音少女_第02集"
    episode1.mkdir(parents=True)
    episode2.mkdir()
    stages = (
        "japanese_subtitle",
        "translate",
        "multi_agent_review",
        "mqm_quality_review",
        "subtitle",
        "embed_subtitle",
        "quality_check",
    )
    _write_json(
        episode1 / "checkpoint.json",
        {stage: {"status": "completed"} for stage in stages},
    )
    _write_json(
        episode1 / "mqm_quality_report.json",
        {"summary": {"approved": 9, "corrected": 1, "needs_review": 2, "errors": 0, "applied": 1}},
    )
    _write_json(
        episode1 / "final_adjudication_summary.json",
        {
            "summary": {
                "reviewed": 4,
                "resolved_needs_review": 2,
                "needs_review_kept": 1,
                "needs_review_revised": 1,
            }
        },
    )
    _write_json(
        episode2 / "checkpoint.json",
        {
            "japanese_subtitle": {"status": "completed"},
            "translate": {"status": "completed"},
        },
    )
    _write_json(episode2 / "translated.json", [{"text": str(i)} for i in range(4)])
    rows = [
        {"position": 0, "status": "approved"},
        {"position": 1, "status": "approved"},
        {"position": 1, "status": "corrected"},
        {"position": 2, "status": "needs_review"},
    ]
    progress = episode2 / "multi_agent_review.progress.jsonl"
    progress.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n{unfinished",
        encoding="utf-8",
    )
    (root / "full_run_v3.stdout.log").write_text(
        "[3/4] needs_review\nAuthorization: Bearer secret-token\napi_key=verysecret",
        encoding="utf-8",
    )

    snapshot = SeasonProgressMonitor(root, episode_count=3).snapshot()

    assert snapshot["status"] == "running"
    assert snapshot["completed_episodes"] == 1
    assert snapshot["active_episode"] == 2
    assert snapshot["overall_percent"] == 46.8
    current = snapshot["episodes"][1]
    assert current["active_stage"] == "multi_agent_review"
    assert current["review"] == {
        "processed": 3,
        "total": 4,
        "percent": 75.0,
        "statuses": {"approved": 1, "corrected": 1, "needs_review": 1},
    }
    assert "secret-token" not in snapshot["log_tail"]
    assert "verysecret" not in snapshot["log_tail"]
    final_mqm = snapshot["episodes"][0]["quality"]["mqm"]
    assert final_mqm["approved"] == 10
    assert final_mqm["corrected"] == 2
    assert final_mqm["needs_review"] == 0
    assert final_mqm["final_reviewed"] == 4


def test_season_monitor_marks_old_artifacts_as_stale(tmp_path):
    root = tmp_path / "season"
    episode = root / "轻音少女_第01集"
    episode.mkdir(parents=True)
    checkpoint = episode / "checkpoint.json"
    _write_json(checkpoint, {"japanese_subtitle": {"status": "completed"}})
    log = root / "full_run_v3.stdout.log"
    log.write_text("old progress", encoding="utf-8")
    old = time.time() - 120
    os.utime(checkpoint, (old, old))
    os.utime(log, (old, old))

    snapshot = SeasonProgressMonitor(
        root, episode_count=2, stale_after_seconds=30
    ).snapshot()

    assert snapshot["status"] == "stale"
    assert snapshot["status_label"] == "等待新进度"


def test_fastapi_exposes_read_only_season_monitor(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    season_root = tmp_path / "private-path" / "season"
    client = TestClient(
        create_app(
            tmp_path / "jobs",
            season_root=season_root,
            season_episode_count=2,
        )
    )

    page = client.get("/monitor")
    assert page.status_code == 200
    assert "轻音少女 S1" in page.text
    assert "每 4 秒" in page.text
    response = client.get("/api/monitor")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "waiting"
    assert payload["episode_count"] == 2
    assert str(tmp_path) not in response.text
