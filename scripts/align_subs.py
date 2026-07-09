"""
整理 K-On! 中日双语字幕
从 data/S1/（中文 ASS）和 data/subtitles/K-ON!/（日文 SRT）中提取并对齐
"""

import json
import re
from pathlib import Path

CN_DIR = Path(r"E:\projects\Anime-Accurate-Sub\data\S1")
JP_FILE = Path(r"E:\projects\Anime-Accurate-Sub\data\subtitles\K-ON!")
OUT_DIR = Path(r"E:\projects\Anime-Accurate-Sub\data\test")


def parse_ass_time(t: str) -> float:
    """ASS 时间格式 0:01:23.45 -> 秒"""
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_srt_time(t: str) -> float:
    """SRT 时间格式 00:01:23,450 -> 秒"""
    t = t.replace(",", ".")
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def extract_cn_lines(ass_file: Path, ep: int) -> list[dict]:
    """从 ASS 文件提取中文对话行"""
    content = ass_file.read_text(encoding="utf-8", errors="replace")
    lines = []
    for line in content.split("\n"):
        line = line.strip()
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        start = parse_ass_time(parts[1].strip())
        end = parse_ass_time(parts[2].strip())
        text = parts[9]

        # 去掉 ASS 样式标签
        text = re.sub(r"\{[^}]*\}", "", text).strip()
        if not text:
            continue

        lines.append({
            "episode": ep,
            "start": round(start, 2),
            "end": round(end, 2),
            "text": text,
        })
    return lines


def extract_jp_lines(srt_file: Path) -> list[dict]:
    """从 SRT 文件提取所有日文行"""
    content = srt_file.read_text(encoding="utf-8-sig", errors="replace")
    lines = []
    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        blines = block.strip().split("\n")
        if len(blines) < 3:
            continue
        # 第一行是序号，第二行是时间，后面是文本
        time_match = re.match(r"(\d+:\d+:\d+[.,]\d+)\s*-->\s*(\d+:\d+:\d+[.,]\d+)", blines[1])
        if not time_match:
            continue
        start = parse_srt_time(time_match.group(1))
        end = parse_srt_time(time_match.group(2))
        text = "\n".join(blines[2:]).strip()
        lines.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "text": text,
        })
    return lines


def align_by_sequence(cn_lines: list, jp_lines: list) -> list[dict]:
    """按顺序对齐（假设中日字幕行数相近且顺序一致）"""
    aligned = []
    min_len = min(len(cn_lines), len(jp_lines))
    for i in range(min_len):
        cn = cn_lines[i]
        jp = jp_lines[i]
        # 检查时间戳是否接近（允许 3 秒误差）
        time_diff = abs(cn["start"] - jp["start"])
        aligned.append({
            "episode": cn["episode"],
            "start": min(cn["start"], jp["start"]),
            "end": max(cn["end"], jp["end"]),
            "ja": jp["text"],
            "zh": cn["text"],
            "time_diff": round(time_diff, 2),
        })
    return aligned


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 提取中文（14 个 ASS 文件）
    print("提取中文字幕...")
    all_cn = []
    cn_files = sorted(CN_DIR.glob("*.ass"))
    for f in cn_files:
        ep = int(re.search(r"EP(\d+)", f.stem).group(1)) if re.search(r"EP(\d+)", f.stem) else cn_files.index(f) + 1
        lines = extract_cn_lines(f, ep)
        all_cn.extend(lines)
        print(f"  {f.name}: {len(lines)} 行")

    # 2. 提取日文（单个 SRT 文件，包含全部集数）
    print("\n提取日文字幕...")
    srt_files = list(JP_FILE.glob("*.srt"))
    if not srt_files:
        print("  找不到 SRT 文件！")
        return
    all_jp = extract_jp_lines(srt_files[0])
    print(f"  {srt_files[0].name}: {len(all_jp)} 行")

    # 3. 按集数分割日文字幕
    # 用中文的集数边界来分割
    ep_boundaries = {}
    for line in all_cn:
        ep = line["episode"]
        if ep not in ep_boundaries:
            ep_boundaries[ep] = {"first": line["start"], "idx": all_cn.index(line)}

    # 简单分割：按比例分配
    total_cn = len(all_cn)
    eps_cn = {}
    for line in all_cn:
        eps_cn.setdefault(line["episode"], []).append(line)

    eps_jp = {}
    cn_keys = sorted(eps_cn.keys())
    # 按比例分配日文行到各集
    total_jp = len(all_jp)
    assigned = 0
    for ep in cn_keys:
        cn_count = len(eps_cn[ep])
        jp_count = int(cn_count / total_cn * total_jp)
        eps_jp[ep] = all_jp[assigned:assigned + jp_count]
        assigned += jp_count
    # 剩余的归到最后一集
    if assigned < total_jp:
        eps_jp[cn_keys[-1]].extend(all_jp[assigned:])

    # 4. 对齐
    print("\n对齐中日字幕...")
    all_aligned = []
    for ep in cn_keys:
        aligned = align_by_sequence(eps_cn[ep], eps_jp.get(ep, []))
        all_aligned.extend(aligned)
        print(f"  EP{ep:02d}: {len(aligned)} 对")

    # 5. 输出
    out_path = OUT_DIR / "k-on_bilingual.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_aligned, f, ensure_ascii=False, indent=2)
    print(f"\n输出: {out_path}")
    print(f"总对数: {len(all_aligned)}")

    # 输出一个简版查看文件
    txt_path = OUT_DIR / "k-on_bilingual_preview.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        for item in all_aligned[:30]:
            f.write(f"[EP{item['episode']:02d}] {item['start']:.1f}s\n")
            f.write(f"  JA: {item['ja'][:60]}\n")
            f.write(f"  ZH: {item['zh'][:60]}\n")
            if item["time_diff"] > 3:
                f.write(f"  ⚠️ 时间差: {item['time_diff']}s\n")
            f.write("\n")
    print(f"预览: {txt_path}")


if __name__ == "__main__":
    main()