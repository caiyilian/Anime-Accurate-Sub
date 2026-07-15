import json
import subprocess
import sys
import zipfile
from pathlib import Path

from scripts.eval_asr_reference import (
    character_error_rate,
    evaluate_dataset,
    normalize_japanese,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_japanese_normalization_and_cer_ignore_spacing_and_punctuation():
    assert normalize_japanese("お姉ちゃん、 起きて！") == "お姉ちゃん起きて"
    assert character_error_rate("軽音部！", "軽音部") == 0.0
    assert character_error_rate("軽音部", "軽音") == 1 / 3


def test_dataset_reads_srt_from_zip_and_filters_oped(tmp_path):
    episode_dir = tmp_path / "episode_01"
    episode_dir.mkdir()
    (episode_dir / "asr_results.json").write_text(
        json.dumps(
            [
                {"start": 1.0, "end": 2.0, "text": "おはよう"},
                {"start": 20.0, "end": 21.0, "text": "軽音部"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (episode_dir / "oped_ranges.json").write_text(
        json.dumps([{"kind": "OP", "start": 9.0, "end": 12.0}]),
        encoding="utf-8",
    )
    srt = """1
00:00:01,000 --> 00:00:02,000
おはよう！

2
00:00:10,000 --> 00:00:11,000
歌です

3
00:00:20,000 --> 00:00:21,000
軽音部。
"""
    archive = tmp_path / "references.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("nested/K-ON! S1E01.jp.srt", srt.encode("utf-8"))

    report = evaluate_dataset(tmp_path, archive, episodes=[1])

    assert report["aggregate"]["missing_episodes"] == []
    assert report["aggregate"]["reference_segments"] == 2
    assert report["aggregate"]["mean_reference_coverage"] == 1.0
    assert report["aggregate"]["corpus_cer"] == 0.0
    assert report["episodes"][0]["oped_ranges"] == [{"start": 9.0, "end": 12.0}]


def test_cli_can_run_as_a_script():
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "eval_asr_reference.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--reference-archive" in result.stdout
