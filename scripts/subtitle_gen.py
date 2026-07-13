"""S10.1: Subtitle generation module - SRT/ASS with timeline optimization.

Generates subtitle files from translation segments with timeline rules:
- Overlap fix (gap-based, no overlapping subs)
- Min/max duration (1s/7s)
- CPS (characters per second) check
- Line wrapping (max 30 chars per line)

Usage:
  python scripts/subtitle_gen.py --input segments.json --output output.srt
  python scripts/subtitle_gen.py --input segments.json --output output.ass --style anime
"""

import json, os, sys, argparse
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, field

import pysubs2

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


@dataclass
class SubSegment:
    """A single subtitle segment."""
    start: float      # seconds
    end: float        # seconds
    text: str         # translated text
    speaker: Optional[str] = None  # optional speaker label
    index: int = 0    # original index


# ======== Timeline Optimization Rules ========

MIN_DURATION = 1.0      # Minimum subtitle duration (seconds)
MAX_DURATION = 7.0      # Maximum subtitle duration (seconds)
MAX_CPS = 15            # Max characters per second (reading speed)
MAX_LINE_LENGTH = 30    # Max chars per line before wrapping
MIN_GAP = 0.05          # Minimum gap between subs (seconds)


def fix_overlap(segments: List[SubSegment]) -> List[SubSegment]:
    """Fix overlapping segments by adjusting end times."""
    fixed = []
    for i, seg in enumerate(segments):
        s = SubSegment(**{**seg.__dict__})
        if i > 0:
            prev = fixed[-1]
            if s.start < prev.end + MIN_GAP:
                # Adjust current start or previous end
                overlap = prev.end - s.start + MIN_GAP
                if overlap > 0:
                    # Shorten previous
                    prev.end = max(prev.start + MIN_DURATION, s.start - MIN_GAP)
        if s.end <= s.start:
            s.end = s.start + MIN_DURATION
        fixed.append(s)
    return fixed


def enforce_min_duration(segments: List[SubSegment]) -> List[SubSegment]:
    """Enforce minimum subtitle display duration."""
    for seg in segments:
        dur = seg.end - seg.start
        if dur < MIN_DURATION:
            seg.end = seg.start + MIN_DURATION
    return segments


def enforce_max_duration(segments: List[SubSegment]) -> List[SubSegment]:
    """Enforce maximum subtitle display duration with CPS check."""
    for seg in segments:
        dur = seg.end - seg.start
        text_len = len(seg.text)
        cps = text_len / dur if dur > 0 else 0

        if dur > MAX_DURATION:
            # Check if text is long enough to justify long duration
            needed_dur = max(text_len / MAX_CPS, MIN_DURATION)
            seg.end = min(seg.end, seg.start + max(MAX_DURATION, needed_dur))

        # Reduce duration if CPS is too low (fast readers)
        if cps < 3 and dur > 3:
            seg.end = seg.start + max(MIN_DURATION, text_len / 5)
    return segments


def check_cps(segments: List[SubSegment]) -> List[dict]:
    """Check characters per second, return warnings."""
    warnings = []
    for seg in segments:
        dur = seg.end - seg.start
        text_len = len(seg.text)
        cps = text_len / dur if dur > 0 else 0
        if cps > MAX_CPS:
            warnings.append({
                "index": seg.index,
                "cps": round(cps, 1),
                "text": seg.text,
                "suggestion": "Consider shortening text or extending duration"
            })
    return warnings


def wrap_lines(segments: List[SubSegment]) -> List[SubSegment]:
    """Wrap long lines at word boundaries or max length."""
    for seg in segments:
        if len(seg.text) <= MAX_LINE_LENGTH:
            continue
        # Try to wrap at punctuation first
        text = seg.text
        lines = []
        while len(text) > MAX_LINE_LENGTH:
            # Find best break point
            break_pos = MAX_LINE_LENGTH
            for punct in ["。", "！", "？", "、", "，", ". ", "! ", "? ", " "]:
                pos = text.rfind(punct, 0, MAX_LINE_LENGTH)
                if pos > break_pos // 2:
                    break_pos = pos + 1
                    break
            lines.append(text[:break_pos].strip())
            text = text[break_pos:].strip()
        if text:
            lines.append(text)
        seg.text = "\\N".join(lines) if len(lines) > 1 else text
    return segments


