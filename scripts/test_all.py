#!/usr/bin/env python3
# S15.3: End-to-end regression test suite
#
# Tests all modules in the pipeline:
#   S3:  ASR (eval_asr)
#   S6:  Diarization (eval_diarization)
#   S9:  Translate + Glossary + TM (translate, glossary, translation_memory)
#   S10: Subtitle generation (subtitle_gen)
#   S11: Quality check + Review + MQM (quality_check, review_agents, gemba_mqm)
#   S12: Checkpoint + Batch (checkpoint, batch_process)
#   S13: Term discovery + AB eval + Extract subs (discover_terms, ab_eval, extract_subs)
#   S14: Translator adapter + Series memory (translator_adapter, series_memory)
#   S15: Pipeline CLI (anime_sub, hardware)
#   S16: Speaker styles + Web UI + proofreading + plugins + video preview
#
# Usage:
#   python scripts/test_all.py
#   python scripts/test_all.py --verbose
#   python scripts/test_all.py --module subtitle_gen

import sys, time, json, importlib, traceback
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

PASS = 0
FAIL = 0
SKIP = 0
RESULTS = []


def test(name: str, func, *args, **kwargs):
    """Run a single test and record result."""
    global PASS, FAIL
    t0 = time.time()
    try:
        func(*args, **kwargs)
        elapsed = time.time() - t0
        RESULTS.append((name, "PASS", elapsed, ""))
        PASS += 1
        print(f"  [PASS] {name} ({elapsed:.2f}s)")
    except Exception as e:
        elapsed = time.time() - t0
        tb = traceback.format_exc().split("\n")[-3] if not kwargs.get("verbose") else traceback.format_exc()
        RESULTS.append((name, "FAIL", elapsed, str(e)))
        FAIL += 1
        print(f"  [FAIL] {name} ({elapsed:.2f}s): {e}")


def skip(name: str, reason: str):
    global SKIP
    SKIP += 1
    RESULTS.append((name, "SKIP", 0, reason))
    print(f"  [SKIP] {name}: {reason}")


# ============ S3: ASR ============

def test_asr():
    """Test ASR evaluation script imports."""
    import scripts.eval_asr
    assert hasattr(scripts.eval_asr, "normalize_text")
    assert hasattr(scripts.eval_asr, "load_gold_standard")


# ============ S9: Translation ============

def test_translate():
    """Test translation module imports and basic function."""
    from scripts.translate import translate
    # Just test the function exists
    assert callable(translate)


def test_glossary():
    """Test glossary module."""
    from scripts.glossary import Glossary
    g = Glossary()
    g.add("test", "测试")
    assert g.get("test") == "测试"
    assert g.count() == 1
    assert "测试" in g.to_prompt_block()


def test_translation_memory():
    """Test translation memory module."""
    import tempfile, os
    from scripts.translation_memory import TranslationMemory
    tm = TranslationMemory()
    assert tm.count() == 0
    tm.store("hello", "你好")
    assert tm.lookup("hello") == "你好"
    assert tm.stats()["stored"] == 1


# ============ S10: Subtitle ============

def test_subtitle_gen():
    """Test subtitle generation module."""
    from scripts.subtitle_gen import generate, STYLES, create_test_segments, optimize_timeline
    assert len(STYLES) >= 3  # At least 3 styles
    segs = create_test_segments()
    assert len(segs) >= 5
    opt = optimize_timeline(segs)
    # Check no overlaps
    for i in range(1, len(opt)):
        assert opt[i].start >= opt[i-1].end - 0.01, f"Overlap at {i}"


# ============ S11: Quality ============

def test_quality_check():
    """Test quality check module."""
    from scripts.quality_check import generate_report
    from scripts.quality_check import SubSegment, check_cps, check_empty
    segs = [SubSegment(start=0, end=2, text="hello", index=0)]
    issues = check_empty(segs)
    assert len(issues) == 0  # Not empty
    segs2 = [SubSegment(start=0, end=2, text="", index=0)]
    issues2 = check_empty(segs2)
    assert len(issues2) == 1  # Empty -> error


def test_review_agents():
    """Test strict review parsing and production configuration."""
    from scripts.review_agents import AGENTS, ReviewConfig, parse_agent_response
    assert len(AGENTS) == 5  # 5 agents
    config = ReviewConfig.from_dict({
        "provider": "openai",
        "base_url": "https://example.invalid/v1",
        "api_key_file": "keys.txt",
        "min_fix_votes": 2,
        "min_reviewer_confidence": 0.75,
        "min_editor_confidence": 0.85,
    }).validate()
    assert config.min_fix_votes == 2
    parsed = parse_agent_response(
        '{"verdict":"ok","suggested_zh":"","reason":"自然",'
        '"confidence":0.9}'
    )
    assert parsed["verdict"] == "ok"
    try:
        parse_agent_response("提示词写着 [OK]，但这不是 JSON 结论")
    except ValueError:
        pass
    else:
        raise AssertionError("natural-language keyword guessing must be rejected")


