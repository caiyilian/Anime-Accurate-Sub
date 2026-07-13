# S10.1/10.3: Subtitle generation module
# SRT/ASS with timeline optimization, bilingual mode, Aegisub-compatible export
#
# Usage:
#   python scripts/subtitle_gen.py --input segments.json --output output.srt
#   python scripts/subtitle_gen.py --input segments.json --output output.ass --style anime
#   python scripts/subtitle_gen.py --input segments.json --output output.ass --bilingual
#   python scripts/subtitle_gen.py --input bilingual.json --output output.ass --style anime_bilingual

import json, os, sys, argparse
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass
import pysubs2

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


@dataclass
class SubSegment:
    start: float      # seconds
    end: float        # seconds
    text: str         # translated text
    speaker: Optional[str] = None
    index: int = 0


MIN_DURATION = 1.0
MAX_DURATION = 7.0
MAX_CPS = 15
MAX_LINE_LENGTH = 30
MIN_GAP = 0.05


# ========== Timeline Optimization ==========

def fix_overlap(segments):
    fixed = []
    for i, seg in enumerate(segments):
        s = SubSegment(**{**seg.__dict__})
        if i > 0:
            prev = fixed[-1]
            if s.start < prev.end + MIN_GAP:
                prev.end = max(prev.start + MIN_DURATION, s.start - MIN_GAP)
        if s.end <= s.start:
            s.end = s.start + MIN_DURATION
        fixed.append(s)
    return fixed


def enforce_min_duration(segments):
    for seg in segments:
        dur = seg.end - seg.start
        if dur < MIN_DURATION:
            seg.end = seg.start + MIN_DURATION
    return segments


def enforce_max_duration(segments):
    for seg in segments:
        dur = seg.end - seg.start
        text_len = len(seg.text)
        if dur > MAX_DURATION:
            needed_dur = max(text_len / MAX_CPS, MIN_DURATION)
            seg.end = min(seg.end, seg.start + max(MAX_DURATION, needed_dur))
        cps = text_len / dur if dur > 0 else 0
        if cps < 3 and dur > 3:
            seg.end = seg.start + max(MIN_DURATION, text_len / 5)
    return segments


def check_cps(segments):
    warnings = []
    for seg in segments:
        dur = seg.end - seg.start
        text_len = len(seg.text)
        cps = text_len / dur if dur > 0 else 0
        if cps > MAX_CPS:
            warnings.append({"index": seg.index, "cps": round(cps, 1), "text": seg.text})
    return warnings


def wrap_lines(segments):
    for seg in segments:
        if len(seg.text) <= MAX_LINE_LENGTH:
            continue
        text = seg.text
        lines = []
        while len(text) > MAX_LINE_LENGTH:
            break_pos = MAX_LINE_LENGTH
            for punct in [". ", "! ", "? ", " "]:
                pos = text.rfind(punct, 0, MAX_LINE_LENGTH)
                if pos > break_pos // 2:
                    break_pos = pos + 1
                    break
            if break_pos <= 0:
                break_pos = MAX_LINE_LENGTH
            lines.append(text[:break_pos].strip())
            text = text[break_pos:].strip()
        if text:
            lines.append(text)
        seg.text = "\\N".join(lines) if len(lines) > 1 else text
    return segments


def optimize_timeline(segments):
    segments = fix_overlap(segments)
    segments = enforce_min_duration(segments)
    segments = enforce_max_duration(segments)
    segments = wrap_lines(segments)
    return segments


# ========== Bilingual ==========

def make_bilingual(ja_text, zh_text, layout="top_ja"):
    if layout == "top_ja":
        return f"{ja_text}\\N{zh_text}"
    else:
        return f"{zh_text}\\N{ja_text}"


def segments_to_bilingual(segments, ja_map, layout="top_ja"):
    result = []
    for seg in segments:
        ja_text = ja_map.get(seg.start, "")
        if ja_text:
            seg.text = make_bilingual(ja_text, seg.text, layout)
        result.append(seg)
    return result


# ========== ASS Styles ==========

