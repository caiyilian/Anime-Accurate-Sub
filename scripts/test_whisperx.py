"""S4.3: WhisperX timestamp alignment test"""
import json, time, os, re
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TEST_DIR = ROOT / "data" / "test"
OUT_DIR = ROOT / "docs" / "evaluation"
MODEL_DIR = ROOT / ".omo" / "anime-whisper-ct2"


def test_whisperx():
    import whisperx
    import torch

    device = "cuda"
    compute_type = "float16"

    # Test 1: Load whisperx with our local model
    print("\n" + "=" * 60)
    print("Test 1: Load model via whisperx")
    print("=" * 60)
    t0 = time.time()
    model = whisperx.load_model(str(MODEL_DIR), device, compute_type=compute_type, language="ja")
    print(f"  Loaded in {time.time()-t0:.1f}s")

    # Test 2: Transcribe with word timestamps
    print("\n" + "=" * 60)
    print("Test 2: Word-level timestamps")
    print("=" * 60)
    audio = str(TEST_DIR / "sample_0000.wav")
    result = model.transcribe(audio, batch_size=1)
    print(f"  Segments: {len(result['segments'])}")
    for seg in result["segments"][:3]:
        text = seg["text"].strip()[:60]
        print(f"  [{seg['start']:.2f}s -> {seg['end']:.2f}s] {text}")

    # Test 3: Align with wav2vec2
    print("\n" + "=" * 60)
    print("Test 3: wav2vec2 word alignment")
    print("=" * 60)
    t0 = time.time()
    try:
        model_a, metadata = whisperx.load_align_model(language_code="ja", device=device)
        print(f"  Align model loaded in {time.time()-t0:.1f}s")
        result = whisperx.align(result["segments"], model_a, metadata, audio, device)
        print(f"  Word-level segments: {len(result['segments'])}")
        for seg in result["segments"][:2]:
            text = seg["text"].strip()[:50]
            print(f"  [{seg['start']:.2f}s -> {seg['end']:.2f}s] {text}")
            if seg.get("words"):
                for w in seg["words"][:5]:
                    print(f"    word: [{w.get('start',0):.2f}s -> {w.get('end',0):.2f}s] {w.get('word','')}")
    except Exception as e:
        print(f"  Alignment failed: {e}")
        print("  (wav2vec2 Japanese model may not be available)")

    # Test 4: Compare with faster-whisper default timing
    print("\n" + "=" * 60)
    print("Test 4: Compare with faster-whisper timing")
    print("=" * 60)
    from faster_whisper import WhisperModel
    fw_model = WhisperModel(str(MODEL_DIR), device="cuda", compute_type="float16")
    segments, info = fw_model.transcribe(audio, language="ja", beam_size=5, vad_filter=False)
    for seg in segments:
        text = seg.text.strip()[:50]
        print(f"  FW [{seg.start:.2f}s -> {seg.end:.2f}s] {text}")

    print("\nDone")


if __name__ == "__main__":
    test_whisperx()