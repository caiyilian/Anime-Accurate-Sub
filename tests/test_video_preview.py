from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.video_preview import PreviewOptions, build_preview_command, render_preview


def test_preview_options_reject_unsafe_ranges():
    with pytest.raises(ValueError, match="起点"):
        PreviewOptions(start=-1).validate()
    with pytest.raises(ValueError, match="起点"):
        PreviewOptions(start=float("nan")).validate()
    with pytest.raises(ValueError, match="时长"):
        PreviewOptions(duration=61).validate()
    with pytest.raises(ValueError, match="宽度"):
        PreviewOptions(width=200).validate()


def test_build_preview_command_is_shell_free_and_browser_friendly(tmp_path):
    command = build_preview_command(
        tmp_path / "episode;safe.mp4",
        ".preview_test.ass",
        "episode_preview.mp4",
        PreviewOptions(start=844.2, duration=8, width=960, mute=True),
        ffmpeg_path="ffmpeg-test",
    )

    assert command[0] == "ffmpeg-test"
    assert command[command.index("-ss") + 1] == "844.200"
    assert command[command.index("-t") + 1] == "8.000"
    video_filter = command[command.index("-vf") + 1]
    assert video_filter.startswith("setpts=PTS+844.200/TB,ass=.preview_test.ass")
    assert "setpts=PTS-STARTPTS" in video_filter
    assert "scale=w=960" in video_filter
    assert "-an" in command
    assert command[-1] == "episode_preview.mp4"


def test_render_preview_cleans_temporary_subtitle(tmp_path):
    video = tmp_path / "episode.mp4"
    subtitle = tmp_path / "episode.ass"
    output = tmp_path / "episode_preview.mp4"
    video.write_bytes(b"video")
    subtitle.write_text("subtitle", encoding="utf-8")
    captured = {}

    def fake_runner(command, cwd, **kwargs):
        captured["command"] = command
        captured["cwd"] = cwd
        ass_filter = next(
            item for item in command[command.index("-vf") + 1].split(",")
            if item.startswith("ass=")
        )
        preview_ass = Path(cwd) / ass_filter[4:]
        assert preview_ass.read_text(encoding="utf-8") == "subtitle"
        (Path(cwd) / command[-1]).write_bytes(b"preview-video")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = render_preview(
        video,
        subtitle,
        output,
        PreviewOptions(duration=2),
        ffmpeg_path="ffmpeg-test",
        runner=fake_runner,
    )

    assert result["output_bytes"] == len(b"preview-video")
    assert output.read_bytes() == b"preview-video"
    assert not list(tmp_path.glob(".preview_*.ass"))
    assert captured["cwd"] == str(tmp_path.resolve())


def test_render_preview_surfaces_ffmpeg_error_and_still_cleans_temp(tmp_path):
    video = tmp_path / "episode.mp4"
    subtitle = tmp_path / "episode.ass"
    video.write_bytes(b"video")
    subtitle.write_text("subtitle", encoding="utf-8")

    def failing_runner(command, cwd, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="invalid filter")

    with pytest.raises(RuntimeError, match="invalid filter"):
        render_preview(
            video,
            subtitle,
            tmp_path / "preview.mp4",
            ffmpeg_path="ffmpeg-test",
            runner=failing_runner,
        )
    assert not list(tmp_path.glob(".preview_*.ass"))