def test_gemba_mqm():
    """Test strict dual-judge MQM production module."""
    from scripts.mqm_quality_review import (
        MQMConfig,
        MQM_DIMENSIONS,
        parse_judge_response,
    )
    assert len(MQM_DIMENSIONS) == 4  # 4 dimensions
    config = MQMConfig(provider="ollama", judge_models=["judge-a", "judge-b"])
    assert len(config.validate().judge_models) == 2
    parsed = parse_judge_response(json.dumps({
        "dimensions": {
            name: {"score": 90, "severity": "none", "reason": "正确"}
            for name in MQM_DIMENSIONS
        },
        "errors": [],
        "recommendation": "keep",
        "suggested_zh": "",
        "confidence": 0.9,
    }, ensure_ascii=False))
    assert parsed["overall"] == 90
    try:
        parse_judge_response("评分: 90")
    except ValueError:
        pass
    else:
        raise AssertionError("MQM keyword score guessing must be rejected")


# ============ S12: Infrastructure ============

def test_checkpoint():
    """Test checkpoint module."""
    import tempfile, shutil
    tmp = Path(tempfile.mkdtemp())
    from scripts.checkpoint import Checkpoint
    cp = Checkpoint(str(tmp))
    assert len(cp.get_pending_stages()) == 6
    cp.mark_completed("asr", duration_s=10.0)
    assert cp.is_completed("asr")
    assert not cp.is_completed("translate")
    # Resume test
    cp2 = Checkpoint(str(tmp))
    assert cp2.is_completed("asr")
    shutil.rmtree(tmp)


def test_batch_process():
    """Test batch processing module imports."""
    from scripts.batch_process import BatchProcessor
    assert hasattr(BatchProcessor, "find_videos")
    assert hasattr(BatchProcessor, "process_all")


# ============ S13: Tools ============

def test_discover_terms():
    """Test term discovery module."""
    from scripts.discover_terms import extract_candidates, generate_glossary
    candidates = extract_candidates("テスト テスト 軽音部", min_freq=1, min_len=2)
    assert len(candidates) >= 2


def test_ab_eval():
    """Test AB evaluation module."""
    from scripts.ab_eval import compute_cer, evaluate_pair
    cer = compute_cer("hello world", "hello world")
    assert cer == 0.0
    cer2 = compute_cer("hello", "world")
    assert cer2 > 0


def test_extract_subs():
    """Test Japanese subtitle priority and ASR-compatible import."""
    import tempfile
    from scripts.extract_subs import get_subtitle_tracks, load_japanese_subtitle
    # Test with non-existent video
    tracks = get_subtitle_tracks("nonexistent.mp4")
    assert tracks == []
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "episode.jp.srt"
        source.write_text(
            "1\n00:00:01,000 --> 00:00:02,000\nおはよう\n", encoding="utf-8"
        )
        segments = load_japanese_subtitle(source)
        assert segments[0]["text"] == "おはよう"
        assert segments[0]["source"] == "external_japanese_subtitle"


# ============ S14: Translation Infrastructure ============

def test_translator_adapter():
    """Test translator adapter module."""
    from scripts.translator_adapter import TranslatorAdapter, load_config, DEFAULT_CONFIG
    config = load_config()
    assert "backend" in config
    assert "sakura" in config


def test_series_memory():
    """Test series memory module."""
    from scripts.series_memory import SeriesMemory, create_k_on_memory
    mem = create_k_on_memory()
    assert len(mem.data["characters"]) == 6
    assert len(mem.data["terms"]) == 10
    prompt = mem.inject_into_prompt("test")
    assert "平泽唯" in prompt
    assert "轻音部" in prompt


# ============ S15: CLI ============

def test_anime_sub():
    """Test anime_sub CLI module imports."""
    from scripts.anime_sub import process_video, PIPELINE_STAGES
    assert len(PIPELINE_STAGES) == 6


def test_hardware():
    """Test hardware detection module."""
    from scripts.hardware import HardwareDetector
    hw = HardwareDetector()
    info = hw.info
    assert "platform" in info
    assert "cpu" in info
    assert "gpu" in info
    rec = hw.recommend()
    assert "recommendations" in rec
    assert "translation" in rec["recommendations"]


# ============ S16: Advanced Features ============

def test_speaker_styles():
    """Test speaker role names and colors."""
    from scripts.subtitle_gen import load_speaker_map
    roles = load_speaker_map({"speaker_00": {"name": "唯", "color": "#FF80C0"}})
    assert roles["speaker_00"].name == "唯"
    assert roles["speaker_00"].color == "#FF80C0"


