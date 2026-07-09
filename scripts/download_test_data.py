"""
Download Anime Speech v2 test dataset
Downloads parquet files from HF mirror, extracts audio + text
"""

import json
import subprocess
import sys
from pathlib import Path

CURL = "C:\\Windows\\System32\\curl.exe"
MIRROR = "https://hf-mirror.com/datasets/joujiboi/japanese-anime-speech-v2/resolve/main"
SAMPLE_COUNT = 200
TEST_DIR = Path(__file__).resolve().parent.parent / "data" / "test"


def curl(url: str, output: Path, timeout: int = 120):
    cmd = [CURL, "-sL", "--max-time", str(timeout), "-o", str(output), url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"curl error: {result.stderr.strip()}")
        return False
    return True


def main():
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading Anime Speech v2 test dataset")
    print(f"Save to: {TEST_DIR}")
    print(f"Target: {SAMPLE_COUNT} samples")

    parquet_url = f"{MIRROR}/data/sfw-00000-of-00039.parquet"
    parquet_path = TEST_DIR / "sfw-00000.parquet"

    print(f"\n[1/2] Downloading parquet file...")
    if parquet_path.exists():
        print(f"    Already exists, skipping")
    else:
        print(f"    URL: {parquet_url}")
        if not curl(parquet_url, parquet_path):
            print("Download failed")
            sys.exit(1)
        size = parquet_path.stat().st_size / 1024**3
        print(f"    Done: {size:.1f} GB")

    print(f"\n[2/2] Extracting audio + text...")
    import pyarrow.parquet as pq
    import soundfile as sf
    import io

    table = pq.read_table(str(parquet_path))
    print(f"    Parquet has {table.num_rows} rows")

    manifest = []
    for i in range(min(SAMPLE_COUNT, table.num_rows)):
        row = table.slice(i, 1)
        audio_bytes = row.column("audio")[0]["bytes"].as_py()
        tx = row.column("transcription")[0].as_py()

        audio_data, sr = sf.read(io.BytesIO(audio_bytes))
        audio_name = f"sample_{i:04d}.wav"
        audio_path = TEST_DIR / audio_name
        sf.write(str(audio_path), audio_data, sr)
        manifest.append({"audio_file": audio_name, "transcription": tx})
        if (i + 1) % 50 == 0:
            print(f"    {i+1}/{SAMPLE_COUNT}")

    manifest_path = TEST_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\nDone! {len(manifest)} samples")
    for m in manifest[:3]:
        print(f"  {m['transcription'][:60]}")


if __name__ == "__main__":
    main()