STYLES = {
    "anime": {
        "fontname": "Microsoft YaHei", "fontsize": 28,
        "primarycolor": pysubs2.Color(255, 255, 255),
        "secondarycolor": pysubs2.Color(0, 0, 0),
        "outlinecolor": pysubs2.Color(0, 0, 0),
        "backcolor": pysubs2.Color(0, 0, 0),
        "bold": False, "italic": False, "underline": False, "strikeout": False,
        "scalex": 100, "scaley": 100, "spacing": 0, "angle": 0,
        "borderstyle": 1, "outline": 2, "shadow": 1, "alignment": 2,
        "marginl": 20, "marginr": 20, "marginv": 10, "encoding": 1,
    },
    "anime_bilingual": {
        "fontname": "Microsoft YaHei", "fontsize": 24,
        "primarycolor": pysubs2.Color(255, 255, 255),
        "secondarycolor": pysubs2.Color(180, 180, 180),
        "outlinecolor": pysubs2.Color(0, 0, 0),
        "backcolor": pysubs2.Color(0, 0, 0),
        "bold": False, "italic": False, "underline": False, "strikeout": False,
        "scalex": 100, "scaley": 100, "spacing": 0, "angle": 0,
        "borderstyle": 1, "outline": 2, "shadow": 1, "alignment": 2,
        "marginl": 20, "marginr": 20, "marginv": 30, "encoding": 1,
    },
    "classic": {
        "fontname": "Arial", "fontsize": 26,
        "primarycolor": pysubs2.Color(255, 255, 255),
        "secondarycolor": pysubs2.Color(0, 0, 0),
        "outlinecolor": pysubs2.Color(0, 0, 0),
        "backcolor": pysubs2.Color(0, 0, 0),
        "bold": False, "italic": False, "underline": False, "strikeout": False,
        "scalex": 100, "scaley": 100, "spacing": 0, "angle": 0,
        "borderstyle": 1, "outline": 1, "shadow": 0, "alignment": 2,
        "marginl": 20, "marginr": 20, "marginv": 15, "encoding": 1,
    },
    "karaoke": {
        "fontname": "Microsoft YaHei", "fontsize": 32,
        "primarycolor": pysubs2.Color(255, 255, 255),
        "secondarycolor": pysubs2.Color(255, 200, 0),
        "outlinecolor": pysubs2.Color(0, 0, 0),
        "backcolor": pysubs2.Color(0, 0, 0),
        "bold": True, "italic": False, "underline": False, "strikeout": False,
        "scalex": 100, "scaley": 100, "spacing": 0, "angle": 0,
        "borderstyle": 1, "outline": 3, "shadow": 1, "alignment": 2,
        "marginl": 20, "marginr": 20, "marginv": 10, "encoding": 1,
    },
}


# ========== Generate ==========

def generate(input_path, output_path, style=None, bilingual=False, bilingual_layout="top_ja"):
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    segments = []
    ja_map = {}
    for i, item in enumerate(data):
        segments.append(SubSegment(
            start=item["start"], end=item["end"],
            text=item["text"], speaker=item.get("speaker"), index=i,
        ))
        if "ja" in item:
            ja_map[item["start"]] = item["ja"]

    print(f"Loaded {len(segments)} segments")
    segments = optimize_timeline(segments)

    if bilingual and ja_map:
        segments = segments_to_bilingual(segments, ja_map, bilingual_layout)
        print(f"Bilingual mode: {bilingual_layout}")

    warnings = check_cps(segments)
    if warnings:
        print(f"CPS warnings: {len(warnings)}")

    subs = pysubs2.SSAFile()
    subs.info["Title"] = "Anime Accurate Sub"
    subs.info["Original Script"] = "Anime Accurate Sub"
    subs.info["Script Type"] = "v4.00+"
    subs.info["Collisions"] = "Normal"
    subs.info["PlayResX"] = "1920"
    subs.info["PlayResY"] = "1080"
    subs.info["Wrap Style"] = "0"
    subs.info["Scaled Border And Shadow"] = "yes"

    for seg in segments:
        subs.append(pysubs2.SSAEvent(
            start=int(seg.start * 1000),
            end=int(seg.end * 1000),
            text=seg.text,
        ))

    ext = Path(output_path).suffix.lower()
    if ext == ".ass" and style:
        sc = STYLES.get(style, STYLES["anime"])
        s = pysubs2.SSAStyle(**sc)
        subs.styles.clear()
        subs.styles[style] = s
        for ev in subs.events:
            if not ev.style:
                ev.style = style

    subs.events.sort(key=lambda e: e.start)
    subs.save(output_path)
    print(f"Saved: {output_path} ({len(subs.events)} events, style={style})")
    return subs


# ========== Test data ==========

