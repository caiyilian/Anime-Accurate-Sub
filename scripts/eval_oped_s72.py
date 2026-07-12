"""S7.2: OP/ED Detection - Cross-correlation + Audio fingerprint evaluation.

Simulates AniChapters (audio correlation) and chromaprint approaches.
Compares with energy-based baseline from S7.1.

Usage:
  python scripts/eval_oped_s72.py
  python scripts/eval_oped_s72.py --report
"""

import json, os, sys, time, argparse
from pathlib import Path
import numpy as np
import soundfile as sf

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

RESULTS_DIR = project_root / "docs" / "evaluation"
TMP_DIR = project_root / ".omo" / "tmp"
DATA_DIR = project_root / "data" / "video"

# ======== Test data ========
# We have OP/ED clips from EP01, and full episodes to test on
# For cross-correlation: use OP from EP01 as reference, find in EP02's audio

def load_audio(path, sr=16000):
    data, orig_sr = sf.read(str(path))
    if len(data.shape) > 1:
        data = data.mean(axis=1)
    if orig_sr != sr:
        import scipy.signal as sp_signal
        ratio = sr / orig_sr
        new_len = int(len(data) * ratio)
        data = sp_signal.resample(data, new_len)
    return data, sr


# ======== Method 1: Cross-correlation (simulates AniChapters) ========

def detect_oped_crosscorr(episode_audio, ref_op, ref_ed, sr=16000):
    """Detect OP/ED using cross-correlation with reference audio.
    This simulates AniChapters' approach (audio correlation with theme songs)."""
    from scipy import signal as sp_signal
    
    results = {"op": None, "ed": None}
    durations = {"op": len(ref_op)/sr, "ed": len(ref_ed)/sr}
    
    for name, ref in [("op", ref_op), ("ed", ref_ed)]:
        # Normalize both signals
        ref_norm = (ref - np.mean(ref)) / (np.std(ref) + 1e-10)
        ep_norm = (episode_audio - np.mean(episode_audio)) / (np.std(episode_audio) + 1e-10)
        
        # Cross-correlation
        # Use a windowed approach for efficiency
        ref_len = len(ref_norm)
        step = int(0.5 * sr)  # 0.5s step
        best_corr = -1
        best_pos = 0
        
        for start in range(0, len(ep_norm) - ref_len, step):
            window = ep_norm[start:start + ref_len]
            # Normalized cross-correlation
            corr = np.dot(window, ref_norm) / (np.linalg.norm(window) * np.linalg.norm(ref_norm) + 1e-10)
            if corr > best_corr:
                best_corr = corr
                best_pos = start
        
        results[name] = {
            "position_s": round(best_pos / sr, 2),
            "confidence": round(float(best_corr), 4),
            "duration_s": round(durations[name], 2),
            "detected": best_corr > 0.3,
        }
    
    return results


# ======== Method 2: MFCC-based similarity (chromaprint-like) ========

