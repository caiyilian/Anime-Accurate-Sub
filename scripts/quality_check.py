# S11.1: Quality check module - rule checker + suspicious line detection
#
# Rules:
#   - Duration too short/long
#   - CPS too high/low
#   - Empty translation
#   - Too many/few lines
#   - Term inconsistency (character name mismatch)
#   - Suspicious patterns (repeated chars, gibberish)
#
# Suspicious line detection:
#   - ASR confidence low (via fast.conf.avg)
#   - BGM interference
#
# Usage:
#   python scripts/quality_check.py --input segments.json --output report.json
#   python scripts/quality_check.py --input segments.json --output report.json --html

import json, os, sys, argparse
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


@dataclass
class SubSegment:
    start: float
    end: float
    text: str
    ja: Optional[str] = None
    speaker: Optional[str] = None
    confidence: Optional[float] = None
    index: int = 0


@dataclass
class QualityIssue:
    rule: str                    # rule name
    severity: str                # error / warning / info
    segment_index: int           # segment index
    message: str                 # description
    value: Optional[float] = None
    expected: Optional[str] = None


# Known character name mappings for term consistency check
DEFAULT_TERMS = {
    "yui": ["yui", "yu i"],
    "mio": ["mio"],
    "ritsu": ["ritsu", "ritsu"],
    "tsumugi": ["tsumugi", "mugi"],
}


# ============ Rule Checker ============

MIN_DURATION = 1.0
MAX_DURATION = 7.0
MAX_CPS = 15
MIN_CPS = 1.5
MAX_LINES = 2
MIN_ASR_CONFIDENCE = 0.45


def segments_from_dicts(items: List[dict]) -> List[SubSegment]:
    """Convert pipeline JSON dictionaries into typed quality-check segments."""
    return [
        SubSegment(
            start=float(item["start"]),
            end=float(item["end"]),
            text=str(item.get("text", item.get("zh", ""))),
            ja=item.get("ja"),
            speaker=item.get("speaker"),
            confidence=item.get("asr_confidence", item.get("confidence")),
            index=index,
        )
        for index, item in enumerate(items)
    ]


def check_duration(segments: List[SubSegment]) -> List[QualityIssue]:
    issues = []
    for seg in segments:
        dur = seg.end - seg.start
        if dur < MIN_DURATION:
            issues.append(QualityIssue(
                rule="duration_too_short", severity="warning",
                segment_index=seg.index,
                message=f"Duration {dur:.1f}s < min {MIN_DURATION}s",
                value=dur, expected=f">={MIN_DURATION}s",
            ))
        elif dur > MAX_DURATION:
            issues.append(QualityIssue(
                rule="duration_too_long", severity="warning",
                segment_index=seg.index,
                message=f"Duration {dur:.1f}s > max {MAX_DURATION}s",
                value=dur, expected=f"<={MAX_DURATION}s",
            ))
    return issues


def check_cps(segments: List[SubSegment]) -> List[QualityIssue]:
    issues = []
    for seg in segments:
        dur = seg.end - seg.start
        if dur <= 0:
            continue
        cps = len(seg.text) / dur
        if cps > MAX_CPS:
            issues.append(QualityIssue(
                rule="cps_too_high", severity="warning",
                segment_index=seg.index,
                message=f"CPS {cps:.1f} > max {MAX_CPS}",
                value=cps, expected=f"<={MAX_CPS}",
            ))
        elif cps < MIN_CPS:
            issues.append(QualityIssue(
                rule="cps_too_low", severity="info",
                segment_index=seg.index,
                message=f"CPS {cps:.1f} < min {MIN_CPS} (possible BGM)",
                value=cps, expected=f">={MIN_CPS}",
            ))
    return issues


def check_empty(segments: List[SubSegment]) -> List[QualityIssue]:
    issues = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            issues.append(QualityIssue(
                rule="empty_translation", severity="error",
                segment_index=seg.index,
                message="Empty translation text",
            ))
        elif len(text) < 2:
            issues.append(QualityIssue(
                rule="too_short_translation", severity="warning",
                segment_index=seg.index,
                message=f"Translation too short: '{text}' ({len(text)} chars)",
            ))
    return issues


