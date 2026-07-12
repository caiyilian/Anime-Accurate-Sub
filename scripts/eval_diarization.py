"""S6.1: Speaker Diarization evaluation for anime audio.

Method: VAD + pyannote embedding + clustering + faster-whisper ASR
(No gated models required for the core pipeline)

Usage:
  python scripts/eval_diarization.py --audio .omo/tmp/k-on_multi_01.wav
  python scripts/eval_diarization.py --all
  python scripts/eval_diarization.py --report
"""

import json, os, sys, time, argparse
from pathlib import Path
import numpy as np
import torch
import soundfile as sf

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

PROXY = "http://127.0.0.1:7890"
os.environ["http_proxy"] = PROXY
os.environ["https_proxy"] = PROXY
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

RESULTS_DIR = project_root / "docs" / "evaluation"
TMP_DIR = project_root / ".omo" / "tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)

device = "cuda" if torch.cuda.is_available() else "cpu"


def load_audio(path, sr=16000):
    data, orig_sr = sf.read(str(path))
    if len(data.shape) > 1:
        data = data.mean(axis=1)
    if orig_sr != sr:
        import scipy.signal as signal
        ratio = sr / orig_sr
        new_len = int(len(data) * ratio)
        data = signal.resample(data, new_len)
    return data, sr


def fmt_ts(sec):
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


_whisper = None
_embed_model = None


def get_whisper():
    global _whisper
    if _whisper is not None:
        return _whisper
    from faster_whisper import WhisperModel
    model_path = project_root / ".omo" / "anime-whisper-ct2"
    print(f"Loading faster-whisper (Anime Whisper) from {model_path}...")
    t0 = time.time()
    _whisper = WhisperModel(str(model_path), device="cuda", compute_type="int8_float16", num_workers=1)
    print(f"  Done in {time.time()-t0:.1f}s")
    return _whisper


def get_embedding_model():
    global _embed_model
    if _embed_model is not None:
        return _embed_model
    from speechbrain.inference.speaker import EncoderClassifier
    print("Loading speechbrain ECAPA-TDNN speaker embedding model...")
    t0 = time.time()
    _embed_model = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(project_root / ".omo" / "speechbrain-models"),
        run_opts={"device": f"{device}:0" if device == "cuda" else device},
    )
    print(f"  Done in {time.time()-t0:.1f}s")
    return _embed_model


def run_vad(audio_data, sr=16000):
    """Simple energy-based VAD."""
    frame_len = int(0.1 * sr)
    energy_threshold = 0.02
    min_speech_dur = 0.3

    n_frames = len(audio_data) // frame_len
    speech_frames = []
    for i in range(n_frames):
        start = i * frame_len
        end = start + frame_len
        frame = audio_data[start:end]
        energy = np.sqrt(np.mean(frame ** 2))
        if energy > energy_threshold:
            speech_frames.append(i)

    if not speech_frames:
        return []

    groups = []
    current_group = [speech_frames[0]]
    for i in range(1, len(speech_frames)):
        if speech_frames[i] - speech_frames[i-1] <= 2:
            current_group.append(speech_frames[i])
        else:
            groups.append(current_group)
            current_group = [speech_frames[i]]
    groups.append(current_group)

    segments = []
    for g in groups:
        dur = len(g) * 0.1
        if dur >= min_speech_dur:
            segments.append({
                "start": round(g[0] * 0.1, 2),
                "end": round((g[-1] + 1) * 0.1, 2),
            })
    return segments


def run_diarization(audio_path, num_speakers=None):
    """VAD + embedding + clustering + ASR."""
    embed_model = get_embedding_model()
    whisper = get_whisper()

    audio_data, sr = load_audio(audio_path)
    duration = len(audio_data) / sr
    print(f"  Audio: {Path(audio_path).name}, {duration:.1f}s, {sr}Hz")

    # Step 1: VAD
    print("  Step 1: VAD...")
    t0 = time.time()
    vad_segments = run_vad(audio_data, sr)
    vad_time = time.time() - t0
    print(f"    {len(vad_segments)} speech segments in {vad_time:.2f}s")

    if not vad_segments:
        return {"segments": [], "speakers": ["SPEAKER_00"], "num_speakers_found": 1,
                "method": "vad+embed+cluster+asr", "elapsed": 0, "rtf": 0}

    # Step 2: Embeddings
    print(f"  Step 2: Extracting {len(vad_segments)} embeddings...")
    t0 = time.time()
    embeddings = []
    valid_segments = []
    for seg in vad_segments:
        if seg["end"] - seg["start"] < 0.5:
            continue
        s_s = int(seg["start"] * sr)
        e_s = int(seg["end"] * sr)
        seg_data = audio_data[s_s:e_s]
        try:
            tensor_data = torch.from_numpy(seg_data).float().unsqueeze(0)
            emb = embed_model.encode_batch(tensor_data).squeeze(0).squeeze(0).cpu().numpy()
            embeddings.append(emb)
            valid_segments.append(seg)
        except Exception:
            pass
    embed_time = time.time() - t0

    # Step 3: Clustering
    t0 = time.time()
    if len(embeddings) < 2:
        for s in valid_segments:
            s["speaker"] = "SPEAKER_00"
    else:
        from sklearn.cluster import AgglomerativeClustering
        emb_matrix = np.stack(embeddings)
        n_clusters = num_speakers if num_speakers else min(4, len(embeddings))
        clustering = AgglomerativeClustering(n_clusters=n_clusters, metric="cosine", linkage="average")
        labels = clustering.fit_predict(emb_matrix)
        for i, label in enumerate(labels):
            valid_segments[i]["speaker"] = f"SPEAKER_{label:02d}"
    cluster_time = time.time() - t0

    # Step 4: ASR
    print("  Step 4: ASR (Anime Whisper)...")
    t0 = time.time()
    segments_asr, info = whisper.transcribe(
        str(audio_path), language="ja", beam_size=5, vad_filter=False
    )
    asr_segments = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments_asr]
    asr_time = time.time() - t0

    # Step 5: Assign speakers
    t0 = time.time()
    diarized = []
    for asr_seg in asr_segments:
        best_spk = "SPEAKER_00"
        best_overlap = 0
        for ds in valid_segments:
            overlap = max(0, min(asr_seg["end"], ds["end"]) - max(asr_seg["start"], ds["start"]))
            if overlap > best_overlap:
                best_overlap = overlap
                best_spk = ds["speaker"]
        diarized.append({"speaker": best_spk, "text": asr_seg["text"], "start": asr_seg["start"], "end": asr_seg["end"]})
    assign_time = time.time() - t0

    total_time = vad_time + embed_time + cluster_time + asr_time + assign_time
    rtf = total_time / duration if duration > 0 else 0

    return {
        "segments": diarized,
        "speakers": sorted(set(s["speaker"] for s in diarized)),
        "num_speakers_found": len(set(s["speaker"] for s in diarized)),
        "method": "vad+embed+cluster+asr",
        "elapsed": round(total_time, 2), "rtf": round(rtf, 3),
        "stats": {"vad_s": round(vad_time, 2), "embed_s": round(embed_time, 2),
                  "cluster_s": round(cluster_time, 2), "asr_s": round(asr_time, 2), "assign_s": round(assign_time, 2)},
    }


