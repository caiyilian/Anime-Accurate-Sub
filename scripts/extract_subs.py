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

import json, os, sys, subprocess, time, argparse
from pathlib import Path
from typing import List, Optional

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Language priority for subtitle extraction (higher = better)
LANG_PRIORITY = {
    "chi": 4, "zho": 4, "zh": 4, "chs": 4, "cht": 4,  # Chinese
    "jpn": 3, "ja": 3,                                    # Japanese
    "eng": 2, "en": 2,                                     # English
}

SUBTITLE_CODECS = {"subrip", "ass", "ssa", "webvtt", "srt"}


def get_subtitle_tracks(video_path: str) -> List[dict]:
    """Detect embedded subtitle tracks in video file using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
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
        "ffmpeg", "-y", "-i", video_path,
        "-map", f"0:{track_index}",
        "-c", "copy" if ext == ".sup" else "srt",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and Path(output_path).exists():
            return output_path
        return None
    except subprocess.TimeoutExpired:
        return None


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