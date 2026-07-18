# S13.3: External subtitle extraction - detect embedded tracks + extract
#
# Checks video files for embedded subtitle tracks, extracts them if found.
# Priority: zh > ja > en (Chinese subtitles preferred, then Japanese, then English)
#
# Usage:
#   python scripts/extract_subs.py --video video.mp4
#   python scripts/extract_subs.py --video video.mp4 --output subs.srt
#   python scripts/extract_subs.py --video video.mp4 --info
#   python scripts/extract_subs.py --batch data/video/*.mp4

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import pysubs2

from scripts.oped_detector import infer_episode_number

# Language priority for subtitle extraction (higher = better)
LANG_PRIORITY = {
    "chi": 4, "zho": 4, "zh": 4, "chs": 4, "cht": 4,  # Chinese
    "jpn": 3, "ja": 3,                                    # Japanese
    "eng": 2, "en": 2,                                     # English
}

SUBTITLE_CODECS = {"subrip", "ass", "ssa", "webvtt", "srt", "mov_text", "text"}
JAPANESE_LANGUAGES = {"jpn", "ja", "jp"}
SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt"}
JAPANESE_NAME_MARKERS = re.compile(
    r"(?:^|[. _\-])(ja|jp|jpn|japanese|日本語)(?:[. _\-]|$)", re.IGNORECASE
)


