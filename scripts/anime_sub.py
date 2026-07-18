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

# ffmpeg path - prefer libass-enabled version
FFMPEG_PATH = "ffmpeg"
LIBAASS_FFMPEG = project_root / ".omo" / "ffmpeg-libass" / "ffmpeg-2026-05-28-git-7b46c6a2a3-full_build" / "bin" / "ffmpeg.exe"
if LIBAASS_FFMPEG.exists():
    FFMPEG_PATH = str(LIBAASS_FFMPEG)
    print(f"Using libass ffmpeg: {FFMPEG_PATH}", file=sys.stderr)

from scripts.checkpoint import Checkpoint
from scripts.asr_engine import ASRSettings, AnimeWhisperASR
from scripts.translator_adapter import (
    TranslatorAdapter,
    _ensure_builtin_translator_plugins,
    load_config,
)
from scripts.plugin_system import load_plugins, plugin_registry
from scripts.translation_engine import PipelineTranslator
from scripts.translation_memory import TranslationMemory
from scripts.glossary import Glossary
from scripts.oped_detector import (
    detect_oped,
    filter_segments as filter_oped_segments,
    parse_explicit_ranges,
)
from scripts.series_memory import SeriesMemory
from scripts.subtitle_gen import (
    STYLES,
    _ensure_builtin_style_plugins,
    generate as generate_subtitles,
)
from scripts.quality_check import (
    generate_report as run_quality_check,
    segments_from_dicts as quality_segments_from_dicts,
)
from scripts.review_agents import ReviewConfig, review_translation_file

PIPELINE_STAGES = ["extract_audio", "asr", "translate", "subtitle", "embed_subtitle", "quality_check"]
MULTI_AGENT_STAGE = "multi_agent_review"
_ASR_ENGINES = {}


def _create_anime_whisper(config: dict):
    asr_config = dict(config.get("asr", {}))
    settings_config = asr_config.pop("settings", {})
    settings = ASRSettings(**settings_config) if settings_config else None
    allowed = {"model_path", "device", "compute_type"}
    options = {key: value for key, value in asr_config.items() if key in allowed}
    return AnimeWhisperASR(settings=settings, **options)


def _ensure_builtin_pipeline_plugins() -> None:
    _ensure_builtin_translator_plugins()
    _ensure_builtin_style_plugins()
    plugin_registry.register_if_missing(
        "asr",
        "anime_whisper",
        _create_anime_whisper,
        source="builtin:anime_sub",
        description="Anime Whisper CT2 long-form ASR",
    )


