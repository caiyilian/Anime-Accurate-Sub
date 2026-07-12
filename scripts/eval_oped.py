"""S7.1: OP/ED Detection evaluation - PANNs + energy-based + SenseVoice AED

Evaluates audio event classification models for OP/ED detection in anime.

Usage:
  python scripts/eval_oped.py
  python scripts/eval_oped.py --report
"""

import json, os, sys, time, argparse
from pathlib import Path
import numpy as np
import soundfile as sf

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

PROXY = "http://127.0.0.1:7890"
os.environ["http_proxy"] = PROXY
os.environ["https_proxy"] = PROXY

RESULTS_DIR = project_root / "docs" / "evaluation"
TMP_DIR = project_root / ".omo" / "tmp"


# ======== Test data ========

TEST_CLIPS = {
    "op": TMP_DIR / "oped_k-on_ep01_op.wav",
    "ed": TMP_DIR / "oped_k-on_ep01_ed.wav",
    "dialogue": TMP_DIR / "oped_k-on_ep01_dialogue.wav",
}

# Expected: OP and ED should be classified as "music", dialogue as "speech"
EXPECTED = {
    "op": "music",
    "ed": "music",
    "dialogue": "speech",
}


def load_audio(path, sr=32000):
    """Load audio, convert to mono, resample to target sr."""
    data, orig_sr = sf.read(str(path))
    if len(data.shape) > 1:
        data = data.mean(axis=1)
    if orig_sr != sr:
        import scipy.signal as signal
        ratio = sr / orig_sr
        new_len = int(len(data) * ratio)
        data = signal.resample(data, new_len)
    return data, sr


# ======== Method 1: Energy-based music detection (baseline) ========

def detect_music_energy(audio_data, sr=32000):
    """Detect music vs speech using spectral features.
    Music typically has: higher spectral centroid, more energy in higher frequencies,
    more consistent energy distribution."""
    from scipy import signal as sp_signal
    
    # Compute spectrogram
    f, t, Sxx = sp_signal.spectrogram(audio_data, sr, nperseg=int(sr*0.05))
    
    # Spectral centroid
    freqs_weighted = np.sum(f[:, None] * Sxx, axis=0) / (np.sum(Sxx, axis=0) + 1e-10)
    centroid_mean = np.mean(freqs_weighted)
    
    # Energy in high frequencies (> 2000 Hz)
    high_freq_idx = f > 2000
    if np.any(high_freq_idx):
        high_energy = np.sum(Sxx[high_freq_idx, :]) / (np.sum(Sxx, axis=0).mean() + 1e-10)
    else:
        high_energy = 0
    
    # Spectral flatness (music tends to have more structured spectrum)
    # Lower spectral flatness = more tonal = more likely music
    from scipy.stats import gmean
    flatness_per_frame = []
    for i in range(Sxx.shape[1]):
        frame = Sxx[:, i] + 1e-10
        geometric = gmean(frame)
        arithmetic = np.mean(frame)
        flatness_per_frame.append(geometric / arithmetic)
    mean_flatness = np.mean(flatness_per_frame)
    
    # Decision
    # Music typically: higher centroid, more high-freq energy, lower flatness
    music_score = centroid_mean / 5000 + high_energy / 10 - mean_flatness
    is_music = music_score > 2.0
    
    return {
        "method": "energy-based",
        "is_music": bool(is_music),
        "music_score": round(float(music_score), 4),
        "features": {
            "spectral_centroid_mean": round(float(centroid_mean), 1),
            "high_freq_energy": round(float(high_energy), 4),
            "spectral_flatness": round(float(mean_flatness), 4),
        },
    }


# ======== Method 2: PANNs CNN14 ========

_panns_model = None


def get_panns_model():
    global _panns_model
    if _panns_model is not None:
        return _panns_model
    from panns_inference import AudioTagging
    print("  Loading PANNs CNN14...")
    t0 = time.time()
    _panns_model = AudioTagging(checkpoint_path=None, device="cuda")
    print(f"    Done in {time.time()-t0:.1f}s")
    return _panns_model


