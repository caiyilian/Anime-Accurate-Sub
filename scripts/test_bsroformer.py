"""S5.3: BS-RoFormer evaluation"""
import sys, os, time, json, re
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

os.environ["http_proxy"] = "http://127.0.0.1:7890"
os.environ["https_proxy"] = "http://127.0.0.1:7890"


def normalize(t):
    return re.sub(r'\s+', '', t).strip()


def load_ref():
    with open(MANIFEST, encoding="utf-8") as f:
        return {item["audio_file"]: item["transcription"] for item in json.load(f)}


def transcribe(model, audio_path):
    segs, info = model.transcribe(audio_path, language="ja", beam_size=5, vad_filter=False)
    return " ".join([s.text.strip() for s in segs])


def pad_audio(src_path, min_duration=12):
    """Pad audio with silence to minimum duration for BS-RoFormer"""
    import soundfile as sf
    data, sr = sf.read(src_path)
    if len(data.shape) > 1:
        data = data.mean(axis=1)
    needed = int(min_duration * sr)
    if len(data) >= needed:
        return src_path
    padded = np.pad(data, (0, needed - len(data)), mode="constant")
    out_path = TMP_DIR / f"padded_{Path(src_path).name}"
    sf.write(str(out_path), padded, sr)
    return str(out_path)


def separate_bsroformer(audio_path):
    """Run BS-RoFormer separation"""
    from audio_separator.separator import Separator
    out_dir = TMP_DIR / "uvr5_output"
    out_dir.mkdir(parents=True, exist_ok=True)

    sep = Separator(
        output_dir=str(out_dir),
        log_level=30,
        sample_rate=44100,
    )
    sep.load_model("model_bs_roformer_ep_317_sdr_12.9755.ckpt")
    output_files = sep.separate(audio_path)
    for f in output_files or []:
        if "vocals" in f.lower():
            fp = os.path.join(str(out_dir), f)
            if os.path.exists(fp):
                return fp
    if output_files:
        fp = os.path.join(str(out_dir), output_files[0])
        if os.path.exists(fp):
            return fp
    return None


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
        print(f"  Orig: CER={orig_cer:.4f} t={orig_time:.2f}s")

        # Pad audio to min 12s for BS-RoFormer
        padded = pad_audio(str(src))

        # Separate
        t0 = time.time()
        try:
            vocals_path = separate_bsroformer(padded)
            sep_time = time.time() - t0
        except Exception as e:
            print(f"  BS-RoFormer failed: {e}")
            continue

        if not vocals_path or not os.path.exists(vocals_path):
            print(f"  No output")
            continue

        print(f"  Separation: {sep_time:.1f}s")

        # Vocals only
        t0 = time.time()
        voc_text = transcribe(model, vocals_path)
        voc_time = time.time() - t0
        voc_cer = cer(normalize(ref), normalize(voc_text))
        print(f"  Vocals: CER={voc_cer:.4f} t={voc_time:.2f}s")
        print(f"  Change: {voc_cer - orig_cer:+.4f}")

        results.append({
            "file": fname, "ref": ref,
            "orig_text": orig_text, "orig_cer": round(orig_cer, 4), "orig_time": round(orig_time, 2),
            "vocals_text": voc_text, "vocals_cer": round(voc_cer, 4),
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

    # Save
    out_path = OUT_DIR / "S5.3_results_bsroformer.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()