"""Generate short, browser-friendly subtitle preview clips with libass."""

import argparse
import json
import math
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class PreviewOptions:
    start: float = 0.0
    duration: float = 8.0
    width: int = 960
    crf: int = 27
    preset: str = "veryfast"
    mute: bool = False

    def validate(self) -> "PreviewOptions":
        if not math.isfinite(self.start) or self.start < 0:
            raise ValueError("预览起点不能小于 0 秒")
        if not 0.5 <= self.duration <= 60:
            raise ValueError("预览时长必须在 0.5 到 60 秒之间")
        if not 320 <= self.width <= 1920:
            raise ValueError("预览宽度必须在 320 到 1920 之间")
        if not 18 <= self.crf <= 40:
            raise ValueError("CRF 必须在 18 到 40 之间")
        if self.preset not in {
            "ultrafast", "superfast", "veryfast", "faster", "fast", "medium"
        }:
            raise ValueError(f"不支持的 x264 preset：{self.preset}")
        return self


def find_ffmpeg() -> str:
    explicit = os.environ.get("FFMPEG_PATH", "").strip()
    if explicit and Path(explicit).is_file():
        return str(Path(explicit).resolve())
    bundled = sorted((PROJECT_ROOT / ".omo" / "ffmpeg-libass").rglob("ffmpeg.exe"))
    if bundled:
        return str(bundled[0].resolve())
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    raise FileNotFoundError("未找到支持 libass 的 ffmpeg；可设置 FFMPEG_PATH")


def build_preview_command(
    video_path: str | Path,
    subtitle_name: str | Path,
    output_name: str | Path,
    options: PreviewOptions | None = None,
    ffmpeg_path: str | None = None,
) -> list[str]:
    """Build a shell-free ffmpeg command; subtitle/output are cwd-local names."""
    options = (options or PreviewOptions()).validate()
    subtitle_name = Path(subtitle_name)
    output_name = Path(output_name)
    if subtitle_name.name != str(subtitle_name) or subtitle_name.suffix.lower() != ".ass":
        raise ValueError("预览命令要求工作目录内的 ASS 文件名")
    if output_name.name != str(output_name) or output_name.suffix.lower() != ".mp4":
        raise ValueError("预览输出必须是工作目录内的 MP4 文件名")
    command = [
        ffmpeg_path or find_ffmpeg(),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-ss",
        f"{options.start:.3f}",
        "-i",
        str(Path(video_path).resolve()),
        "-t",
        f"{options.duration:.3f}",
        "-map",
        "0:v:0",
        "-vf",
        (
            f"setpts=PTS+{options.start:.3f}/TB,"
            f"ass={subtitle_name.name},"
            "setpts=PTS-STARTPTS,"
            f"scale=w={options.width}:h=-2:force_original_aspect_ratio=decrease"
        ),
        "-c:v",
        "libx264",
        "-preset",
        options.preset,
        "-crf",
        str(options.crf),
        "-pix_fmt",
        "yuv420p",
    ]
    if options.mute:
        command.append("-an")
    else:
        command.extend(["-map", "0:a?", "-c:a", "aac", "-b:a", "96k"])
    command.extend(["-movflags", "+faststart", output_name.name])
    return command


def render_preview(
    video_path: str | Path,
    subtitle_path: str | Path,
    output_path: str | Path,
    options: PreviewOptions | None = None,
    ffmpeg_path: str | None = None,
    runner: Callable = subprocess.run,
) -> dict:
    """Render a short preview without copying the source video or invoking a shell."""
    options = (options or PreviewOptions()).validate()
    video_path = Path(video_path).resolve()
    subtitle_path = Path(subtitle_path).resolve()
    output_path = Path(output_path).resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"视频不存在：{video_path}")
    if not subtitle_path.is_file() or subtitle_path.suffix.lower() != ".ass":
        raise FileNotFoundError(f"ASS 字幕不存在：{subtitle_path}")
    if output_path.suffix.lower() != ".mp4":
        raise ValueError("预览输出必须使用 .mp4 扩展名")
    if output_path == video_path:
        raise ValueError("预览输出不能覆盖输入视频")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_subtitle = output_path.parent / f".preview_{uuid.uuid4().hex}.ass"
    shutil.copy2(subtitle_path, temporary_subtitle)
    command = build_preview_command(
        video_path,
        temporary_subtitle.name,
        output_path.name,
        options,
        ffmpeg_path,
    )
    started = time.perf_counter()
    try:
        completed = runner(
            command,
            cwd=str(output_path.parent),
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            error = (completed.stderr or completed.stdout or "ffmpeg failed")[-2000:]
            raise RuntimeError(f"预览生成失败：{error.strip()}")
    finally:
        temporary_subtitle.unlink(missing_ok=True)
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("ffmpeg 未生成有效预览文件")
    return {
        "video": str(video_path),
        "subtitle": str(subtitle_path),
        "output": str(output_path),
        "output_bytes": output_path.stat().st_size,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "options": asdict(options),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a short subtitle preview MP4")
    parser.add_argument("video")
    parser.add_argument("--subtitle", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=8.0)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--crf", type=int, default=27)
    parser.add_argument("--preset", default="veryfast")
    parser.add_argument("--mute", action="store_true")
    parser.add_argument("--ffmpeg", default="")
    args = parser.parse_args()
    result = render_preview(
        args.video,
        args.subtitle,
        args.output,
        PreviewOptions(
            start=args.start,
            duration=args.duration,
            width=args.width,
            crf=args.crf,
            preset=args.preset,
            mute=args.mute,
        ),
        args.ffmpeg or None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