def detect_music_panns(audio_data, sr=32000):
    """Detect music using PANNs CNN14 (AudioSet 527 classes)."""
    model = get_panns_model()
    
    # PANNs expects input at 32kHz
    if sr != 32000:
        import scipy.signal as signal
        ratio = 32000 / sr
        new_len = int(len(audio_data) * ratio)
        audio_data = signal.resample(audio_data, new_len)
        sr = 32000
    
    # Run inference
    t0 = time.time()
    # Pad to at least 1 second
    min_len = sr
    if len(audio_data) < min_len:
        audio_data = np.pad(audio_data, (0, min_len - len(audio_data)))
    
    clipwise_output, embedding = model.inference(audio_data[np.newaxis, :])
    infer_time = time.time() - t0
    
    # Get top classes
    # AudioSet class indices for music-related classes
    # Index 0: Speech, 10: Music, 11: Pop music, etc.
    probs = clipwise_output[0]
    
    # Music-related class indices in AudioSet
    music_classes = {
        10: "Music",        # Music
        11: "Pop music",    # Pop music
        12: "Rock music",   # Rock music
        13: "Jazz",         # Jazz
        14: "Classical music", # Classical music
        15: "Electronic music", # Electronic music/House
        16: "Dance music",  # Dance music/House
        17: "Country music", # Country music
        18: "Heavy metal",  # Heavy metal
        19: "Swing music",  # Swing music
        20: "Funk",         # Funk
        21: "Rhythm and blues", # R&B
        22: "Hip hop music", # Hip hop
        23: "Reggae",       # Reggae
        24: "Blues",        # Blues
        25: "Soul music",   # Soul music
        26: "Folk music",   # Folk music
        27: "Middle Eastern music", # Middle Eastern music
        28: "New-age music", # New-age
        29: "Vocal music",  # Vocal music
        30: "Choir",        # Choir
        0: "Speech",        # Speech
    }
    
    music_prob = sum(probs[idx] for idx in music_classes if idx != 0 and idx < len(probs))
    speech_prob = probs[0] if 0 < len(probs) else 0
    
    # Get top 5 classes
    top_indices = np.argsort(probs)[-5:][::-1]
    top_classes = []
    for idx in top_indices:
        label = music_classes.get(int(idx), f"Class_{idx}")
        top_classes.append({"class": label, "probability": round(float(probs[idx]), 4)})
    
    is_music = music_prob > speech_prob and music_prob > 0.3
    
    return {
        "method": "panns-cnn14",
        "is_music": bool(is_music),
        "music_probability": round(float(music_prob), 4),
        "speech_probability": round(float(speech_prob), 4),
        "top_classes": top_classes,
        "inference_time_s": round(infer_time, 3),
    }


# ======== Method 3: Simple spectral energy baseline ========

def detect_music_spectral(audio_data, sr=32000):
    """Simple spectral energy ratio: high energy in music frequency ranges."""
    from scipy import signal as sp_signal
    
    f, t, Sxx = sp_signal.spectrogram(audio_data, sr, nperseg=int(sr*0.05))
    
    # Music typically has energy spread across frequencies
    # Speech typically has energy concentrated in 300-3000 Hz
    speech_band = (f > 300) & (f < 3000)
    music_band = (f > 3000) & (f < 8000)
    
    speech_energy = np.sum(Sxx[speech_band, :]) / np.sum(Sxx, axis=0).mean()
    music_energy = np.sum(Sxx[music_band, :]) / np.sum(Sxx, axis=0).mean()
    
    ratio = music_energy / (speech_energy + 1e-10)
    is_music = ratio > 1.0
    
    return {
        "method": "spectral-ratio",
        "is_music": bool(is_music),
        "music_speech_ratio": round(float(ratio), 4),
        "speech_band_energy": round(float(speech_energy), 4),
        "music_band_energy": round(float(music_energy), 4),
    }


# ======== Evaluation ========