def test_web_ui():
    """Test the dependency-light Web UI helpers."""
    from scripts.web_ui import safe_upload_name, validate_job_options
    assert safe_upload_name("../episode.mp4") == "episode.mp4"
    assert validate_job_options({"backend": "sakura"})["backend"] == "sakura"


def test_proofreading():
    """Test proofreading schema is available to CLI and Web UI."""
    from scripts.proofread import SHEET_SCHEMA
    assert SHEET_SCHEMA == "anime-accurate-sub/proofread-v1"


def test_plugin_system():
    """Test plugin registration and style contract."""
    from scripts.plugin_system import PluginRegistry
    registry = PluginRegistry()
    registry.register("subtitle_style", "smoke_style", lambda config: {"fontname": "Arial"})
    assert registry.create("subtitle_style", "smoke_style", {})["fontname"] == "Arial"


def test_video_preview():
    """Test preview option validation without invoking ffmpeg."""
    from scripts.video_preview import PreviewOptions
    assert PreviewOptions(start=10, duration=5, width=960).validate().duration == 5


# ============ Test Registry ============

ALL_TESTS = [
    # S3
    ("S3.1  ASR evaluation module", test_asr),
    # S9
    ("S9.1  Translate module", test_translate),
    ("S9.2  Glossary module", test_glossary),
    ("S9.3  Translation memory module", test_translation_memory),
    # S10
    ("S10.1 Subtitle generation module", test_subtitle_gen),
    # S11
    ("S11.1 Quality check module", test_quality_check),
    ("S11.2 Review agents module", test_review_agents),
    ("S11.3 GEMBA-MQM module", test_gemba_mqm),
    # S12
    ("S12.1 Checkpoint module", test_checkpoint),
    ("S12.2 Batch process module", test_batch_process),
    # S13
    ("S13.1 Term discovery module", test_discover_terms),
    ("S13.2 AB evaluation module", test_ab_eval),
    ("S13.3 Extract subs module", test_extract_subs),
    # S14
    ("S14.1 Translator adapter module", test_translator_adapter),
    ("S14.2 Series memory module", test_series_memory),
    # S15
    ("S15.1 Pipeline CLI module", test_anime_sub),
    ("S15.2 Hardware detection module", test_hardware),
    # S16
    ("S16.1 Speaker role styles", test_speaker_styles),
    ("S16.2 FastAPI Web UI", test_web_ui),
    ("S16.3 Proofreading workflow", test_proofreading),
    ("S16.4 Plugin system", test_plugin_system),
    ("S16.5 Video preview", test_video_preview),
]


# ============ Main ============

def main():
    import argparse
    parser = argparse.ArgumentParser(description="S15.3 Regression Test Suite")
    parser.add_argument("--verbose", action="store_true", help="Show full traceback")
    parser.add_argument("--module", type=str, help="Run specific module (e.g., subtitle_gen)")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("S15.3 REGRESSION TEST SUITE")
    print("=" * 60)
    print(f"Testing {len(ALL_TESTS)} modules across S3-S16...\n")

    t0 = time.time()

    for name, func in ALL_TESTS:
        if args.module and args.module.lower() not in name.lower():
            skip(name, "filtered by --module")
            continue
        test(name, func)

    elapsed = time.time() - t0

    # Summary
    print(f"\n{'='*60}")
    print("RESULTS SUMMARY")
    print(f"{'='*60}")
    print(f"  PASS: {PASS}/{len(ALL_TESTS)}")
    print(f"  FAIL: {FAIL}/{len(ALL_TESTS)}")
    print(f"  SKIP: {SKIP}/{len(ALL_TESTS)}")
    print(f"  Time: {elapsed:.1f}s")

    # Detail
    print(f"\n{'='*60}")
    print("DETAIL")
    print(f"{'='*60}")
    for name, status, t, msg in RESULTS:
        icon = {"PASS": "OK", "FAIL": "FAIL", "SKIP": "--"}.get(status, "?")
        time_str = f"({t:.2f}s)" if status == "PASS" else ""
        print(f"  [{icon}] {name} {time_str}")
        if status == "FAIL" and msg:
            print(f"       {msg}")

    # Save results
    out_path = project_root / "docs" / "evaluation" / "S15.3_regression_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total": len(ALL_TESTS),
            "pass": PASS,
            "fail": FAIL,
            "skip": SKIP,
            "elapsed_s": round(elapsed, 1),
            "results": [{"name": n, "status": s, "time_s": round(t, 2), "error": m}
                       for n, s, t, m in RESULTS],
        }, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved: {out_path}")

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
