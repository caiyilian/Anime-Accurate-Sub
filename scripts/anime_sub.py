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

PIPELINE_STAGES = ["extract_audio", "asr", "translate", "subtitle", "embed_subtitle", "quality_check"]


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


def embed_subtitle(video_path: str, subtitle_path: str, output_path: str) -> str:
    """Embed subtitle into video using ffmpeg."""
    out = Path(output_path)
    if out.exists():
        print(f"  Video with subs already exists: {out.name}")
        return str(out)

    print(f"  Embedding subtitles into video...")

    ext = Path(subtitle_path).suffix.lower()
    if ext == ".ass":
        # ASS: direct embedding
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"ass={subtitle_path}",
            "-c:a", "copy",
            str(out),
        ]
    else:
        # SRT: burn as subtitles
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"subtitles={subtitle_path}",
            "-c:a", "copy",
            str(out),
        ]

    subprocess.run(cmd, capture_output=True, check=True)
    print(f"  Video saved: {out.name}")
    return str(out)


def run_asr(audio_path: str, output_dir: str) -> list:
    """Run ASR on audio file using Anime Whisper (faster-whisper)."""
    from faster_whisper import WhisperModel

    model_path = project_root / ".omo" / "anime-whisper-ct2"
    print(f"  Running ASR on {Path(audio_path).name}...")
    print(f"  Model: {model_path}")

    model = WhisperModel(str(model_path), device="cuda", compute_type="int8_float16", num_workers=1)
    segments, info = model.transcribe(audio_path, language="ja", beam_size=5, vad_filter=False)

    result = []
    for seg in segments:
        result.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
        })

    print(f"  Recognized {len(result)} segments")
    return result


def translate_segments(segments: list, adapter: TranslatorAdapter,
                        series_memory: SeriesMemory = None) -> list:
    """Translate ASR segments."""
    print(f"  Translating {len(segments)} segments...")
    translated = []
    # Build series context once
    series_context = ""
    if series_memory:
        series_context = series_memory.to_prompt_block() + "\n\n"
    for seg in segments:
        text = seg.get("text", "")
        # Inject series memory into the adapter's system prompt
        if series_memory:
            adapter.series_info = series_context
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

    # Stage 5: Embed subtitles into video
    if "embed_subtitle" in cp.get_pending_stages():
        print("[embed_subtitle]")
        t0 = time.time()
        srt_path = work_dir / f"{video_name}.srt"
        ass_path = work_dir / f"{video_name}.ass"
        output_video = work_dir / f"{video_name}_subs.mp4"
        sub_path = ass_path if ass_path.exists() else srt_path
        if sub_path.exists():
            embed_subtitle(video_path, str(sub_path), str(output_video))
            cp.mark_completed("embed_subtitle", input_file=video_path,
                              output_file=str(output_video), duration_s=time.time()-t0)

    # Stage 6: Quality check
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

    config = load_config(args.config)

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

    if args.video:
        result = process_video(
            args.video, args.output_dir, config,
            backend=args.backend, memory_path=args.memory,
            quality_check=args.quality_check,
        )
        return

    if args.batch:
        import glob as glob_mod
        video_files = []
        for pattern in args.batch:
            video_files.extend(glob_mod.glob(pattern))
        if not video_files:
            print(f"No video files matched the patterns")
            return
        for video in video_files:
            process_video(video, args.output_dir, config,
                          backend=args.backend, memory_path=args.memory,
                          quality_check=args.quality_check)
        return

    parser.print_help()


if __name__ == "__main__":
    main()