def evaluate_all():
    """Run all methods on all test clips."""
    results = {"samples": []}
    
    for clip_name, clip_path in TEST_CLIPS.items():
        if not clip_path.exists():
            print(f"SKIP: {clip_path} not found")
            continue
        
        print(f"\n{'='*60}")
        print(f"Testing: {clip_name} ({EXPECTED[clip_name]})")
        print(f"  File: {clip_path.name}")
        print(f"{'='*60}")
        
        audio_data, sr = load_audio(str(clip_path))
        duration = len(audio_data) / sr
        print(f"  Duration: {duration:.1f}s")
        
        sample_result = {
            "clip": clip_name,
            "file": str(clip_path),
            "duration": round(duration, 1),
            "expected": EXPECTED[clip_name],
            "methods": {},
        }
        
        # Method 1: Energy-based
        print("\n  [Energy-based]")
        try:
            result1 = detect_music_energy(audio_data, sr)
            sample_result["methods"]["energy-based"] = result1
            correct = result1["is_music"] == (EXPECTED[clip_name] == "music")
            print(f"    Music: {result1['is_music']}, Score: {result1['music_score']}, Correct: {correct}")
        except Exception as e:
            sample_result["methods"]["energy-based"] = {"error": str(e)}
            print(f"    ERROR: {e}")
        
        # Method 2: PANNs
        print("\n  [PANNs CNN14]")
        try:
            result2 = detect_music_panns(audio_data, sr)
            sample_result["methods"]["panns-cnn14"] = result2
            correct = result2["is_music"] == (EXPECTED[clip_name] == "music")
            print(f"    Music: {result2['is_music']}, Prob: {result2['music_probability']:.4f}, Correct: {correct}")
            print(f"    Top: {[c['class'] for c in result2['top_classes'][:3]]}")
        except Exception as e:
            sample_result["methods"]["panns-cnn14"] = {"error": str(e)}
            print(f"    ERROR: {e}")
        
        # Method 3: Spectral ratio
        print("\n  [Spectral Ratio]")
        try:
            result3 = detect_music_spectral(audio_data, sr)
            sample_result["methods"]["spectral-ratio"] = result3
            correct = result3["is_music"] == (EXPECTED[clip_name] == "music")
            print(f"    Music: {result3['is_music']}, Ratio: {result3['music_speech_ratio']:.4f}, Correct: {correct}")
        except Exception as e:
            sample_result["methods"]["spectral-ratio"] = {"error": str(e)}
            print(f"    ERROR: {e}")
        
        results["samples"].append(sample_result)
    
    return results


def print_results(results):
    """Print formatted results."""
    print(f"\n\n{'='*70}")
    print("OP/ED DETECTION EVALUATION RESULTS")
    print(f"{'='*70}")
    
    for sample in results["samples"]:
        print(f"\n  Clip: {sample['clip']} (expected: {sample['expected']})")
        for method_name, method_result in sample["methods"].items():
            if "error" in method_result:
                print(f"    [{method_name}] ERROR: {method_result['error'][:50]}")
                continue
            
            is_music = method_result.get("is_music", False)
            correct = "✓" if is_music == (sample["expected"] == "music") else "✗"
            prob = method_result.get("music_probability") or method_result.get("music_score") or ""
            print(f"    [{method_name}] {correct} music={is_music} {prob}")
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    
    methods = set()
    for sample in results["samples"]:
        methods.update(sample["methods"].keys())
    
    for method in sorted(methods):
        correct = 0
        total = 0
        for sample in results["samples"]:
            if method in sample["methods"] and "error" not in sample["methods"][method]:
                total += 1
                if sample["methods"][method]["is_music"] == (sample["expected"] == "music"):
                    correct += 1
        if total > 0:
            acc = correct / total * 100
            print(f"  {method}: {correct}/{total} correct ({acc:.0f}%)")

            # Speed
            times = [sample["methods"][method].get("inference_time_s", 0) 
                    for sample in results["samples"] 
                    if method in sample["methods"] and "inference_time_s" in sample["methods"][method]]
            if times:
                avg_time = np.mean(times)
                print(f"    Avg inference: {avg_time:.3f}s")


# ======== Main ========

def main():
    parser = argparse.ArgumentParser(description="S7.1 OP/ED Detection Evaluation")
    parser.add_argument("--report", action="store_true", help="Print report from saved results")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()
    
    if args.report:
        for rf in sorted(RESULTS_DIR.glob("S7.1_*_results.json")):
            if "all" in rf.name:
                with open(rf) as f:
                    print_results(json.load(f))
        return
    
    # Run evaluation
    results = evaluate_all()
    
    # Print results
    print_results(results)
    
    # Save
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = RESULTS_DIR / "S7.1_all_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved: {out_path}")


if __name__ == "__main__":
    main()