def create_test_segments():
    return [
        SubSegment(start=0.0, end=3.5, text="Good morning, Yui."),
        SubSegment(start=3.2, end=6.0, text="Oh, good morning!"),
        SubSegment(start=6.5, end=10.0, text="You are energetic today."),
        SubSegment(start=10.5, end=15.0, text="Yes! I practiced the new guitar yesterday."),
        SubSegment(start=14.8, end=19.0, text="Is that so? Did you improve?"),
        SubSegment(start=19.5, end=25.0, text="Not yet, but it is fun!"),
        SubSegment(start=25.5, end=29.0, text="Mio, want to practice together?"),
        SubSegment(start=28.5, end=33.0, text="Sure. But I am still learning."),
        SubSegment(start=33.5, end=38.0, text="That is not true! You play well, Mio."),
        SubSegment(start=38.5, end=43.0, text="Thank you, Yui. See you after school."),
    ]


def create_bilingual_test():
    ja_texts = [
        "Good morning, Yui.", "Oh, good morning!",
        "You are energetic today.", "Yes! I practiced guitar.",
        "Is that so?", "Not yet, but it is fun!",
        "Mio, practice together?", "Sure. Still learning.",
        "Not true! You play well.", "Thanks. See you after school.",
    ]
    segments = create_test_segments()
    for i, seg in enumerate(segments):
        seg.text = f"ZH_{i}: {seg.text}"
    ja_map = {s.start: ja_texts[i] for i, s in enumerate(segments)}
    return segments, ja_map


# ========== Evaluate ==========

def evaluate():
    import tempfile
    tmp = Path(tempfile.gettempdir())

    print("\n============================================================")
    print("S10.3 SUBTITLE GENERATION EVALUATION")
    print("============================================================")

    # 1. Test single language SRT
    print("\n--- SRT Output ---")
    segs = create_test_segments()
    path = tmp / "test_mono.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump([{"start": s.start, "end": s.end, "text": s.text} for s in segs], f, ensure_ascii=False)
    out = tmp / "test_mono.srt"
    generate(str(path), str(out))

    # 2. Test bilingual ASS
    print("\n--- Bilingual ASS (anime_bilingual style) ---")
    segs, ja_map = create_bilingual_test()
    path2 = tmp / "test_bilingual.json"
    with open(path2, "w", encoding="utf-8") as f:
        json.dump([{"start": s.start, "end": s.end, "text": s.text, "ja": ja_map[s.start]}
                    for s in segs], f, ensure_ascii=False)
    out2 = tmp / "test_bilingual.ass"
    generate(str(path2), str(out2), style="anime_bilingual", bilingual=True)

    # 3. Test all styles
    print("\n--- All Styles ---")
    for style_name in STYLES:
        style_out = tmp / f"test_{style_name}.ass"
        generate(str(path2), str(style_out), style=style_name, bilingual=True)
        print(f"  {style_name}: {style_out} ({os.path.getsize(style_out)} bytes)")

    # 4. Timeline stats
    print("\n--- Timeline Stats ---")
    segs = create_test_segments()
    before_overlaps = sum(1 for i in range(1, len(segs)) if segs[i].start < segs[i-1].end)
    opt = optimize_timeline(segs)
    after_overlaps = sum(1 for i in range(1, len(opt)) if opt[i].start < opt[i-1].end)
    durs = [s.end - s.start for s in opt]
    cps = [len(s.text) / max(d, 0.1) for s, d in zip(opt, durs)]
    print(f"  Overlaps: {before_overlaps} -> {after_overlaps}")
    print(f"  Duration: {min(durs):.1f}s - {max(durs):.1f}s (avg {sum(durs)/len(durs):.1f}s)")
    print(f"  CPS: {min(cps):.1f} - {max(cps):.1f} (avg {sum(cps)/len(cps):.1f})")

    # Cleanup
    for f in [path, path2, out, out2]:
        try: f.unlink()
        except: pass

    print("\n============================================================")
    print("EVALUATION COMPLETE")
    print("============================================================")


# ========== CLI ==========

def main():
    parser = argparse.ArgumentParser(description="S10.3 Subtitle Generation")
    parser.add_argument("--input", type=str)
    parser.add_argument("--output", type=str, default="")
    parser.add_argument("--style", type=str, choices=list(STYLES.keys()), default="anime")
    parser.add_argument("--bilingual", action="store_true")
    parser.add_argument("--bilingual-layout", type=str, choices=["top_ja", "top_zh"], default="top_ja")
    parser.add_argument("--list-styles", action="store_true")
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()

    if args.list_styles:
        print("Available ASS styles:")
        for name, info in STYLES.items():
            print(f"  {name}: font={info['fontname']} {info['fontsize']}px, "
                  f"outline={info['outline']}, shadow={info['shadow']}")
        return

    if args.evaluate:
        evaluate()
        return

    if args.input and args.output:
        generate(args.input, args.output, args.style, args.bilingual, args.bilingual_layout)
        return

    parser.print_help()


if __name__ == "__main__":
    main()