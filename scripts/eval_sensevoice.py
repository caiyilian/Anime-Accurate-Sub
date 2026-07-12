"""
SenseVoice Small ASR evaluation using direct PyTorch model loading
Bypasses funasr AutoModel compatibility issues with Python 3.13
"""
import json, os, sys, time, re
from pathlib import Path
import numpy as np
from jiwer import cer

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

TEST_DIR = project_root / "data" / "test"
MANIFEST = TEST_DIR / "manifest.json"
OUT_DIR = project_root / "docs" / "evaluation"

def load_samples():
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    samples = []
    for item in manifest:
        ap = TEST_DIR / item["audio_file"]
        if ap.exists():
            samples.append({"audio_path": str(ap), "reference": item["transcription"]})
    print(f"Loaded {len(samples)} samples")
    return samples

def normalize_text(text):
    import re
    return re.sub(r'\s+', '', text).strip()

def test_sensevoice(samples):
    import torch
    import soundfile as sf
    from funasr import AutoModel

    print("\n" + "=" * 60)
    print("Testing SenseVoice Small")
    print("=" * 60)

    t0 = time.time()
    model = AutoModel(
        model="iic/SenseVoiceSmall",
        device="cuda:0",
        disable_update=True,
        disable_pipeline=True,
    )
    load_time = time.time() - t0
    print(f"  Loaded in {load_time:.1f}s")

    results = []
    total_asr = 0.0
    total_audio = 0.0

    for i, s in enumerate(samples):
        asr_start = time.time()
        text = ""
        try:
            # Use file path directly (funasr handles resampling internally)
            res = model.generate(
                input=s["audio_path"],
                language="ja",
                use_itn=True,
            )
            if res and isinstance(res, list) and len(res) > 0:
                if isinstance(res[0], dict):
                    text = res[0].get("text", "")
                    # Clean AED tags: <|ja|><|EMO_UNKNOWN|><|Speech|><|withitn|>
                    text = re.sub(r'<\|[^|]+\|>', '', text).strip()
        except Exception as e:
            text = f"<ERROR: {e}>"
            print(f"    ERROR sample_{i}: {type(e).__name__}: {e}")

        asr_time = time.time() - asr_start
        try:
            data, sr = sf.read(s["audio_path"])
            duration = len(data) / sr
        except:
            duration = 0
        total_asr += asr_time
        total_audio += duration
        cer_score = cer(normalize_text(s["reference"]), normalize_text(text)) if text and not text.startswith("<ERROR") else 1.0
        results.append({"sample": os.path.basename(s["audio_path"]), "reference": s["reference"], "transcription": text, "cer": cer_score, "asr_time": asr_time, "audio_duration": duration})
        if (i + 1) % 50 == 0:
            cers = [r["cer"] for r in results]
            print(f"  {i+1}/{len(samples)}, avg CER={np.mean(cers):.4f}")

    cers = [r["cer"] for r in results]
    summary = {"model": "SenseVoice Small", "samples": len(results), "load_time_s": round(load_time, 2),
        "total_asr_s": round(total_asr, 2), "total_audio_s": round(total_audio, 2),
        "rtf": round(total_asr / total_audio, 4) if total_audio > 0 else 0,
        "avg_cer": round(float(np.mean(cers)), 4), "median_cer": round(float(np.median(cers)), 4), "p90_cer": round(float(np.percentile(cers, 90)), 4)}
    print(f"\n  Avg CER: {summary['avg_cer']:.4f}  Med CER: {summary['median_cer']:.4f}  RTF: {summary['rtf']:.4f}")
    return summary

if __name__ == "__main__":
    os.environ["MODELSCOPE_CACHE"] = os.path.expanduser("~/.cache/modelscope/hub")
    samples = load_samples()
    result = test_sensevoice(samples)
    out_path = OUT_DIR / "S4.1_results_sensevoice.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {out_path}")