def compute_stats(segments):
    changes = sum(1 for i in range(1, len(segments)) if segments[i]["speaker"] != segments[i-1]["speaker"])
    avg_dur = round(np.mean([s["end"] - s["start"] for s in segments]), 2) if segments else 0
    return {"num_segments": len(segments), "num_speaker_changes": changes, "avg_segment_dur": avg_dur}


def find_test_audio():
    return list(TMP_DIR.glob("k-on_multi_*.wav")) + list(TMP_DIR.glob("sample_diarization_*.mp3"))


def print_results(results):
    print(f"\n{'='*70}")
    print(f"RESULTS: {Path(results.get('audio_file', '?')).name}")
    dur = results.get("duration", 0)
    print(f"Duration: {dur:.1f}s" if dur else "")
    print(f"{'='*70}")

    for mn, mr in results.get("methods", {}).items():
        print(f"\n  [{mn}]")
        if "error" in mr:
            print(f"    SKIPPED: {mr['error'][:80]}")
            continue
        print(f"    Speakers: {mr.get('num_speakers_found', '?')}")
        print(f"    Elapsed: {mr.get('elapsed', '?')}s | RTF: {mr.get('rtf', '?')}")
        if "stats" in mr:
            s = mr["stats"]
            print(f"    Breakdown: vad={s.get('vad_s','?')}s emb={s.get('embed_s','?')}s "
                  f"cluster={s.get('cluster_s','?')}s asr={s.get('asr_s','?')}s assign={s.get('assign_s','?')}s")

        segs = mr.get("segments", [])
        stats = compute_stats(segs)
        print(f"    Segments: {stats['num_segments']}, changes: {stats['num_speaker_changes']}, avg: {stats['avg_segment_dur']}s")

        for seg in segs[:12]:
            ts, te = fmt_ts(seg["start"]), fmt_ts(seg["end"])
            text = seg.get("text", "")
            line = f"      [{seg['speaker']}] {ts}-{te}"
            if text:
                line += f"  {text[:50]}"
            print(line)
        if len(segs) > 12:
            print(f"      ... ({len(segs)-12} more)")


def main():
    parser = argparse.ArgumentParser(description="S6.1 Speaker Diarization Evaluation")
    parser.add_argument("--audio", type=str)
    parser.add_argument("--num-speakers", type=int, default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    if args.report:
        for rf in sorted(RESULTS_DIR.glob("S6.1_*_results.json")):
            if rf.name == "S6.1_all_results.json":
                continue
            with open(rf) as f:
                print_results(json.load(f))
        return

    test_files = []
    if args.audio:
        test_files = [Path(args.audio)]
    elif args.all:
        test_files = find_test_audio()

    if not test_files:
        parser.print_help()
        return

    combined = {"samples": []}
    for audio_path in test_files:
        if not audio_path.exists():
            print(f"NOT FOUND: {audio_path}")
            continue

        audio_data, sr = load_audio(audio_path)
        duration = len(audio_data) / sr
        results = {"audio_file": str(audio_path), "duration": round(duration, 1), "methods": {}}

        print(f"\n{'='*60}")
        print("Method: VAD + embedding + clustering + Anime Whisper")
        print(f"{'='*60}")
        try:
            results["methods"]["vad+embed+cluster+asr"] = run_diarization(audio_path, args.num_speakers)
        except Exception as e:
            import traceback; traceback.print_exc()
            results["methods"]["vad+embed+cluster+asr"] = {"error": str(e), "method": "vad+embed+cluster+asr"}

        print_results(results)

        stem = audio_path.stem.replace(" ", "_")
        out_path = RESULTS_DIR / f"S6.1_{stem}_results.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nSaved: {out_path}")
        combined["samples"].append(results)

    comb_path = RESULTS_DIR / "S6.1_all_results.json"
    with open(comb_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)
    print(f"Combined: {comb_path}")


if __name__ == "__main__":
    main()