def extract_audio(video_path: str, output_dir: str) -> str:
    """Extract audio from video using ffmpeg."""
    video_name = Path(video_path).stem
    audio_path = Path(output_dir) / f"{video_name}.wav"

    if audio_path.exists():
        print(f"  Audio already extracted: {audio_path}")
        return str(audio_path)

    print(f"  Extracting audio...")
    cmd = [
        FFMPEG_PATH, "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(audio_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    print(f"  Audio saved: {audio_path.name}")
    return str(audio_path)


def embed_subtitle(video_path: str, subtitle_path: str, output_path: str) -> str:
    """Burn subtitles into video using libass (relative path to avoid colon issue)."""
    out = Path(output_path)
    if out.exists():
        print(f"  Video with subs already exists: {out.name}")
        return str(out)

    import shutil
    out_dir = out.parent
    sub_name = Path(subtitle_path).name
    vid_name = Path(video_path).name

    # Copy files to output dir (skip if already there)
    for src, dst in [(video_path, out_dir / vid_name), (subtitle_path, out_dir / sub_name)]:
        if not dst.exists():
            try:
                shutil.copy2(src, dst)
            except PermissionError:
                print(f"  Warning: couldn't copy {Path(src).name}, file may be in use")

    print(f"  Burning subtitles into video (libass)...")
    cmd = [FFMPEG_PATH, "-y", "-i", vid_name, "-vf", f"ass={sub_name}", "-c:a", "copy", "-preset", "fast", "-crf", "22", out.name]
    subprocess.run(cmd, capture_output=True, check=True, cwd=str(out_dir))
    print(f"  Video saved: {out.name}")
    return str(out)


def run_asr(
    audio_path: str,
    output_dir: str,
    backend: str = "anime_whisper",
    config: dict | None = None,
) -> list:
    """Run reliable long-form ASR with a model reused across batch items."""
    _ensure_builtin_pipeline_plugins()
    config = config or {}
    cache_key = (backend, json.dumps(config, sort_keys=True, default=str))
    if cache_key not in _ASR_ENGINES:
        _ASR_ENGINES[cache_key] = plugin_registry.create("asr", backend, config)
    engine = _ASR_ENGINES[cache_key]
    print(f"  Running ASR on {Path(audio_path).name}...")
    if getattr(engine, "model_path", None):
        print(f"  Model: {engine.model_path}")
    result = engine.transcribe(audio_path)
    print(f"  Recognized {len(result)} segments")
    return result


def translate_segments(segments: list, adapter: TranslatorAdapter,
                        series_memory: SeriesMemory = None,
                        glossary: Glossary = None,
                        translation_memory: TranslationMemory = None,
                        batch_size: int = None,
                        progress_path: str = "") -> list:
    """Translate ASR segments in validated, resumable batches."""
    print(f"  Translating {len(segments)} segments...")
    if series_memory:
        adapter.series_info = series_memory.to_prompt_block()
    engine = PipelineTranslator(
        adapter,
        glossary=glossary,
        memory=translation_memory,
        batch_size=batch_size,
    )
    return engine.translate(segments, progress_path=progress_path or None)


def process_video(video_path: str, output_dir: str, config: dict,
                   backend: str = "sakura", memory_path: str = "",
                   quality_check: bool = False, glossary_path: str = "",
                   translation_memory_path: str = "",
                   translation_batch_size: int = 0,
                   oped_series: str = "", episode_number: int = 0,
                   oped_ranges: list[str] = None,
                   oped_strict: bool = True,
                   speaker_map_path: str = "",
                   asr_backend: str = "anime_whisper",
                   subtitle_style: str = "anime",
                   multi_agent_review: bool = False,
                   review_config: dict = None) -> dict:
    """Process a single video through the full pipeline."""
    video_name = Path(video_path).stem
    work_dir = Path(output_dir) / video_name
    work_dir.mkdir(parents=True, exist_ok=True)

    active_stages = PIPELINE_STAGES[:-1]
    if multi_agent_review:
        active_stages.insert(active_stages.index("subtitle"), MULTI_AGENT_STAGE)
    if quality_check:
        active_stages.append("quality_check")
    cp = Checkpoint(str(work_dir), stages=active_stages)
    result = {"video": video_name, "path": video_path, "status": "ok"}

    # Enabling review on an existing work directory must regenerate every
    # downstream artifact from reviewed.json rather than silently keeping the
    # pre-review subtitle/video checkpoints.
    if multi_agent_review and not cp.is_completed(MULTI_AGENT_STAGE):
        for downstream in ("subtitle", "embed_subtitle", "quality_check"):
            if cp.is_completed(downstream):
                cp.reset(downstream)

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
        if not audio_path:
            existing_audio = work_dir / f"{video_name}.wav"
            if not existing_audio.exists():
                raise FileNotFoundError(
                    f"ASR audio is missing after extract_audio checkpoint: {existing_audio}"
                )
            audio_path = str(existing_audio)

        ranges = []
        if oped_ranges:
            ranges = parse_explicit_ranges(oped_ranges)
        elif oped_series:
            print(f"  Detecting OP/ED for series: {oped_series}")
            try:
                ranges = detect_oped(
                    video_path,
                    oped_series,
                    episode=episode_number or None,
                )
            except Exception as error:
                if oped_strict:
                    raise
                print(f"  Warning: OP/ED detection failed; continuing without filter: {error}")

        if ranges:
            range_path = work_dir / "oped_ranges.json"
            with open(range_path, "w", encoding="utf-8") as file:
                json.dump([item.to_dict() for item in ranges], file, ensure_ascii=False, indent=2)
            for item in ranges:
                print(
                    f"  {item.kind}: {item.start:.3f}s -> {item.end:.3f}s "
                    f"(score={item.score:.3f}, source={item.source})"
                )

        asr_segments = run_asr(
            audio_path, str(work_dir), backend=asr_backend, config=config
        )
        if ranges:
            asr_segments, removed_segments = filter_oped_segments(asr_segments, ranges)
            removed_path = work_dir / "oped_removed_segments.json"
            with open(removed_path, "w", encoding="utf-8") as file:
                json.dump(removed_segments, file, ensure_ascii=False, indent=2)
            print(
                f"  OP/ED filter removed {len(removed_segments)} segments; "
                f"{len(asr_segments)} dialogue segments remain"
            )
            result["oped_removed_segments"] = len(removed_segments)
        cp.mark_completed("asr", duration_s=time.time()-t0)
        # Save ASR results for later stages
        asr_path = work_dir / "asr_results.json"
        with open(asr_path, "w", encoding="utf-8") as f:
            json.dump(asr_segments, f, ensure_ascii=False, indent=2)
    else:
        # Load ASR results from file if ASR was already completed
        asr_path = work_dir / "asr_results.json"
        if asr_path.exists():
            with open(asr_path, encoding="utf-8") as f:
                asr_segments = json.load(f)

    # Stage 3: Translate
    if "translate" in cp.get_pending_stages():
        print("[translate]")
        t0 = time.time()
        cfg = dict(config)
        cfg["backend"] = backend
        adapter = TranslatorAdapter.from_config(cfg)
        series_mem = SeriesMemory(memory_path) if memory_path and Path(memory_path).exists() else None
        glossary = Glossary(glossary_path) if glossary_path and Path(glossary_path).exists() else None
        tm_path = Path(translation_memory_path) if translation_memory_path else work_dir / "translation_memory.jsonl"
        translation_memory = TranslationMemory(str(tm_path), auto_save=False)
        if series_mem:
            print(f"  Using series memory: {memory_path}")
        if glossary:
            print(f"  Using glossary: {glossary_path} ({glossary.count()} terms)")
        if asr_segments:
            # Save translated segments
            seg_path = work_dir / "translated.json"
            translate_segments(
                asr_segments,
                adapter,
                series_mem,
                glossary=glossary,
                translation_memory=translation_memory,
                batch_size=translation_batch_size or None,
                progress_path=str(seg_path),
            )
            cp.mark_completed("translate", output_file=str(seg_path),
                              duration_s=time.time()-t0)

    # Stage 3b: Five reviewers + conservative editor
    if multi_agent_review and MULTI_AGENT_STAGE in cp.get_pending_stages():
        print(f"[{MULTI_AGENT_STAGE}]")
        t0 = time.time()
        translated_path = work_dir / "translated.json"
        if not translated_path.exists():
            raise FileNotFoundError(
                f"Translated segments are missing for multi-agent review: {translated_path}"
            )
        reviewed_path = work_dir / "reviewed.json"
        review_report_path = work_dir / "multi_agent_review.json"
        review_progress_path = work_dir / "multi_agent_review.progress.jsonl"
        review_result = review_translation_file(
            str(translated_path),
            str(reviewed_path),
            str(review_report_path),
            progress_path=str(review_progress_path),
            glossary_path=glossary_path,
            config=ReviewConfig.from_dict(review_config).validate(),
            apply_fixes=True,
        )
        result["multi_agent_review"] = review_result["summary"]
        cp.mark_completed(
            MULTI_AGENT_STAGE,
            input_file=str(translated_path),
            output_file=str(reviewed_path),
            duration_s=time.time() - t0,
        )

    # Stage 4: Generate subtitles
    if "subtitle" in cp.get_pending_stages():
        print("[subtitle]")
        t0 = time.time()
        seg_path = work_dir / ("reviewed.json" if multi_agent_review else "translated.json")
        if seg_path.exists():
            srt_path = work_dir / f"{video_name}.srt"
            ass_path = work_dir / f"{video_name}.ass"
            generate_subtitles(
                str(seg_path), str(srt_path), speaker_map=speaker_map_path or None
            )
            generate_subtitles(
                str(seg_path),
                str(ass_path),
                style=subtitle_style,
                speaker_map=speaker_map_path or None,
            )
            cp.mark_completed("subtitle", output_file=str(srt_path),
                              duration_s=time.time()-t0)

    # Stage 5: Embed subtitles into video
    if "embed_subtitle" in cp.get_pending_stages():
        print("[embed_subtitle]")
        t0 = time.time()
        srt_path = work_dir / f"{video_name}.srt"
        ass_path = work_dir / f"{video_name}.ass"
        output_video = work_dir / f"{video_name}_subs.mp4"
        ass_path = work_dir / f"{video_name}.ass"
        if ass_path.exists():
            embed_subtitle(video_path, str(ass_path), str(output_video))
            cp.mark_completed("embed_subtitle", input_file=video_path,
                              output_file=str(output_video), duration_s=time.time()-t0)

    # Stage 6: Quality check
    if quality_check and "quality_check" in cp.get_pending_stages():
        print("[quality_check]")
        t0 = time.time()
        seg_path = work_dir / ("reviewed.json" if multi_agent_review else "translated.json")
        if not seg_path.exists():
            raise FileNotFoundError(
                f"Translated segments are missing for quality check: {seg_path}"
            )
        with open(seg_path, encoding="utf-8") as file:
            translated_items = json.load(file)
        report_path = work_dir / "quality_report.json"
        report = run_quality_check(
            quality_segments_from_dicts(translated_items),
            [],
            str(report_path),
            glossary_path or None,
        )
        result["quality_stats"] = report["stats"]
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
                        help="Translation backend or translator plugin name")
    parser.add_argument("--asr-backend", type=str, default="anime_whisper",
                        help="ASR backend or asr plugin name")
    parser.add_argument("--subtitle-style", type=str, default="anime",
                        help="ASS style or subtitle_style plugin name")
    parser.add_argument("--plugin", action="append", default=[],
                        help="Trusted local plugin .py file (repeatable)")
    parser.add_argument("--list-plugins", action="store_true",
                        help="List built-in, local and installed plugins")
    parser.add_argument("--config", type=str, default="", help="Translator config file")
    parser.add_argument("--memory", type=str, default="", help="Series memory JSON file")
    parser.add_argument("--glossary", type=str, default="", help="Japanese-Chinese glossary JSON")
    parser.add_argument("--translation-memory", type=str, default="",
                        help="Shared translation memory JSONL (defaults to the episode work directory)")
    parser.add_argument("--translation-batch-size", type=int, default=0,
                        help="Lines per translation request (default: backend configuration)")
    parser.add_argument("--oped-series", type=str, default="",
                        help="AnimeThemes series name used for automatic OP/ED detection")
    parser.add_argument("--episode-number", type=int, default=0,
                        help="Episode number for selecting the correct theme version")
    parser.add_argument("--oped-range", action="append", default=[],
                        help="Explicit offline range, e.g. op:115.1-204.9 (repeatable)")
    parser.add_argument("--oped-best-effort", action="store_true",
                        help="Continue without OP/ED filtering if automatic detection fails")
    parser.add_argument("--quality-check", action="store_true", help="Enable quality checks")
    parser.add_argument(
        "--multi-agent-review", action="store_true",
        help="Run five structured reviewers and a conservative editor before subtitles",
    )
    parser.add_argument("--review-config", type=str, default="",
                        help="JSON configuration for multi-agent review")
    parser.add_argument("--review-host", type=str, default="")
    parser.add_argument("--review-model", type=str, default="")
    parser.add_argument("--editor-host", type=str, default="")
    parser.add_argument("--editor-model", type=str, default="")
    parser.add_argument("--review-workers", type=int, default=0)
    parser.add_argument("--review-min-votes", type=int, default=0)
    parser.add_argument("--review-min-confidence", type=float, default=-1.0)
    parser.add_argument("--review-context-window", type=int, default=-1)
    parser.add_argument("--speaker-map", type=str, default="",
                        help="JSON mapping from speaker IDs to ASS character names/colors")
    parser.add_argument("--auto", action="store_true", help="Auto-detect hardware and set optimal params")
    parser.add_argument("--batch", type=str, nargs="+", help="Batch process multiple videos")
    parser.add_argument("--test", action="store_true", help="Run pipeline test")
    parser.add_argument("--version", action="store_true", help="Show version info")
    args = parser.parse_args()

    load_plugins(args.plugin)
    _ensure_builtin_pipeline_plugins()

    if args.list_plugins:
        for spec in plugin_registry.specs():
            print(
                f"{spec['kind']:<15} {spec['name']:<20} "
                f"{spec['description']} [{spec['source']}]"
            )
        return

    if args.version:
        print("Anime Accurate Sub v1.0.0")
        print("Pipeline stages: extract_audio -> asr -> translate -> subtitle -> quality_check")
        return

    if args.test:
        test_run()
        return

    config = load_config(args.config)
    review_config = {}
    if args.review_config:
        review_config = json.loads(Path(args.review_config).read_text(encoding="utf-8"))
    review_overrides = {
        "host": args.review_host or None,
        "review_model": args.review_model or None,
        "editor_host": args.editor_host or None,
        "editor_model": args.editor_model or None,
        "max_workers": args.review_workers or None,
        "min_fix_votes": args.review_min_votes or None,
        "min_editor_confidence": (
            args.review_min_confidence if args.review_min_confidence >= 0 else None
        ),
        "context_window": (
            args.review_context_window if args.review_context_window >= 0 else None
        ),
    }
    review_config.update(
        {key: value for key, value in review_overrides.items() if value is not None}
    )

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
            quality_check=args.quality_check, glossary_path=args.glossary,
            translation_memory_path=args.translation_memory,
            translation_batch_size=args.translation_batch_size,
            oped_series=args.oped_series, episode_number=args.episode_number,
            oped_ranges=args.oped_range,
            oped_strict=not args.oped_best_effort,
            speaker_map_path=args.speaker_map,
            asr_backend=args.asr_backend,
            subtitle_style=args.subtitle_style,
            multi_agent_review=args.multi_agent_review,
            review_config=review_config,
        )
        return

    if args.batch:
        video_files = []
        for pattern in args.batch:
            # Check if pattern is a batch.txt file with paths
            if pattern.endswith(".txt") and Path(pattern).exists():
                with open(pattern, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and Path(line).exists():
                            video_files.append(line)
            else:
                import glob as glob_mod
                video_files.extend(glob_mod.glob(pattern))
        if not video_files:
            print(f"No video files matched the patterns")
            return
        for video in video_files:
            process_video(video, args.output_dir, config,
                          backend=args.backend, memory_path=args.memory,
                          quality_check=args.quality_check, glossary_path=args.glossary,
                          translation_memory_path=args.translation_memory,
                          translation_batch_size=args.translation_batch_size,
                          oped_series=args.oped_series,
                          episode_number=args.episode_number,
                          oped_ranges=args.oped_range,
                          oped_strict=not args.oped_best_effort,
                          speaker_map_path=args.speaker_map,
                          asr_backend=args.asr_backend,
                          subtitle_style=args.subtitle_style,
                          multi_agent_review=args.multi_agent_review,
                          review_config=review_config)

        return

    parser.print_help()


if __name__ == "__main__":
    main()
