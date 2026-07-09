"""
Download K-On! Season 1 - all 14 episodes
Skips already downloaded files (resume-friendly)
Compresses to 480p to save space
"""

import subprocess
import sys
import re
from pathlib import Path

CURL = "C:\\Windows\\System32\\curl.exe"
VIDEO_DIR = Path(__file__).resolve().parent.parent / "data" / "video"


def get_m3u8(ep: int):
    url = f"https://acgfta.com/play/4551-7-{ep}.html"
    r = subprocess.run([CURL, "-sL", "--max-time", "15", url], capture_output=True)
    if r.returncode != 0:
        return None
    html = r.stdout.decode("utf-8", errors="ignore")
    m = re.search(r'"url":"([^"]+\.m3u8)"', html)
    return m.group(1).replace("\\/", "/") if m else None


def dl_ep(ep: int, m3u8_url: str):
    raw = VIDEO_DIR / f"_raw_ep{ep:02d}.mp4"
    final = VIDEO_DIR / f"k-on_ep{ep:02d}.mp4"
    if final.exists():
        return f"SKIP ({final.stat().st_size / 1024**2:.0f} MB)"

    import yt_dlp
    ydl = yt_dlp.YoutubeDL({"outtmpl": str(raw), "quiet": True})
    try:
        ydl.download([m3u8_url])
    except Exception as e:
        return f"DL_FAIL: {e}"
    if not raw.exists():
        return "DL_FAIL: no file"

    r = subprocess.run([
        "ffmpeg", "-i", str(raw),
        "-vf", "scale=-2:480",
        "-c:v", "libx264", "-crf", "28",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart",
        "-y", str(final)
    ], capture_output=True)
    raw.unlink(missing_ok=True)

    if final.exists():
        return f"OK ({final.stat().st_size / 1024**2:.0f} MB)"
    return "COMPRESS_FAIL"


def main():
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 50)
    print("  K-On! S1 Batch Download (14 eps)")
    print(f"  Save to: {VIDEO_DIR}")
    print(f"  Resolution: 480p")
    print("=" * 50)

    print("\n[1/2] Fetching m3u8 URLs...")
    eps = {}
    for ep in range(1, 15):
        url = get_m3u8(ep)
        eps[ep] = url
        print(f"  EP{ep:02d}: {'OK' if url else 'FAIL'}")

    done = sum(1 for ep in eps if eps[ep] and (VIDEO_DIR / f"k-on_ep{ep:02d}.mp4").exists())
    total = sum(1 for ep in eps if eps[ep])
    print(f"\n  Available: {total}, Already done: {done}, Remaining: {total - done}")

    print(f"\n[2/2] Downloading & compressing...")
    for i, (ep, url) in enumerate(sorted(eps.items()), 1):
        if not url:
            print(f"  [{i}/14] EP{ep:02d}: NO_URL")
            continue
        result = dl_ep(ep, url)
        print(f"  [{i}/14] EP{ep:02d}: {result}")

    print(f"\nDone! Files in: {VIDEO_DIR}")


if __name__ == "__main__":
    main()