def extract_mfcc(audio, sr=16000, n_mfcc=13):
    """Extract MFCC features using simple FFT-based approach."""
    from scipy.fft import dct
    
    frame_len = int(0.025 * sr)  # 25ms
    hop_len = int(0.010 * sr)    # 10ms
    
    # Pre-emphasis
    audio = np.append(audio[0], audio[1:] - 0.97 * audio[:-1])
    
    # Framing
    n_frames = 1 + (len(audio) - frame_len) // hop_len
    frames = np.zeros((n_frames, frame_len))
    for i in range(n_frames):
        start = i * hop_len
        frames[i] = audio[start:start + frame_len] * np.hamming(frame_len)
    
    # FFT
    fft = np.fft.rfft(frames)
    power = np.abs(fft) ** 2
    
    # Mel filterbank
    n_fft = frame_len
    n_mels = 26
    low_freq = 0
    high_freq = sr / 2
    
    # Convert to mel scale
    mel_points = np.linspace(0, 2595 * np.log10(1 + high_freq / 700), n_mels + 2)
    hz_points = 700 * (10 ** (mel_points / 2595) - 1)
    bin_points = np.floor((n_fft + 1) * hz_points / sr).astype(int)
    
    filterbank = np.zeros((n_mels, n_fft // 2 + 1))
    for m in range(1, n_mels + 1):
        f_m_minus = bin_points[m - 1]
        f_m = bin_points[m]
        f_m_plus = bin_points[m + 1]
        
        for k in range(f_m_minus, f_m):
            filterbank[m - 1, k] = (k - bin_points[m - 1]) / (bin_points[m] - bin_points[m - 1])
        for k in range(f_m, f_m_plus):
            filterbank[m - 1, k] = (bin_points[m + 1] - k) / (bin_points[m + 1] - bin_points[m])
    
    mel_energy = np.dot(power, filterbank.T)
    mel_energy = np.where(mel_energy > 0, mel_energy, 1e-10)
    log_mel = np.log(mel_energy)
    
    # DCT to get MFCCs
    mfcc = dct(log_mel, type=2, axis=1, norm='ortho')[:, :n_mfcc]
    
    return mfcc


def detect_oped_mfcc(episode_audio, ref_op, ref_ed, sr=16000):
    """Detect OP/ED using MFCC similarity (chromaprint-like approach)."""
    # Extract MFCCs
    ep_mfcc = extract_mfcc(episode_audio, sr)
    op_mfcc = extract_mfcc(ref_op, sr)
    ed_mfcc = extract_mfcc(ref_ed, sr)
    
    results = {"op": None, "ed": None}
    
    for name, ref_mfcc in [("op", op_mfcc), ("ed", ed_mfcc)]:
        ref_len = ref_mfcc.shape[0]
        best_sim = -1
        best_pos = 0
        
        # Sliding window similarity
        step = max(1, ref_len // 10)  # ~10% overlap steps
        for start in range(0, ep_mfcc.shape[0] - ref_len, step):
            window = ep_mfcc[start:start + ref_len]
            
            # Cosine similarity
            sim = 0
            for t in range(ref_len):
                dot = np.dot(window[t], ref_mfcc[t])
                norm = np.linalg.norm(window[t]) * np.linalg.norm(ref_mfcc[t]) + 1e-10
                sim += dot / norm
            sim /= ref_len
            
            if sim > best_sim:
                best_sim = sim
                best_pos = start
        
        hop_len = int(0.010 * sr)
        results[name] = {
            "position_s": round(best_pos * hop_len / sr, 2),
            "confidence": round(float(best_sim), 4),
            "detected": best_sim > 0.5,
        }
    
    return results


# ======== Evaluation ========

def run_evaluation():
    """Run OP/ED detection evaluation using cross-episode matching."""
    
    # Check if we have multiple K-On! episodes
    episodes = sorted(DATA_DIR.glob("k-on_ep*.mp4"))
    if len(episodes) < 2:
        print("Need at least 2 episodes for cross-episode matching test")
        return None
    
    results = {"samples": []}
    
    # Use EP01's OP/ED as reference, EP02 as target
    ref_ep = episodes[0]
    target_ep = episodes[1]
    
    print(f"Reference: {ref_ep.name}")
    print(f"Target: {target_ep.name}")
    
    # Extract reference OP/ED from our pre-extracted clips
    ref_op_path = TMP_DIR / "oped_k-on_ep01_op.wav"
    ref_ed_path = TMP_DIR / "oped_k-on_ep01_ed.wav"
    
    if not (ref_op_path.exists() and ref_ed_path.exists()):
        print("Reference OP/ED clips not found. Run S7.1 test data preparation first.")
        return None
    
    ref_op, sr = load_audio(str(ref_op_path))
    ref_ed, _ = load_audio(str(ref_ed_path))
    
    # Extract target episode audio
    print(f"\nExtracting audio from {target_ep.name}...")
    import subprocess
    target_wav = TMP_DIR / f"{target_ep.stem}_full.wav"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(target_ep),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(target_wav)
    ], capture_output=True)
    
    ep_audio, ep_sr = load_audio(str(target_wav))
    ep_duration = len(ep_audio) / ep_sr
    print(f"  Duration: {ep_duration:.1f}s")
    
    sample_result = {
        "reference": ref_ep.name,
        "target": target_ep.name,
        "target_duration": round(ep_duration, 1),
        "ref_op_duration": round(len(ref_op)/sr, 1),
        "ref_ed_duration": round(len(ref_ed)/sr, 1),
        "methods": {},
    }
    
    # Method 1: Cross-correlation
    print("\n  [Cross-correlation]")
    t0 = time.time()
    cc_result = detect_oped_crosscorr(ep_audio, ref_op, ref_ed, sr)
    cc_time = time.time() - t0
    sample_result["methods"]["cross-correlation"] = {
        **cc_result,
        "inference_time_s": round(cc_time, 2),
    }
    for name in ["op", "ed"]:
        r = cc_result[name]
        print(f"    {name.upper()}: pos={r['position_s']:.1f}s conf={r['confidence']:.4f} detected={r['detected']}")
    
    # Method 2: MFCC similarity
    print("\n  [MFCC Similarity]")
    t0 = time.time()
    mfcc_result = detect_oped_mfcc(ep_audio, ref_op, ref_ed, sr)
    mfcc_time = time.time() - t0
    sample_result["methods"]["mfcc-similarity"] = {
        **mfcc_result,
        "inference_time_s": round(mfcc_time, 2),
    }
    for name in ["op", "ed"]:
        r = mfcc_result[name]
        print(f"    {name.upper()}: pos={r['position_s']:.1f}s conf={r['confidence']:.4f} detected={r['detected']}")
    
    # Ground truth: K-On! EP01 OP at 1:30 (90s), EP02 should be similar
    # EP01 OP starts at ~90s, EP02 OP should be at similar position
    # We'll note the expected range based on the reference position
    print(f"\n  [Ground Truth]")
    print(f"    OP expected at ~90s (beginning of episode)")
    print(f"    ED expected at ~1440s (end of episode)")
    
    results["samples"].append(sample_result)
    return results


def print_results(results):
    if not results:
        return
    print(f"\n\n{'='*70}")
    print("S7.2 OP/ED DETECTION EVALUATION")
    print(f"{'='*70}")
    
    for sample in results["samples"]:
        print(f"\n  Reference: {sample['reference']}")
        print(f"  Target: {sample['target']} ({sample['target_duration']}s)")
        
        for method_name, method_result in sample["methods"].items():
            if isinstance(method_result, dict) and "error" in method_result:
                print(f"    [{method_name}] ERROR: {method_result['error'][:50]}")
                continue
            
            print(f"\n    [{method_name}] ({method_result.get('inference_time_s', '?')}s)")
            for seg_name in ["op", "ed"]:
                if seg_name in method_result:
                    r = method_result[seg_name]
                    status = "✓" if r.get("detected") else "✗"
                    print(f"      {status} {seg_name.upper()}: {r['position_s']}s (conf={r['confidence']})")


# ======== Main ========

def main():
    parser = argparse.ArgumentParser(description="S7.2 OP/ED Detection - Cross-correlation + MFCC")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()
    
    if args.report:
        for rf in sorted(RESULTS_DIR.glob("S7.2_*_results.json")):
            with open(rf) as f:
                print_results(json.load(f))
        return
    
    results = run_evaluation()
    if results:
        print_results(results)
        out_path = RESULTS_DIR / "S7.2_all_results.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nSaved: {out_path}")
    else:
        print("Evaluation failed - check test data availability")


if __name__ == "__main__":
    main()