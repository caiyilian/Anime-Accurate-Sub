"""S5.2: UVR5 (audio-separator) evaluation"""
import sys, os, time, json, re
from pathlib import Path

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
        return {item["audio_file"]: item["transcription"] for item in json.load(f)}


def transcribe(model, audio_path):
    segments, info = model.transcribe(audio_path, language="ja", beam_size=5, vad_filter=False)
    return " ".join([s.text.strip() for s in segments])


def separate_uvr5(audio_path):
    """Run UVR5 separation using audio-separator, return path to vocals file"""
    stem = Path(audio_path).stem
    out_dir = TMP_DIR / "uvr5_output"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from audio_separator.separator import Separator
        separator = Separator(
            output_dir=str(out_dir),
            log_level=20,
            sample_rate=16000,
        )
        separator.load_model("UVR-MDX-NET-Inst_HQ_4.onnx")
        output_files = separator.separate(audio_path)
        # Find vocals file
        for f in output_files or []:
            if "vocals" in f.lower() or "Vocals" in f:
                result = os.path.join(str(out_dir), f)
                if os.path.exists(result):
                    return result
        # Fallback: try any output
        if output_files:
            for f in output_files:
                fp = os.path.join(str(out_dir), f)
                if os.path.exists(fp):
                    return fp
        return None
    except Exception as e:
        raise e


def main():
    refs = load_ref()
    print("Loading ASR model...")
    model = WhisperModel(str(MODEL_PATH), device="cuda", compute_type="int8_float16")

    test_files = ["sample_0000.wav", "sample_0004.wav", "sample_0104.wav"]
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
            vocals_path = separate_uvr5(str(src))
            sep_time = time.time() - t0
        except Exception as e:
            print(f"  UVR5 failed: {e}")
            continue

        if not vocals_path or not os.path.exists(vocals_path):
            print(f"  No vocals output (path={vocals_path})")
            continue

        print(f"  Separation: {sep_time:.1f}s -> {vocals_path}")

        # Vocals only
        t0 = time.time()
        voc_text = transcribe(model, vocals_path)
        voc_time = time.time() - t0
        voc_cer = cer(normalize(ref), normalize(voc_text))
        print(f"  Vocals: {voc_text}")
        print(f"  CER={voc_cer:.4f} t={voc_time:.2f}s")
        print(f"  CER change: {voc_cer - orig_cer:+.4f}")

        results.append({
            "file": fname, "ref": ref,
            "orig_text": orig_text, "orig_cer": round(orig_cer, 4), "orig_time": round(orig_time, 2),
            "vocals_text": voc_text, "vocals_cer": round(voc_cer, 4), "vocals_time": round(voc_time, 2),
            "sep_time": round(sep_time, 1), "cer_change": round(voc_cer - orig_cer, 4),
        })

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"{'File':<20} {'Orig CER':<10} {'Voc CER':<10} {'Change':<10} {'Sep Time':<10}")
    print("-" * 60)
    for r in results:
        print(f"{r['file']:<20} {r['orig_cer']:<10.4f} {r['vocals_cer']:<10.4f} {r['cer_change']:<+10.4f} {r['sep_time']:<10.1f}")

    out_path = OUT_DIR / "S5.2_results_uvr5.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()