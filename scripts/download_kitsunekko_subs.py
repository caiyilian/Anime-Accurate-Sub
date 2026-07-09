"""
从 Kitsunekko 下载指定动漫的日文字幕
用法: python scripts/download_kitsunekko_subs.py <动漫目录名>
示例: python scripts/download_kitsunekko_subs.py Bakemonogatari
       python scripts/download_kitsunekko_subs.py K-ON!
       python scripts/download_kitsunekko_subs.py Steins;Gate
"""

import subprocess
import sys
import re
import urllib.parse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

CURL = "C:\\Windows\\System32\\curl.exe"
BASE_URL = "https://kitsunekko.net/subtitles/japanese"
SAVE_DIR = Path(__file__).resolve().parent.parent / "data" / "subtitles"


def curl(url: str, timeout: int = 30):
    cmd = [CURL, "-sL", "--max-time", str(timeout), url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout


def download_file(f: str, anime: str) -> tuple[str, int | None]:
    file_url = f"{BASE_URL}/{anime}/{f}"
    decoded_name = urllib.parse.unquote(f)
    file_path = SAVE_DIR / anime / decoded_name
    if file_path.exists():
        return (decoded_name, file_path.stat().st_size)
    cmd = [CURL, "-sL", "--max-time", "60", "-o", str(file_path), file_url]
    subprocess.run(cmd, capture_output=True)
    if file_path.exists():
        return (decoded_name, file_path.stat().st_size)
    return (decoded_name, None)


def main():
    if len(sys.argv) < 2:
        html = curl(f"{BASE_URL}/")
        if not html:
            print("错误: 无法连接 Kitsunekko")
            sys.exit(1)
        titles = re.findall(r'href="([^"]+)/"', html)
        print(f"\nKitsunekko 共有 {len(titles)} 部动漫的日文字幕")
        print(f"\n用法: python scripts/download_kitsunekko_subs.py <动漫名>")
        print(f"例如: python scripts/download_kitsunekko_subs.py Bakemonogatari")
        print(f"       python scripts/download_kitsunekko_subs.py K-ON!")
        return

    anime = sys.argv[1]
    print(f"\n正在获取 {anime} 的字幕列表...")

    html = curl(f"{BASE_URL}/{anime}/", timeout=30)
    if not html:
        print(f"错误: 无法访问 {BASE_URL}/{anime}/")
        sys.exit(1)

    files = re.findall(r'href="([^"]+\.(?:srt|ass|zip|rar|7z))"', html)
    if not files:
        print(f"在 {anime} 中没找到字幕文件")
        sys.exit(1)

    save_dir = SAVE_DIR / anime
    save_dir.mkdir(parents=True, exist_ok=True)
    print(f"找到 {len(files)} 个字幕文件")
    print(f"保存到: {save_dir}\n")

    try:
        from tqdm import tqdm
        use_tqdm = True
    except ImportError:
        use_tqdm = False

    downloaded = 0
    skipped = 0
    failed = 0

    if use_tqdm:
        # 带进度条的并行下载
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = {ex.submit(download_file, f, anime): f for f in files}
            for future in tqdm(as_completed(futures), total=len(files), unit="file", desc="下载进度"):
                name, size = future.result()
                if size is None:
                    failed += 1
                elif size == 0:
                    skipped += 1
                else:
                    downloaded += 1
    else:
        # 不带进度条
        for i, f in enumerate(files, 1):
            name, size = download_file(f, anime)
            if size is None:
                print(f"  [{i}/{len(files)}] 失败: {name}")
                failed += 1
            else:
                print(f"  [{i}/{len(files)}] OK: {name} ({size/1024:.0f} KB)")
                downloaded += 1

    print(f"\n完成！保存到: {save_dir}")
    print(f"  已下载: {downloaded}  跳过: {skipped}  失败: {failed}")


if __name__ == "__main__":
    main()