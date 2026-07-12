"""S5.1: Demucs audio separation test"""
import sys, os, time, subprocess, json, re
from pathlib import Path

import numpy as np
from jiwer import cer
from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parent.parent
TEST_DIR = ROOT / "data" / "test"
MANIFEST = TEST_DIR / "manifest.json"
TMP_DIR = ROOT / ".omo" / "tmp"
OUT_DIR = ROOT / "docs" / "evaluation"
MODEL_PATH = ROOT / ".omo" / "anime-whisper-ct2"
TMP_DIR.mkdir(parents=True, exist_ok=True)


def normalize(t):
    return re.sub(r'\s+', '', t).strip()


def load_ref():
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    refs = {}
    for item in manifest:
        refs[item["audio_file"]] = item["transcription"]
    return refs


def transcribe(model, audio_path):
    segments, info = model.transcribe(audio_path, language="ja", beam_size=5, vad_filter=False)
    return " ".join([s.text.strip() for s in segments])


def separate_demucs(audio_path):
    """Run Demucs separation, return path to vocals file"""
    stem = Path(audio_path).stem
    out_dir = TMP_DIR / "htdemucs" / stem
    vocals_path = out_dir / "vocals.wav"
    if vocals_path.exists():
        return str(vocals_path)

    import demucs.separate
    demucs.separate.main(["--two-stems", "vocals", "-o", str(TMP_DIR), audio_path])
    return str(vocals_path) if vocals_path.exists() else None


def main():
    refs = load_ref()

    print("Loading ASR model...")
    model = WhisperModel(str(MODEL_PATH), device="cuda", compute_type="int8_float16")

    # Test on mixed clips (some have BGM, some pure speech)
    test_files = [
        "sample_0000.wav",  # normal dialogue with BGM
        "sample_0003.wav",  # crying
        "sample_0004.wav",  # normal
        "sample_0104.wav",  # dialogue
        "sample_0181.wav",  # dialogue
    ]

    results = []
    for fname in test_files:
        src = TEST_DIR / fname
        if not src.exists():
            continue
        ref = refs.get(fname, "")
        print(f"\n=== {fname} ===")
        print(f"  Ref: {ref}")

        # Original
        t0 = time.time()
        orig_text = transcribe(model, str(src))
        orig_time = time.time() - t0
        orig_cer = cer(normalize(ref), normalize(orig_text))
        print(f"  Orig: {orig_text}")
        print(f"  CER={orig_cer:.4f} t={orig_time:.2f}s")

        # Separate
        t0 = time.time()
        try:
            vocals_path = separate_demucs(str(src))
            sep_time = time.time() - t0
        except Exception as e:
            print(f"  Demucs failed: {e}")
            continue

        if not vocals_path:
            print("  No vocals output")
            continue

        print(f"  Separation: {sep_time:.1f}s")

        # Vocals only
        t0 = time.time()
        voc_text = transcribe(model, vocals_path)
        voc_time = time.time() - t0
        voc_cer = cer(normalize(ref), normalize(voc_text))
        print(f"  Vocals: {voc_text}")
        print(f"  CER={voc_cer:.4f} t={voc_time:.2f}s")
        print(f"  CER change: {voc_cer - orig_cer:+.4f}")

        results.append({
            "file": fname,
            "ref": ref,
            "orig_text": orig_text,
            "orig_cer": round(orig_cer, 4),
            "orig_time": round(orig_time, 2),
            "vocals_text": voc_text,
            "vocals_cer": round(voc_cer, 4),
            "vocals_time": round(voc_time, 2),
            "sep_time": round(sep_time, 1),
            "cer_change": round(voc_cer - orig_cer, 4),
        })

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"{'File':<20} {'Orig CER':<10} {'Voc CER':<10} {'Change':<10} {'Sep Time':<10}")
    print("-" * 60)
    for r in results:
        print(f"{r['file']:<20} {r['orig_cer']:<10.4f} {r['vocals_cer']:<10.4f} {r['cer_change']:<+10.4f} {r['sep_time']:<10.1f}")

    # Save results
    out_path = OUT_DIR / "S5.1_results_demucs.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()