def optimize_timeline(segments: List[SubSegment]) -> List[SubSegment]:
    """Apply all timeline optimization rules."""
    segments = fix_overlap(segments)
    segments = enforce_min_duration(segments)
    segments = enforce_max_duration(segments)
    segments = wrap_lines(segments)
    return segments


# ======== Subtitle Generation ========

# ASS Style templates
STYLES = {
    "anime": {
        "fontname": "Microsoft YaHei",
        "fontsize": 28,
        "primarycolor": pysubs2.Color(255, 255, 255),
        "secondarycolor": pysubs2.Color(0, 0, 0),
        "outlinecolor": pysubs2.Color(0, 0, 0),
        "backcolor": pysubs2.Color(0, 0, 0),
        "bold": False,
        "italic": False,
        "underline": False,
        "strikeout": False,
        "scalex": 100,
        "scaley": 100,
        "spacing": 0,
        "angle": 0,
        "borderstyle": 1,
        "outline": 2,
        "shadow": 1,
        "alignment": 2,
        "marginl": 20,
        "marginr": 20,
        "marginv": 10,
        "encoding": 1,
    },
    "anime_bilingual": {
        "fontname": "Microsoft YaHei",
        "fontsize": 24,
        "primarycolor": pysubs2.Color(255, 255, 255),
        "secondarycolor": pysubs2.Color(0, 0, 0),
        "outlinecolor": pysubs2.Color(0, 0, 0),
        "backcolor": pysubs2.Color(0, 0, 0),
        "bold": False,
        "italic": False,
        "underline": False,
        "strikeout": False,
        "scalex": 100,
        "scaley": 100,
        "spacing": 0,
        "angle": 0,
        "borderstyle": 1,
        "outline": 2,
        "shadow": 1,
        "alignment": 2,
        "marginl": 20,
        "marginr": 20,
        "marginv": 30,
        "encoding": 1,
    },
}


def segments_to_subs(segments: List[SubSegment]) -> pysubs2.SSAFile:
    """Convert segments to pysubs2 subtitle file."""
    subs = pysubs2.SSAFile()
    subs.info["Title"] = "Anime Accurate Sub"
    subs.info["Original Script"] = "Anime Accurate Sub"
    subs.info["Script Type"] = "v4.00+"
    subs.info["Wrap Style"] = "0"
    subs.info["Scaled Border And Shadow"] = "yes"

    for seg in segments:
        start_ms = int(seg.start * 1000)
        end_ms = int(seg.end * 1000)
        text = seg.text
        subs.append(pysubs2.SSAEvent(start=start_ms, end=end_ms, text=text))

    return subs


def apply_ass_style(subs: pysubs2.SSAFile, style_name: str = "anime"):
    """Apply ASS style template to subtitle file."""
    style_config = STYLES.get(style_name, STYLES["anime"])
    style = pysubs2.SSAStyle(**style_config)

    # Clear default styles and add ours
    subs.styles.clear()
    subs.styles[style_name] = style

    # Set all events to use this style
    for event in subs.events:
        if not event.style:
            event.style = style_name

    return subs


def generate(input_path: str, output_path: str, style: Optional[str] = None):
    """Generate subtitle file from segments JSON.

    Input JSON format:
    [
        {"start": 1.0, "end": 4.0, "text": "早上好"},
        {"start": 4.5, "end": 8.0, "text": "你好", "speaker": "SPEAKER_00"}
    ]
    """
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    segments = []
    for i, item in enumerate(data):
        segments.append(SubSegment(
            start=item["start"],
            end=item["end"],
            text=item["text"],
            speaker=item.get("speaker"),
            index=i,
        ))

    print(f"Loaded {len(segments)} segments")

    # Optimize timeline
    segments = optimize_timeline(segments)
    print(f"After optimization: {len(segments)} segments")

    # Check CPS
    warnings = check_cps(segments)
    if warnings:
        print(f"CPS warnings: {len(warnings)}")
        for w in warnings[:3]:
            print(f"  #{w['index']}: CPS={w['cps']}, text={w['text'][:30]}")

    # Generate subtitles
    subs = segments_to_subs(segments)

    # Apply ASS style if output is ASS
    ext = Path(output_path).suffix.lower()
    if ext == ".ass" and style:
        apply_ass_style(subs, style)

    # Sort by start time
    subs.events.sort(key=lambda e: e.start)

    # Save
    subs.save(output_path)
    print(f"Saved: {output_path} ({len(subs.events)} events)")
    return subs


