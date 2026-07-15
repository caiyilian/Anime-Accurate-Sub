#!/usr/bin/env python3
"""Evaluate Japanese ASR JSON against downloaded Japanese subtitle archives."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import unicodedata
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

import pysubs2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.oped_detector import infer_episode_number


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


def normalize_japanese(text: str) -> str:
    """Remove subtitle markup, spacing and punctuation for character metrics."""
    text = re.sub(r"\{[^}]*\}", "", text or "")
    text = unicodedata.normalize("NFKC", text).lower()
    return "".join(character for character in text if character.isalnum())


def levenshtein_distance(left: str, right: str) -> int:
    """Return character edit distance using O(min(n, m)) memory."""
    if len(left) > len(right):
        left, right = right, left
    previous = list(range(len(left) + 1))
    for row, right_character in enumerate(right, start=1):
        current = [row]
        for column, left_character in enumerate(left, start=1):
            insertion = current[column - 1] + 1
            deletion = previous[column] + 1
            substitution = previous[column - 1] + (left_character != right_character)
            current.append(min(insertion, deletion, substitution))
        previous = current
    return previous[-1]


def character_error_rate(reference: str, candidate: str) -> float:
    """Dependency-free Levenshtein CER."""
    reference = normalize_japanese(reference)
    candidate = normalize_japanese(candidate)
    if not reference:
        return 0.0 if not candidate else 1.0
    return levenshtein_distance(reference, candidate) / len(reference)


def load_predictions(path: Path) -> list[Segment]:
    items = json.loads(path.read_text(encoding="utf-8"))
    result = []
    for item in items:
        text = str(item.get("text", item.get("ja", ""))).strip()
        start = float(item.get("start", 0.0))
        end = float(item.get("end", start))
        if normalize_japanese(text) and end > start:
            result.append(Segment(start, end, text))
    return sorted(result, key=lambda segment: (segment.start, segment.end))


def _decode_subtitle(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp932", "utf-16"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def load_reference(archive_path: Path, episode: int) -> tuple[str, list[Segment]]:
    pattern = re.compile(rf"S1E{episode:02d}\.jp\.srt$", re.IGNORECASE)
    # The selected VCB archive contains ASCII/UTF-8 member names. An explicit
    # encoding also avoids minimal Windows Python builds that omit CP437.
    with zipfile.ZipFile(archive_path, metadata_encoding="utf-8") as archive:
        members = [name for name in archive.namelist() if pattern.search(name.replace("\\", "/"))]
        if len(members) != 1:
            raise FileNotFoundError(
                f"Expected one S1E{episode:02d}.jp.srt in {archive_path}, found {members}"
            )
        member = members[0]
        content = _decode_subtitle(archive.read(member))
    subtitles = pysubs2.SSAFile.from_string(content, format_="srt")
    result = []
    for event in subtitles.events:
        text = event.plaintext.strip()
        if event.end > event.start and normalize_japanese(text):
            result.append(Segment(event.start / 1000.0, event.end / 1000.0, text))
    return member, sorted(result, key=lambda segment: (segment.start, segment.end))


def load_oped_ranges(prediction_path: Path) -> list[tuple[float, float]]:
    path = prediction_path.with_name("oped_ranges.json")
    if not path.exists():
        return []
    items = json.loads(path.read_text(encoding="utf-8"))
    return [(float(item["start"]), float(item["end"])) for item in items]


def filter_ranges(
    segments: Sequence[Segment], ranges: Sequence[tuple[float, float]]
) -> list[Segment]:
    return [
        segment
        for segment in segments
        if not any(
            start <= (segment.start + segment.end) / 2.0 <= end
            for start, end in ranges
        )
    ]


def _overlaps(left: Segment, right: Segment, tolerance: float) -> bool:
    return left.start <= right.end + tolerance and right.start <= left.end + tolerance


def reference_coverage(
    predictions: Sequence[Segment], references: Sequence[Segment], tolerance: float
) -> float:
    matched = sum(
        any(_overlaps(prediction, reference, tolerance) for prediction in predictions)
        for reference in references
    )
    return matched / len(references) if references else 0.0


def worst_reference_windows(
    predictions: Sequence[Segment], references: Sequence[Segment], tolerance: float
) -> list[dict]:
    windows = []
    for reference in references:
        candidates = [
            prediction.text
            for prediction in predictions
            if _overlaps(prediction, reference, tolerance)
        ]
        candidate = "".join(dict.fromkeys(candidates))
        windows.append(
            {
                "start": reference.start,
                "end": reference.end,
                "reference": reference.text,
                "candidate": candidate,
                "cer": round(character_error_rate(reference.text, candidate), 4),
            }
        )
    return sorted(windows, key=lambda item: (-item["cer"], item["start"]))[:20]


def evaluate_episode(
    episode: int,
    prediction_path: Path,
    archive_path: Path,
    tolerance: float = 0.8,
) -> dict:
    predictions = load_predictions(prediction_path)
    member, references = load_reference(archive_path, episode)
    ranges = load_oped_ranges(prediction_path)
    references = filter_ranges(references, ranges)
    reference_text = "".join(segment.text for segment in references)
    candidate_text = "".join(segment.text for segment in predictions)
    normalized_reference = normalize_japanese(reference_text)
    normalized_candidate = normalize_japanese(candidate_text)
    edit_distance = levenshtein_distance(normalized_reference, normalized_candidate)
    return {
        "episode": episode,
        "prediction_path": str(prediction_path),
        "reference_member": member,
        "prediction_segments": len(predictions),
        "reference_segments": len(references),
        "oped_ranges": [{"start": start, "end": end} for start, end in ranges],
        "reference_coverage": round(
            reference_coverage(predictions, references, tolerance), 4
        ),
        "reference_characters": len(normalized_reference),
        "prediction_characters": len(normalized_candidate),
        "cer": round(
            edit_distance / len(normalized_reference) if normalized_reference else 0.0,
            4,
        ),
        "worst_windows": worst_reference_windows(predictions, references, tolerance),
        "_edit_distance": edit_distance,
    }


def discover_predictions(root: Path) -> dict[int, Path]:
    candidates = sorted(root.glob("*/asr_results.json"))
    if (root / "asr_results.json").exists():
        candidates.append(root / "asr_results.json")
    result = {}
    for path in candidates:
        episode = infer_episode_number(path.parent.name)
        if episode is not None:
            result[episode] = path
    return result


def evaluate_dataset(
    prediction_root: Path,
    archive_path: Path,
    episodes: Iterable[int] | None = None,
    tolerance: float = 0.8,
) -> dict:
    requested = list(episodes or range(1, 15))
    predictions = discover_predictions(prediction_root)
    results = []
    missing = []
    total_edit_distance = 0
    total_reference_characters = 0
    for episode in requested:
        path = predictions.get(episode)
        if path is None:
            missing.append(episode)
            continue
        result = evaluate_episode(episode, path, archive_path, tolerance)
        total_edit_distance += result.pop("_edit_distance")
        total_reference_characters += result["reference_characters"]
        results.append(result)
    coverage_values = [result["reference_coverage"] for result in results]
    return {
        "config": {
            "prediction_root": str(prediction_root),
            "reference_archive": str(archive_path),
            "episodes": requested,
            "tolerance_s": tolerance,
        },
        "aggregate": {
            "episodes": len(results),
            "missing_episodes": missing,
            "prediction_segments": sum(result["prediction_segments"] for result in results),
            "reference_segments": sum(result["reference_segments"] for result in results),
            "mean_reference_coverage": round(
                statistics.fmean(coverage_values) if coverage_values else 0.0, 4
            ),
            "corpus_cer": round(
                total_edit_distance / total_reference_characters
                if total_reference_characters
                else 0.0,
                4,
            ),
        },
        "episodes": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Japanese ASR output with a downloaded Japanese SRT ZIP"
    )
    parser.add_argument("--prediction-root", type=Path, required=True)
    parser.add_argument("--reference-archive", type=Path, required=True)
    parser.add_argument("--episodes", type=int, nargs="+")
    parser.add_argument("--tolerance", type=float, default=0.8)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate_dataset(
        args.prediction_root,
        args.reference_archive,
        episodes=args.episodes,
        tolerance=args.tolerance,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    aggregate = report["aggregate"]
    print("Japanese ASR reference evaluation")
    print(f"  Episodes: {aggregate['episodes']}")
    print(f"  Reference coverage: {aggregate['mean_reference_coverage']:.2%}")
    print(f"  Corpus CER: {aggregate['corpus_cer']:.2%}")
    print(f"  Report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