def get_subtitle_tracks(video_path: str) -> List[dict]:
    """Detect embedded subtitle tracks in video file using ffprobe."""
    ffprobe = "ffprobe"
    explicit_ffmpeg = os.environ.get("FFMPEG_PATH", "").strip()
    if explicit_ffmpeg:
        sibling = Path(explicit_ffmpeg).with_name(
            "ffprobe.exe" if os.name == "nt" else "ffprobe"
        )
        if sibling.exists():
            ffprobe = str(sibling)
    cmd = [
        ffprobe, "-v", "quiet", "-print_format", "json",
        "-show_streams", "-select_streams", "s",
        video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        tracks = []
        for s in streams:
            lang = s.get("tags", {}).get("language", "und")
            codec = s.get("codec_name", "")
            index = s.get("index", 0)
            tracks.append({
                "index": index,
                "language": lang,
                "codec": codec,
                "title": s.get("tags", {}).get("title", ""),
                "priority": LANG_PRIORITY.get(lang, 1),
            })
        return tracks
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return []


def extract_subtitle(video_path: str, track_index: int,
                      output_path: str) -> Optional[str]:
    """Extract a specific subtitle track from video."""
    ext = Path(output_path).suffix or ".srt"
    cmd = [
        os.environ.get("FFMPEG_PATH", "ffmpeg"), "-y", "-i", video_path,
        "-map", f"0:{track_index}",
        "-c", "copy" if ext == ".sup" else "srt",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and Path(output_path).exists():
            return output_path
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def select_japanese_track(tracks: List[dict]) -> Optional[dict]:
    """Select a text-based Japanese track without ever falling back to Chinese."""
    candidates = []
    for track in tracks:
        language = str(track.get("language", "")).lower()
        title = str(track.get("title", ""))
        is_japanese = language in JAPANESE_LANGUAGES or bool(
            re.search(r"japanese|日本語", title, flags=re.IGNORECASE)
        )
        if is_japanese and track.get("codec") in SUBTITLE_CODECS:
            candidates.append(track)
    return sorted(candidates, key=lambda item: item.get("index", 0))[0] if candidates else None


def load_japanese_subtitle(subtitle_path: str | Path) -> list[dict]:
    """Load a Japanese text subtitle into the ASR-compatible segment schema."""
    path = Path(subtitle_path)
    if not path.is_file():
        raise FileNotFoundError(f"Japanese subtitle does not exist: {path}")
    if path.suffix.lower() not in SUBTITLE_EXTENSIONS:
        raise ValueError(f"Unsupported Japanese subtitle format: {path.suffix}")

    subtitles = None
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "cp932", "utf-16"):
        try:
            subtitles = pysubs2.load(str(path), encoding=encoding)
            break
        except (UnicodeDecodeError, UnicodeError) as error:
            last_error = error
    if subtitles is None:
        raise ValueError(f"Unable to decode Japanese subtitle: {path}") from last_error

    segments = []
    kana_count = 0
    for index, event in enumerate(subtitles.events):
        text = " ".join(
            part.strip() for part in re.split(r"[\r\n]+", event.plaintext) if part.strip()
        )
        if not text or event.end <= event.start:
            continue
        if "\ufffd" in text:
            raise ValueError(f"Japanese subtitle contains replacement characters: {path}")
        kana_count += len(re.findall(r"[\u3040-\u30ff]", text))
        segments.append(
            {
                "start": round(event.start / 1000.0, 3),
                "end": round(event.end / 1000.0, 3),
                "text": text,
                "confidence": 1.0,
                "source": "external_japanese_subtitle",
                "subtitle_index": index,
            }
        )
    if not segments:
        raise ValueError(f"Japanese subtitle contains no timed text: {path}")
    if kana_count == 0:
        raise ValueError(f"Subtitle does not appear to contain Japanese text: {path}")
    return sorted(segments, key=lambda item: (item["start"], item["end"]))


def subtitle_fingerprint(subtitle_path: str | Path) -> str:
    """Return a stable content fingerprint used for checkpoint invalidation."""
    digest = hashlib.sha256()
    with Path(subtitle_path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_japanese_sidecar(video_path: str | Path, search_dir: str | Path) -> Optional[Path]:
    """Match one validated Japanese sidecar by exact stem or episode number."""
    video = Path(video_path)
    directory = Path(search_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"Japanese subtitle directory does not exist: {directory}")

    files = sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in SUBTITLE_EXTENSIONS
    )
    exact = [
        path for path in files
        if path.stem == video.stem or path.stem.startswith(video.stem + ".")
    ]
    episode = infer_episode_number(video.name)
    episode_matches = [
        path for path in files
        if episode is not None and infer_episode_number(path.name) == episode
    ]
    candidates = exact or episode_matches
    marked = [path for path in candidates if JAPANESE_NAME_MARKERS.search(path.stem)]
    candidates = marked or candidates

    valid = []
    for path in candidates:
        try:
            load_japanese_subtitle(path)
            valid.append(path)
        except (FileNotFoundError, ValueError):
            continue
    if len(valid) > 1:
        raise ValueError(
            f"Multiple Japanese subtitles match {video.name}: "
            + ", ".join(path.name for path in valid)
        )
    return valid[0] if valid else None


def resolve_japanese_subtitle(
    video_path: str | Path,
    explicit_path: str | Path = "",
    search_dir: str | Path = "",
) -> Optional[Path]:
    """Resolve and validate an explicit or episode-matched Japanese subtitle."""
    if explicit_path:
        path = Path(explicit_path).resolve()
        load_japanese_subtitle(path)
        return path
    if search_dir:
        return find_japanese_sidecar(video_path, search_dir)
    return None


def extract_embedded_japanese(video_path: str, output_dir: str) -> Optional[Path]:
    """Extract and validate a Japanese text track, returning None when unavailable."""
    track = select_japanese_track(get_subtitle_tracks(video_path))
    if track is None:
        return None
    output = Path(output_dir) / f"{Path(video_path).stem}.embedded.ja.srt"
    if not extract_subtitle(video_path, int(track["index"]), str(output)):
        return None
    try:
        load_japanese_subtitle(output)
    except ValueError:
        output.unlink(missing_ok=True)
        return None
    return output.resolve()


def extract_best_subtitle(video_path: str, output_dir: str = "") -> Optional[dict]:
    """Find and extract the best subtitle track from a video.

    Returns dict with extracted subtitle info, or None if no subtitles found.
    """
    tracks = get_subtitle_tracks(video_path)
    if not tracks:
        return None

    # Sort by priority (highest first), then by index
    tracks.sort(key=lambda t: (-t["priority"], t["index"]))
    best = tracks[0]

    video_name = Path(video_path).stem
    out_dir = Path(output_dir) if output_dir else Path(video_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    ext = ".srt"
    output_path = str(out_dir / f"{video_name}.{best['language']}{ext}")

    result = extract_subtitle(video_path, best["index"], output_path)
    if result:
        lang_name = {"zh": "Chinese", "ja": "Japanese", "en": "English"}.get(
            best["language"], best["language"])
        return {
            "video": video_path,
            "track_index": best["index"],
            "language": best["language"],
            "language_name": lang_name,
            "output": output_path,
            "size_bytes": Path(output_path).stat().st_size,
        }
    return None


def check_subtitle_available(video_path: str) -> dict:
    """Check if video has usable subtitles. Returns decision info."""
    tracks = get_subtitle_tracks(video_path)
    if not tracks:
        return {"available": False, "reason": "no_subtitle_tracks",
                "tracks": [], "decision": "proceed_asr"}

    # Check for Chinese subtitles
    has_zh = any(t["priority"] >= 4 for t in tracks)
    has_ja = any(t["priority"] >= 3 for t in tracks)

    if has_zh:
        zh_track = [t for t in tracks if t["priority"] >= 4][0]
        return {
            "available": True, "reason": "chinese_found",
            "tracks": tracks, "decision": "use_zh",
            "best_track": zh_track,
        }
    elif has_ja:
        ja_track = [t for t in tracks if t["priority"] >= 3][0]
        return {
            "available": True, "reason": "japanese_found",
            "tracks": tracks, "decision": "use_ja_as_reference",
            "best_track": ja_track,
        }

    return {"available": False, "reason": "no_zh_or_ja",
            "tracks": tracks, "decision": "proceed_asr"}


# ============ Evaluate ============

def evaluate():
    print("\n============================================================")
    print("S13.3 EXTERNAL SUBTITLE EVALUATION")
    print("============================================================")

    # Check if we have test videos
    video_dir = project_root / "data" / "video"
    videos = sorted(video_dir.glob("*.mp4"))

    if not videos:
        print("No test videos found")
        return

    print(f"\nTest videos: {len(videos)}")
    for v in videos[:3]:
        print(f"  {v.name} ({v.stat().st_size / 1024 / 1024:.1f} MB)")

    # Test 1: Detect subtitle tracks
    print("\n--- Test 1: Detect subtitle tracks ---")
    for video in videos[:3]:
        tracks = get_subtitle_tracks(str(video))
        if tracks:
            print(f"  {video.name}: {len(tracks)} track(s)")
            for t in tracks:
                lang_name = {"zh": "Chinese", "ja": "Japanese",
                             "en": "English", "und": "Unknown"}.get(
                    t["language"], t["language"])
                print(f"    #{t['index']}: {lang_name} ({t['codec']})")
        else:
            print(f"  {video.name}: no subtitle tracks")

    # Test 2: Check subtitle availability
    print("\n--- Test 2: Check subtitle availability ---")
    for video in videos[:1]:
        info = check_subtitle_available(str(video))
        print(f"  {video.name}: available={info['available']}, "
              f"reason={info['reason']}, decision={info['decision']}")

    # Test 3: Extract subtitle (if available)
    print("\n--- Test 3: Extract subtitle (if available) ---")
    for video in videos[:1]:
        info = check_subtitle_available(str(video))
        if info["available"]:
            result = extract_best_subtitle(str(video))
            if result:
                print(f"  Extracted: {result['language_name']} -> {result['output']}")
                print(f"  Size: {result['size_bytes']} bytes")
            else:
                print(f"  Extraction failed")
        else:
            print(f"  No subtitles to extract (expected for K-On!)")

    # Test 4: No subtitles = proceed with ASR
    print("\n--- Test 4: No subtitles -> proceed ASR ---")
    info = {"available": False, "reason": "no_subtitle_tracks",
            "decision": "proceed_asr"}
    print(f"  Decision: {info['decision']} (correct for K-On! episodes)")

    print("\n============================================================")
    print("EVALUATION COMPLETE")
    print("============================================================")


# ============ CLI ============

def main():
    parser = argparse.ArgumentParser(description="S13.3 External Subtitle Extraction")
    parser.add_argument("--video", type=str, help="Video file path")
    parser.add_argument("--output", type=str, default="", help="Output subtitle file")
    parser.add_argument("--info", action="store_true", help="Show subtitle track info only")
    parser.add_argument("--batch", type=str, nargs="+", help="Batch process multiple videos")
    parser.add_argument("--output-dir", type=str, default="", help="Output directory")
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()

    if args.evaluate:
        evaluate()
        return

    if args.info and args.video:
        tracks = get_subtitle_tracks(args.video)
        if tracks:
            print(f"Subtitle tracks in {Path(args.video).name}:")
            for t in tracks:
                print(f"  #{t['index']}: lang={t['language']}, codec={t['codec']}")
        else:
            print("No subtitle tracks found")
        return

    if args.video:
        if args.output:
            # Extract specific track
            tracks = get_subtitle_tracks(args.video)
            if tracks:
                extract_subtitle(args.video, tracks[0]["index"], args.output)
                print(f"Extracted: {args.output}")
        else:
            # Extract best track
            result = extract_best_subtitle(args.video, args.output_dir)
            if result:
                lang_name = result["language_name"]
                print(f"Extracted [{lang_name}]: {result['output']}")
            else:
                print("No subtitles found or extraction failed")
        return

    if args.batch:
        for video in args.batch:
            result = extract_best_subtitle(video, args.output_dir)
            if result:
                print(f"OK: {Path(video).name} -> {result['language_name']}")
            else:
                print(f"--: {Path(video).name} (no subtitles)")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