def check_lines(segments: List[SubSegment]) -> List[QualityIssue]:
    issues = []
    for seg in segments:
        lines = seg.text.count("\\N") + 1
        if lines > MAX_LINES:
            issues.append(QualityIssue(
                rule="too_many_lines", severity="info",
                segment_index=seg.index,
                message=f"{lines} lines > max {MAX_LINES}",
                value=float(lines), expected=f"<={MAX_LINES}",
            ))
    return issues


SUSPICIOUS_PATTERNS = [
    (r"(.)\1{4,}", "repeated_char", "Repeated character (possible stutter/gibberish)"),
    (r"[a-zA-Z]{20,}", "long_ascii", "Long ASCII sequence (possible transcription error)"),
]


def check_suspicious_patterns(segments: List[SubSegment]) -> List[QualityIssue]:
    import re
    issues = []
    for seg in segments:
        for pattern, rule, msg in SUSPICIOUS_PATTERNS:
            if re.search(pattern, seg.text):
                issues.append(QualityIssue(
                    rule=rule, severity="warning",
                    segment_index=seg.index,
                    message=msg,
                ))
    return issues


def check_term_consistency(segments: List[SubSegment],
                            glossary_path: Optional[str] = None) -> List[QualityIssue]:
    issues = []
    # Load glossary for term checking
    terms = {}
    if glossary_path and Path(glossary_path).exists():
        with open(glossary_path, encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("terms", []):
            terms[item["ja"]] = item["zh"]

    # Check if terms in ja text match zh translation
    for seg in segments:
        if not seg.ja or not seg.text:
            continue
        for ja_term, zh_term in terms.items():
            if ja_term in seg.ja and zh_term not in seg.text:
                # Check if the translation contains a similar term
                if len(ja_term) > 1:  # Skip single-char terms (too many false positives)
                    issues.append(QualityIssue(
                        rule="term_inconsistency", severity="warning",
                        segment_index=seg.index,
                        message=f"Term '{ja_term}' should be '{zh_term}' but not found in translation",
                    ))
    return issues


# ============ Suspicious Line Detection ============

def detect_suspicious(segments: List[SubSegment]) -> List[QualityIssue]:
    """Detect lines with ASR confidence issues or BGM interference."""
    issues = []

    for seg in segments:
        text = seg.text.strip()
        ja = (seg.ja or "").strip()

        if seg.confidence is not None and float(seg.confidence) < MIN_ASR_CONFIDENCE:
            issues.append(QualityIssue(
                rule="low_asr_confidence", severity="warning",
                segment_index=seg.index,
                message=(
                    f"ASR confidence {float(seg.confidence):.3f} < "
                    f"{MIN_ASR_CONFIDENCE:.2f}; manual review recommended"
                ),
                value=float(seg.confidence),
                expected=f">={MIN_ASR_CONFIDENCE}",
            ))

        # Check for very short duration with long text (probably error)
        dur = seg.end - seg.start
        if dur > 0 and len(text) > 20 and dur < 1.5:
            issues.append(QualityIssue(
                rule="short_duration_long_text", severity="warning",
                segment_index=seg.index,
                message=f"Long text ({len(text)} chars) in short duration ({dur:.1f}s)",
            ))

        # Check for possible BGM interference
        # BGM-only segments often have very short or very regular timing
        if seg.ja and not text:
            issues.append(QualityIssue(
                rule="bgm_interference", severity="info",
                segment_index=seg.index,
                message="Japanese text present but empty translation",
            ))

        # Detect potential ASR hallucinations (very long runs of same/similar text)
        if ja:
            words = ja.split()
            unique_ratio = len(set(words)) / max(len(words), 1)
            if unique_ratio < 0.3 and len(words) > 5:
                issues.append(QualityIssue(
                    rule="possible_hallucination", severity="warning",
                    segment_index=seg.index,
                    message=f"Low unique word ratio {unique_ratio:.2f} (possible ASR hallucination)",
                ))

    return issues


# ============ Report Generation ============

def generate_report(segments: List[SubSegment], issues: Optional[List[QualityIssue]],
                     output_path: str, glossary_path: Optional[str] = None) -> dict:
    """Run all checks and generate report."""
    all_rules = [
        ("duration", check_duration),
        ("cps", check_cps),
        ("empty", check_empty),
        ("lines", check_lines),
        ("suspicious_patterns", check_suspicious_patterns),
        ("suspicious_lines", detect_suspicious),
    ]

    if glossary_path:
        all_rules.append(("term_consistency",
                         lambda s: check_term_consistency(s, glossary_path)))

    all_issues = list(issues or [])
    for rule_name, check_fn in all_rules:
        try:
            rule_issues = check_fn(segments)
            all_issues.extend(rule_issues)
        except Exception as e:
            print(f"  Rule '{rule_name}' failed: {e}")

    # Sort by severity
    severity_order = {"error": 0, "warning": 1, "info": 2}
    all_issues.sort(key=lambda x: (severity_order.get(x.severity, 9), x.segment_index))

    # Count stats
    stats = {
        "total_segments": len(segments),
        "total_issues": len(all_issues),
        "errors": sum(1 for i in all_issues if i.severity == "error"),
        "warnings": sum(1 for i in all_issues if i.severity == "warning"),
        "info": sum(1 for i in all_issues if i.severity == "info"),
    }

    report = {
        "generated_at": datetime.now().isoformat(),
        "stats": stats,
        "issues": [asdict(i) for i in all_issues],
        "review_queue": [],
    }

    segment_map = {segment.index: segment for segment in segments}
    for issue in all_issues:
        segment = segment_map.get(issue.segment_index)
        if segment is None:
            continue
        report["review_queue"].append({
            **asdict(issue),
            "start": segment.start,
            "end": segment.end,
            "ja": segment.ja,
            "text": segment.text,
            "speaker": segment.speaker,
            "asr_confidence": segment.confidence,
        })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\nQuality Report: {output_path}")
    print(f"  Total segments: {stats['total_segments']}")
    print(f"  Issues: {stats['errors']} errors, {stats['warnings']} warnings, {stats['info']} info")

    return report


def generate_html(report: dict, output_path: str):
    """Generate a review HTML from the quality report."""
    issues = report["issues"]
    stats = report["stats"]

    severity_colors = {"error": "#e74c3c", "warning": "#f39c12", "info": "#3498db"}

    html_rows = ""
    for issue in issues:
        color = severity_colors.get(issue["severity"], "#999")
        html_rows += f"""
        <tr>
            <td><span style="color:{color}">&#9679;</span> {issue['severity']}</td>
            <td>{issue['rule']}</td>
            <td>#{issue['segment_index']}</td>
            <td>{issue['message']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Subtitle Quality Report</title>
<style>
body {{ font-family: 'Microsoft YaHei', sans-serif; margin: 20px; background: #f5f5f5; }}
h1 {{ color: #333; }}
.stats {{ display: flex; gap: 20px; margin: 20px 0; }}
.stat-card {{ background: white; padding: 15px 25px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
.stat-card h3 {{ margin: 0; font-size: 14px; color: #666; }}
.stat-card .value {{ font-size: 28px; font-weight: bold; color: #333; }}
table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
th {{ background: #333; color: white; padding: 12px; text-align: left; }}
td {{ padding: 10px 12px; border-bottom: 1px solid #eee; }}
tr:hover {{ background: #f9f9f9; }}
.generated {{ color: #999; font-size: 12px; margin-top: 20px; }}
</style>
</head>
<body>
<h1>Subtitle Quality Report</h1>
<div class="stats">
    <div class="stat-card"><h3>Segments</h3><div class="value">{stats['total_segments']}</div></div>
    <div class="stat-card"><h3>Errors</h3><div class="value" style="color:#e74c3c">{stats['errors']}</div></div>
    <div class="stat-card"><h3>Warnings</h3><div class="value" style="color:#f39c12">{stats['warnings']}</div></div>
    <div class="stat-card"><h3>Info</h3><div class="value" style="color:#3498db">{stats['info']}</div></div>
</div>
<table>
<tr><th>Severity</th><th>Rule</th><th>Segment</th><th>Message</th></tr>
{html_rows}
</table>
<div class="generated">Generated: {report['generated_at']}</div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML Report: {output_path}")
    return output_path


# ============ CLI ============

def main():
    parser = argparse.ArgumentParser(description="S11.1 Quality Check")
    parser.add_argument("--input", type=str, help="Input JSON segments file")
    parser.add_argument("--output", type=str, default="", help="Output report path (.json or .html)")
    parser.add_argument("--glossary", type=str, help="Glossary JSON for term consistency check")
    parser.add_argument("--html", action="store_true", help="Also generate HTML review")
    parser.add_argument("--evaluate", action="store_true", help="Run evaluation with test data")
    args = parser.parse_args()

    if args.evaluate:
        evaluate()
        return

    if args.input:
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)

        segments = segments_from_dicts(data)

        output_path = args.output or str(Path(args.input).with_suffix(".quality.json"))
        report = generate_report(segments, [], output_path, args.glossary)
        if args.html:
            html_path = Path(output_path).with_suffix(".html")
            generate_html(report, str(html_path))
        return

    parser.print_help()


# ============ Test Data ============

def create_test_segments():
    return [
        SubSegment(start=0.0, end=3.5, text="Good morning, Yui.",
                   ja="Good morning, Yui.", index=0),
        SubSegment(start=3.2, end=6.0, text="",
                   ja="Oh, good morning!", index=1),  # empty translation
        SubSegment(start=6.5, end=10.0, text="You are very energetic today!",
                   ja="You are energetic today.", index=2),
        SubSegment(start=10.5, end=15.0, text="Yes! I practiced the new guitar yesterday and it was amazing!",
                   ja="Yes! I practiced guitar.", index=3),  # long text, CPS may be high
        SubSegment(start=14.8, end=19.0, text="Is that so? Did you improve?",
                   ja="Is that so?", index=4),
        SubSegment(start=19.5, end=25.0, text="Not yet, but it is really fun and enjoyable!",
                   ja="Not yet, but fun!", index=5),
        SubSegment(start=25.5, end=29.0, text="Mio, want to practice together?",
                   ja="Mio, practice together?", index=6),
        SubSegment(start=28.5, end=33.0, text="",
                   ja="Sure. Still learning.", index=7),  # empty translation
        SubSegment(start=33.5, end=38.0, text="That is not true! You play very well, Mio!",
                   ja="Not true! You play well.", index=8),
        SubSegment(start=38.5, end=43.0, text="Thank you, Yui. See you after school!",
                   ja="Thanks. See you after school.", index=9),
        SubSegment(start=50.0, end=50.5, text="Hi",
                   ja="Hi", index=10),  # too short duration + short text
    ]


def evaluate():
    print("\n============================================================")
    print("S11.1 QUALITY CHECK EVALUATION")
    print("============================================================")

    segments = create_test_segments()
    print(f"Test segments: {len(segments)}")
    print(f"  Empty translations: {sum(1 for s in segments if not s.text.strip())}")
    print(f"  Short duration: {sum(1 for s in segments if s.end - s.start < 1.0)}")

    # Run checks
    output_path = project_root / "docs" / "evaluation" / "S11.1_test_report.json"
    report = generate_report(segments, [], str(output_path))

    # Generate HTML
    html_path = output_path.with_suffix(".html")
    generate_html(report, str(html_path))

    # Print issues
    print("\n--- Issues ---")
    for issue in report["issues"][:10]:
        print(f"  [{issue['severity']:7}] #{issue['segment_index']}: {issue['message']}")
    if len(report["issues"]) > 10:
        print(f"  ... and {len(report['issues']) - 10} more")

    print("\n============================================================")
    print("EVALUATION COMPLETE")
    print("============================================================")


if __name__ == "__main__":
    main()