def create_test_segments() -> List[SubSegment]:
    """Create test segments for evaluation."""
    return [
        SubSegment(start=0.0, end=3.5, text="早安啊，唯"),
        SubSegment(start=3.2, end=6.0, text="啊，早安！"),
        SubSegment(start=6.5, end=10.0, text="今天也很有精神呢。"),
        SubSegment(start=10.5, end=15.0, text="是的！昨天练习了新的吉他。"),
        SubSegment(start=14.8, end=19.0, text="是这样啊。进步很大吧？"),
        SubSegment(start=19.5, end=25.0, text="虽然还差得远，但是很开心！"),
        SubSegment(start=25.5, end=29.0, text="小澪，要不要一起练习？"),
        SubSegment(start=28.5, end=33.0, text="好啊。不过我还在练习中。"),
        SubSegment(start=33.5, end=38.0, text="没那回事！小澪弹得很好哦。"),
        SubSegment(start=38.5, end=43.0, text="谢谢你，唯。那放学后见。这是一个很长的句子用来测试换行功能，看看是不是能正确断开。"),
    ]


def evaluate():
    """Run evaluation: generate SRT and ASS, print stats."""
    import tempfile
    tmp = Path(tempfile.gettempdir())

    segments = create_test_segments()
    for s in segments:
        # Check for overlap before optimization
        pass

    print(f"\n{'='*60}")
    print("S10.1 SUBTITLE GENERATION EVALUATION")
    print(f"{'='*60}")

    print(f"\nInput segments: {len(segments)}")
    print(f"Overlaps before: {sum(1 for i in range(1,len(segments)) if segments[i].start < segments[i-1].end)}")

    # Optimize
    optimized = optimize_timeline(segments)

    print(f"Overlaps after: {sum(1 for i in range(1,len(optimized)) if optimized[i].start < optimized[i-1].end)}")

    # Stats
    durations = [s.end - s.start for s in optimized]
    print(f"Duration range: {min(durations):.1f}s - {max(durations):.1f}s")
    print(f"Average duration: {sum(durations)/len(durations):.1f}s")

    cps_list = [len(s.text) / (s.end - s.start) for s in optimized]
    print(f"CPS range: {min(cps_list):.1f} - {max(cps_list):.1f}")
    print(f"Average CPS: {sum(cps_list)/len(cps_list):.1f}")

    # Generate files
    json_path = tmp / "test_segments.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([{"start": s.start, "end": s.end, "text": s.text} for s in optimized], f, ensure_ascii=False, indent=2)

    srt_path = tmp / "test_output.srt"
    generate(str(json_path), str(srt_path))

    ass_path = tmp / "test_output.ass"
    generate(str(json_path), str(ass_path), style="anime")

    # Verify files
    srt_size = os.path.getsize(srt_path)
    ass_size = os.path.getsize(ass_path)
    print(f"\nSRT size: {srt_size} bytes")
    print(f"ASS size: {ass_size} bytes")

    # Print sample output
    print(f"\nSample SRT:")
    with open(srt_path, encoding="utf-8") as f:
        lines = f.readlines()
        for line in lines[:15]:
            print(f"  {line.rstrip()}")

    print(f"\nSample ASS (first 15 lines):")
    with open(ass_path, encoding="utf-8") as f:
        lines = f.readlines()
        for line in lines[:15]:
            print(f"  {line.rstrip()}")

    # Cleanup
    json_path.unlink()
    srt_path.unlink()
    ass_path.unlink()

    print(f"\n{'='*60}")
    print("EVALUATION COMPLETE")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="S10.1 Subtitle Generation")
    parser.add_argument("--input", type=str, help="Input JSON segments file")
    parser.add_argument("--output", type=str, default="", help="Output subtitle file (.srt or .ass)")
    parser.add_argument("--style", type=str, choices=list(STYLES.keys()), help="ASS style template")
    parser.add_argument("--evaluate", action="store_true", help="Run evaluation with test data")
    args = parser.parse_args()

    if args.evaluate:
        evaluate()
        return

    if args.input and args.output:
        generate(args.input, args.output, args.style)
        return

    parser.print_help()


if __name__ == "__main__":
    main()