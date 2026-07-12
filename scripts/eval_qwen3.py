"""S4.2: Qwen3-ASR-1.7B-JA evaluation - CER + proper noun comparison"""
import json, os, sys, time, re
from pathlib import Path
import numpy as np
from jiwer import cer

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

TEST_DIR = project_root / "data" / "test"
MANIFEST = TEST_DIR / "manifest.json"
OUT_DIR = project_root / "docs" / "evaluation"
MODEL_PATH = project_root / "packages" / "reference-projects" / "Sprint-2" / "JAVTrans" / "models" / "jaykwok-Qwen3-ASR-1.7B-JA-Anime-Galgame-hf"

SAMPLE_RATE = 16000


def move_processor_inputs(inputs, device, dtype):
    import torch
    moved = {}
    for key, value in inputs.items():
        if not torch.is_tensor(value):
            moved[key] = value
        elif torch.is_floating_point(value):
            moved[key] = value.to(device=device, dtype=dtype)
        else:
            moved[key] = value.to(device=device)
    return moved

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
    return re.sub(r'\s+', '', text).strip()

def test_qwen3(samples):
    import torch
    from transformers import AutoModelForMultimodalLM, AutoProcessor

    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

    print("\n" + "=" * 60)
    print("Testing Qwen3-ASR-1.7B-JA-Anime-Galgame")
    print("=" * 60)

    t0 = time.time()
    processor = AutoProcessor.from_pretrained(str(MODEL_PATH))
    model = AutoModelForMultimodalLM.from_pretrained(
        str(MODEL_PATH),
        torch_dtype=torch.float16,
        device_map="cuda:0",
        attn_implementation="sdpa",
    )
    model.eval()
    load_time = time.time() - t0
    print(f"  Loaded in {load_time:.1f}s")

    results = []
    total_asr = 0.0
    total_audio = 0.0

    for i, s in enumerate(samples):
        asr_start = time.time()
        text = ""
        try:
            import soundfile as sf
            import scipy.signal
            audio, sr = sf.read(s["audio_path"])
            if len(audio.shape) > 1:
                audio = audio.mean(axis=1)
            audio = audio.astype(np.float32)
            # Resample to 16kHz if needed
            if sr != SAMPLE_RATE:
                audio = scipy.signal.resample_poly(audio, SAMPLE_RATE, sr).astype(np.float32)
            audio = np.ascontiguousarray(audio, dtype=np.float32)

            inputs = processor.apply_transcription_request(
                audio=[audio],
                language=["Japanese"],
            )
            inputs = move_processor_inputs(inputs, device="cuda", dtype=torch.float16)

            with torch.no_grad():
                generated = model.generate(
                    **inputs,
                    max_new_tokens=128,
                )

            text = processor.decode(generated[0], skip_special_tokens=True)
            text = text.strip()
            # Extract ASR text from <asr_text> tag
            m = re.search(r'<asr_text>(.*)', text, re.DOTALL)
            if m:
                text = m.group(1).strip()
            else:
                # Fallback: take text after last "assistant"
                parts = text.split("assistant")
                if len(parts) > 1:
                    text = parts[-1].strip()
                    # Remove language prefix
                    text = re.sub(r'^language\s+\w+\s*', '', text)
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
    summary = {"model": "Qwen3-ASR-1.7B-JA-Anime-Galgame", "samples": len(results), "load_time_s": round(load_time, 2),
        "total_asr_s": round(total_asr, 2), "total_audio_s": round(total_audio, 2),
        "rtf": round(total_asr / total_audio, 4) if total_audio > 0 else 0,
        "avg_cer": round(float(np.mean(cers)), 4), "median_cer": round(float(np.median(cers)), 4), "p90_cer": round(float(np.percentile(cers, 90)), 4)}
    print(f"\n  Avg CER: {summary['avg_cer']:.4f}  Med CER: {summary['median_cer']:.4f}  RTF: {summary['rtf']:.4f}")
    return summary

if __name__ == "__main__":
    samples = load_samples()
    result = test_qwen3(samples)
    out_path = OUT_DIR / "S4.2_results_qwen3.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {out_path}")