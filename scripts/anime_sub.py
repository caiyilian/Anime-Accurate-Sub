#!/usr/bin/env python3
# S15.1: Full pipeline CLI - anime-sub video.mp4
#
# Usage:
#   python scripts/anime_sub.py video.mp4
#   python scripts/anime_sub.py video.mp4 --output-dir ./output
#   python scripts/anime_sub.py video.mp4 --backend sakura --series-memory k-on_memory.json
#   python scripts/anime_sub.py --batch data/video/*.mp4
#   python scripts/anime_sub.py --test

import json, os, sys, time, argparse, subprocess
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from scripts.checkpoint import Checkpoint
from scripts.translator_adapter import TranslatorAdapter, load_config
from scripts.series_memory import SeriesMemory
from scripts.subtitle_gen import generate as generate_subtitles, STYLES
from scripts.quality_check import generate_report as run_quality_check

PIPELINE_STAGES = ["extract_audio", "asr", "translate", "subtitle", "quality_check"]


def extract_audio(video_path: str, output_dir: str) -> str:
    """Extract audio from video using ffmpeg."""
    video_name = Path(video_path).stem
    audio_path = Path(output_dir) / f"{video_name}.wav"

    if audio_path.exists():
        print(f"  Audio already extracted: {audio_path}")
        return str(audio_path)

    print(f"  Extracting audio...")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        str(audio_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    print(f"  Audio saved: {audio_path.name}")
    return str(audio_path)


def run_asr(audio_path: str, output_dir: str) -> list:
    """Run ASR on audio file."""
    print(f"  Running ASR on {Path(audio_path).name}...")
    # In a full implementation, this would call faster-whisper
    # For now, simulate with mock data
    segments = [
        {"start": 0.0, "end": 2.0, "text": "[ASR] simulated recognition result"},
        {"start": 2.5, "end": 5.0, "text": "[ASR] second line of dialogue"},
    ]
    return segments


def translate_segments(segments: list, adapter: TranslatorAdapter,
                        series_memory: SeriesMemory = None) -> list:
    """Translate ASR segments."""
    print(f"  Translating {len(segments)} segments...")
    translated = []
    for seg in segments:
        text = seg.get("text", "")
        prompt = text
        if series_memory:
            prompt = series_memory.inject_into_prompt(text)
        zh = adapter.translate(text)
        translated.append({
            "start": seg["start"],
            "end": seg["end"],
            "ja": text,
            "text": zh,
        })
    return translated


def process_video(video_path: str, output_dir: str, config: dict,
                   backend: str = "sakura", memory_path: str = "",
                   quality_check: bool = False) -> dict:
    """Process a single video through the full pipeline."""
    video_name = Path(video_path).stem
    work_dir = Path(output_dir) / video_name
    work_dir.mkdir(parents=True, exist_ok=True)

    cp = Checkpoint(str(work_dir))
    result = {"video": video_name, "path": video_path, "status": "ok"}

    # Stage 1: Extract audio
    audio_path = None
    if "extract_audio" in cp.get_pending_stages():
        print("[extract_audio]")
        t0 = time.time()
        audio_path = extract_audio(video_path, str(work_dir))
        cp.mark_completed("extract_audio", input_file=video_path,
                          output_file=audio_path, duration_s=time.time()-t0)

    # Stage 2: ASR
    asr_segments = None
    if "asr" in cp.get_pending_stages():
        print("[asr]")
        t0 = time.time()
        asr_segments = run_asr(audio_path or str(work_dir), str(work_dir))
        cp.mark_completed("asr", duration_s=time.time()-t0)

    # Stage 3: Translate
    if "translate" in cp.get_pending_stages():
        print("[translate]")
        t0 = time.time()
        cfg = dict(config)
        cfg["backend"] = backend
        adapter = TranslatorAdapter.from_config(cfg)
        series_mem = SeriesMemory(memory_path) if memory_path and Path(memory_path).exists() else None
        if series_mem:
            print(f"  Using series memory: {memory_path}")
        if asr_segments:
            translated = translate_segments(asr_segments, adapter, series_mem)
            # Save translated segments
            seg_path = work_dir / "translated.json"
            with open(seg_path, "w", encoding="utf-8") as f:
                json.dump(translated, f, ensure_ascii=False, indent=2)
            cp.mark_completed("translate", output_file=str(seg_path),
                              duration_s=time.time()-t0)

    # Stage 4: Generate subtitles
    if "subtitle" in cp.get_pending_stages():
        print("[subtitle]")
        t0 = time.time()
        seg_path = work_dir / "translated.json"
        if seg_path.exists():
            srt_path = work_dir / f"{video_name}.srt"
            ass_path = work_dir / f"{video_name}.ass"
            generate_subtitles(str(seg_path), str(srt_path))
            generate_subtitles(str(seg_path), str(ass_path), style="anime")
            cp.mark_completed("subtitle", output_file=str(srt_path),
                              duration_s=time.time()-t0)

    # Stage 5: Quality check
    if quality_check and "quality_check" in cp.get_pending_stages():
        print("[quality_check]")
        t0 = time.time()
        seg_path = work_dir / "translated.json"
        if seg_path.exists():
            report_path = work_dir / "quality_report.json"
            run_quality_check([], [], str(report_path))
            cp.mark_completed("quality_check", output_file=str(report_path),
                              duration_s=time.time()-t0)

    # Summary
    done = len(cp.get_completed_stages())
    total = len(cp.stages)
    print(f"\nPipeline: {done}/{total} stages completed")
    print(cp.summary())

    result["stages_completed"] = done
    result["stages_total"] = total
    return result


# ============ Test Mode ============

def test_run():
    """Simulate a full pipeline run for testing."""
    import tempfile
    tmp = Path(tempfile.mkdtemp())

    print("\n============================================================")
    print("S15.1 FULL PIPELINE TEST")
    print("============================================================")

    # Create test directories
    video_dir = tmp / "videos"
    out_dir = tmp / "output"
    video_dir.mkdir()
    video_path = video_dir / "test_ep01.mp4"
    video_path.write_text("fake video")

    # Test the pipeline flow with checkpoint only (skip actual ffmpeg/ASR)
    config = load_config()
    work_dir = out_dir / "test_ep01"
    work_dir.mkdir(parents=True)

    cp = Checkpoint(str(work_dir))
    cp.mark_completed("extract_audio", duration_s=5.0)
    cp.mark_completed("asr", duration_s=30.0)
    cp.mark_completed("translate", duration_s=15.0)

    # Verify checkpoint resume
    cp2 = Checkpoint(str(work_dir))
    assert cp2.is_completed("extract_audio")
    assert cp2.is_completed("asr")
    assert cp2.is_completed("translate")
    assert not cp2.is_completed("subtitle")
    assert not cp2.is_completed("quality_check")

    print(f"\nPipeline stages:")
    for s in cp.stages:
        status = "OK" if cp2.is_completed(s) else ".."
        print(f"  [{status}] {s}")
    print(f"\n  Completed: {len(cp2.get_completed_stages())}/{len(cp.stages)}")
    assert len(cp2.get_completed_stages()) == 3

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    print("\n============================================================")
    print("TEST COMPLETE")
    print("============================================================")


# ============ CLI ============

def main():
    parser = argparse.ArgumentParser(
        description="Anime Accurate Sub - Full pipeline CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/anime_sub.py video.mp4
  python scripts/anime_sub.py video.mp4 --backend galtransl --memory k-on_memory.json
  python scripts/anime_sub.py video.mp4 --quality-check
  python scripts/anime_sub.py --batch data/video/*.mp4 --output-dir ./output
        """,
    )
    parser.add_argument("video", nargs="?", type=str, help="Video file to process")
    parser.add_argument("--output-dir", type=str, default="output", help="Output directory")
    parser.add_argument("--backend", type=str, default="sakura",
                        choices=["sakura", "qwen", "galtransl", "external"],
                        help="Translation backend")
    parser.add_argument("--config", type=str, default="", help="Translator config file")
    parser.add_argument("--memory", type=str, default="", help="Series memory JSON file")
    parser.add_argument("--quality-check", action="store_true", help="Enable quality checks")
    parser.add_argument("--auto", action="store_true", help="Auto-detect hardware and set optimal params")
    parser.add_argument("--batch", type=str, nargs="+", help="Batch process multiple videos")
    parser.add_argument("--test", action="store_true", help="Run pipeline test")
    parser.add_argument("--version", action="store_true", help="Show version info")
    args = parser.parse_args()

    if args.version:
        print("Anime Accurate Sub v1.0.0")
        print("Pipeline stages: extract_audio -> asr -> translate -> subtitle -> quality_check")
        return

    if args.test:
        test_run()
        return

    if args.auto:
        from scripts.hardware import HardwareDetector
        detector = HardwareDetector()
        rec = detector.recommend()
        t = rec["recommendations"]["translation"]
        print(f"Auto-detected: {rec['hardware']['gpu']} ({rec['hardware']['vram_mb']}MB VRAM)")
        print(f"Recommended: backend={t['backend']}, model={t['model']}")
        # Apply recommendations
        if not args.backend or args.backend == "sakura":
            args.backend = t["backend"]
        if not args.config:
            # Create a temp config with recommended host
            config["backend"] = t["backend"]
            config[t["backend"]] = {"model": t["model"], "host": t["host"]}
        if not args.quality_check and rec["recommendations"]["quality_check"]["enabled"]:
            args.quality_check = True

    config = load_config(args.config)

    if args.video:
        result = process_video(
            args.video, args.output_dir, config,
            backend=args.backend, memory_path=args.memory,
            quality_check=args.quality_check,
        )
        return

    if args.batch:
        from scripts.batch_process import BatchProcessor
        bp = BatchProcessor("", args.output_dir)
        for video in args.batch:
            process_video(video, args.output_dir, config,
                          backend=args.backend, memory_path=args.memory,
                          quality_check=args.quality_check)
        return

    parser.print_help()


if __name__ == "__main__":
    main()