#!/usr/bin/env python3
"""Evaluate generated Chinese subtitles against fansub ASS references.

The evaluator is deliberately segmentation-independent: each generated segment is
matched with every reference dialogue that overlaps it on the timeline. This makes
the result useful even when Whisper and the fansub group split the same conversation
into different numbers of lines.

Usage:
  python scripts/eval_fansub_quality.py \
    --prediction-root output_clean \
    --reference-root data/S1 \
    --output docs/evaluation/fansub_quality_baseline.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Sequence

import pysubs2


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIALOGUE_STYLES = {"DEFAULT", "YUI", "MUGI", "MIO", "RITU", "AZUSA"}
SONG_STYLES = {"OPCN", "EDCN", "FUWACN", "IMCN"}


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str
    source: str = ""
    style: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class Alignment:
    prediction_index: int
    reference_indices: tuple[int, ...]
    source: str
    candidate: str
    reference: str
    start: float
    end: float
    char_f1: float
    chrf: float
    edit_similarity: float


def clean_subtitle_text(text: str) -> str:
    """Remove ASS markup while retaining human-visible subtitle text."""
    text = re.sub(r"\{[^}]*}", "", text or "")
    text = text.replace(r"\N", " ").replace(r"\n", " ").replace("\ufeff", "")
    return re.sub(r"\s+", " ", text).strip()


def normalize_zh(text: str) -> str:
    """Normalize Chinese text for reference-based automatic metrics."""
    text = unicodedata.normalize("NFKC", clean_subtitle_text(text)).lower()
    return "".join(ch for ch in text if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _counter_f1(candidate: Counter, reference: Counter) -> float:
    if not candidate or not reference:
        return 0.0
    overlap = sum((candidate & reference).values())
    precision = overlap / sum(candidate.values())
    recall = overlap / sum(reference.values())
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def char_f1(candidate: str, reference: str) -> float:
    return _counter_f1(Counter(normalize_zh(candidate)), Counter(normalize_zh(reference)))


def _ngrams(text: str, n: int) -> Counter:
    return Counter(text[i : i + n] for i in range(max(0, len(text) - n + 1)))


def chrf(candidate: str, reference: str, max_order: int = 3) -> float:
    """Small dependency-free chrF variant averaged over character n-grams."""
    candidate = normalize_zh(candidate)
    reference = normalize_zh(reference)
    scores = [
        _counter_f1(_ngrams(candidate, n), _ngrams(reference, n))
        for n in range(1, max_order + 1)
        if len(candidate) >= n and len(reference) >= n
    ]
    return statistics.fmean(scores) if scores else 0.0


def edit_similarity(candidate: str, reference: str) -> float:
    candidate = normalize_zh(candidate)
    reference = normalize_zh(reference)
    if not candidate or not reference:
        return 0.0
    return SequenceMatcher(None, candidate, reference, autojunk=False).ratio()


def load_predictions(path: Path) -> list[Segment]:
    data = json.loads(path.read_text(encoding="utf-8"))
    segments = []
    for item in data:
        text = clean_subtitle_text(str(item.get("text", item.get("zh", ""))))
        source = clean_subtitle_text(str(item.get("ja", item.get("source", ""))))
        start = float(item.get("start", 0.0))
        end = float(item.get("end", start))
        if text and end > start:
            segments.append(Segment(start, end, text, source=source))
    return sorted(segments, key=lambda segment: (segment.start, segment.end))


def load_fansub(
    path: Path,
    dialogue_styles: set[str] | None = None,
    include_songs: bool = False,
) -> list[Segment]:
    styles = {style.upper() for style in (dialogue_styles or DEFAULT_DIALOGUE_STYLES)}
    if include_songs:
        styles |= SONG_STYLES
    subtitles = pysubs2.load(str(path), encoding="utf-8")
    result = []
    for event in subtitles.events:
        if event.is_comment or event.style.upper() not in styles:
            continue
        text = clean_subtitle_text(event.plaintext)
        # Formatting markers such as "~" are not spoken reference translations.
        if not normalize_zh(text):
            continue
        result.append(
            Segment(
                start=event.start / 1000.0,
                end=event.end / 1000.0,
                text=text,
                style=event.style,
            )
        )
    return sorted(result, key=lambda segment: (segment.start, segment.end, segment.text))


def _overlap_seconds(left: Segment, right: Segment, tolerance: float) -> float:
    overlap = min(left.end, right.end) - max(left.start, right.start)
    if overlap > 0:
        return overlap
    if left.end + tolerance >= right.start and right.end + tolerance >= left.start:
        return tolerance
    return 0.0


def align_segments(
    predictions: Sequence[Segment],
    references: Sequence[Segment],
    tolerance: float = 0.35,
) -> tuple[list[Alignment], set[int]]:
    """Align predictions to all temporally overlapping reference events."""
    alignments = []
    matched_references: set[int] = set()
    first_reference = 0

    for pred_index, prediction in enumerate(predictions):
        while (
            first_reference < len(references)
            and references[first_reference].end + tolerance < prediction.start
        ):
            first_reference += 1

        matches = []
        ref_index = first_reference
        while ref_index < len(references):
            reference = references[ref_index]
            if reference.start - tolerance > prediction.end:
                break
            if _overlap_seconds(prediction, reference, tolerance) > 0:
                matches.append(ref_index)
            ref_index += 1

        if not matches:
            continue

        matched_references.update(matches)
        # Remove exact duplicate text caused by overlapping ASS effect events.
        ref_texts = list(dict.fromkeys(references[index].text for index in matches))
        reference_text = " ".join(ref_texts)
        alignments.append(
            Alignment(
                prediction_index=pred_index,
                reference_indices=tuple(matches),
                source=prediction.source,
                candidate=prediction.text,
                reference=reference_text,
                start=prediction.start,
                end=prediction.end,
                char_f1=char_f1(prediction.text, reference_text),
                chrf=chrf(prediction.text, reference_text),
                edit_similarity=edit_similarity(prediction.text, reference_text),
            )
        )

    return alignments, matched_references


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def asr_health(predictions: Sequence[Segment]) -> dict:
    durations = [segment.duration for segment in predictions]
    sources = [segment.source for segment in predictions]
    return {
        "segments": len(predictions),
        "mean_duration_s": round(statistics.fmean(durations), 3) if durations else 0.0,
        "p95_duration_s": round(_percentile(durations, 0.95), 3),
        "max_duration_s": round(max(durations), 3) if durations else 0.0,
        "segments_over_10s": sum(duration > 10 for duration in durations),
        "segments_over_20s": sum(duration > 20 for duration in durations),
        "replacement_characters": sum(text.count("\ufffd") for text in sources),
        "empty_source_segments": sum(not normalize_zh(text) for text in sources),
    }


def evaluate_episode(
    episode: int,
    prediction_path: Path,
    reference_path: Path,
    dialogue_styles: set[str] | None = None,
    include_songs: bool = False,
) -> dict:
    predictions = load_predictions(prediction_path)
    references = load_fansub(reference_path, dialogue_styles, include_songs)
    alignments, matched_references = align_segments(predictions, references)

    candidate_corpus = " ".join(alignment.candidate for alignment in alignments)
    reference_corpus = " ".join(alignment.reference for alignment in alignments)
    worst = sorted(alignments, key=lambda alignment: (alignment.chrf, alignment.start))[:20]

    return {
        "episode": episode,
        "prediction_path": str(prediction_path),
        "reference_path": str(reference_path),
        "prediction_segments": len(predictions),
        "reference_segments": len(references),
        "aligned_prediction_segments": len(alignments),
        "reference_coverage": round(
            len(matched_references) / len(references) if references else 0.0, 4
        ),
        "corpus_char_f1": round(char_f1(candidate_corpus, reference_corpus), 4),
        "corpus_chrf": round(chrf(candidate_corpus, reference_corpus), 4),
        "corpus_edit_similarity": round(edit_similarity(candidate_corpus, reference_corpus), 4),
        "mean_aligned_chrf": round(
            statistics.fmean(item.chrf for item in alignments) if alignments else 0.0, 4
        ),
        "asr_health": asr_health(predictions),
        "worst_alignments": [asdict(item) for item in worst],
    }


def _discover_prediction_files(root: Path) -> list[Path]:
    direct = sorted(root.glob("*/translated.json"))
    if direct:
        return direct
    return sorted(root.glob("*.json"))


def evaluate_dataset(
    prediction_root: Path,
    reference_root: Path,
    episodes: Iterable[int] | None = None,
    dialogue_styles: set[str] | None = None,
    include_songs: bool = False,
) -> dict:
    requested = list(episodes or range(1, 15))
    prediction_files = _discover_prediction_files(prediction_root)
    prediction_map = {index + 1: path for index, path in enumerate(prediction_files)}
    episode_results = []
    missing = []

    for episode in requested:
        prediction_path = prediction_map.get(episode)
        reference_path = reference_root / f"K-ON! 2009 - EP{episode:02d}.ass"
        if prediction_path is None or not reference_path.exists():
            missing.append(episode)
            continue
        episode_results.append(
            evaluate_episode(
                episode,
                prediction_path,
                reference_path,
                dialogue_styles=dialogue_styles,
                include_songs=include_songs,
            )
        )

    def mean(key: str) -> float:
        values = [float(result[key]) for result in episode_results]
        return round(statistics.fmean(values), 4) if values else 0.0

    aggregate = {
        "episodes": len(episode_results),
        "missing_episodes": missing,
        "mean_reference_coverage": mean("reference_coverage"),
        "mean_corpus_char_f1": mean("corpus_char_f1"),
        "mean_corpus_chrf": mean("corpus_chrf"),
        "mean_corpus_edit_similarity": mean("corpus_edit_similarity"),
        "prediction_segments": sum(item["prediction_segments"] for item in episode_results),
        "reference_segments": sum(item["reference_segments"] for item in episode_results),
        "segments_over_20s": sum(
            item["asr_health"]["segments_over_20s"] for item in episode_results
        ),
        "replacement_characters": sum(
            item["asr_health"]["replacement_characters"] for item in episode_results
        ),
    }
    return {
        "config": {
            "prediction_root": str(prediction_root),
            "reference_root": str(reference_root),
            "dialogue_styles": sorted(dialogue_styles or DEFAULT_DIALOGUE_STYLES),
            "include_songs": include_songs,
        },
        "aggregate": aggregate,
        "episodes": episode_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare generated subtitles with translation-group ASS references"
    )
    parser.add_argument("--prediction-root", type=Path, default=PROJECT_ROOT / "output_clean")
    parser.add_argument("--reference-root", type=Path, default=PROJECT_ROOT / "data" / "S1")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--episodes", type=int, nargs="+")
    parser.add_argument("--reference-styles", type=str, default="")
    parser.add_argument("--include-songs", action="store_true")
    args = parser.parse_args()

    styles = (
        {item.strip().upper() for item in args.reference_styles.split(",") if item.strip()}
        or None
    )
    report = evaluate_dataset(
        args.prediction_root,
        args.reference_root,
        episodes=args.episodes,
        dialogue_styles=styles,
        include_songs=args.include_songs,
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    aggregate = report["aggregate"]
    print("Fansub quality evaluation")
    print(f"  Episodes: {aggregate['episodes']}")
    print(f"  Prediction/reference segments: {aggregate['prediction_segments']}/{aggregate['reference_segments']}")
    print(f"  Reference coverage: {aggregate['mean_reference_coverage']:.2%}")
    print(f"  Corpus chrF: {aggregate['mean_corpus_chrf']:.4f}")
    print(f"  Corpus char-F1: {aggregate['mean_corpus_char_f1']:.4f}")
    print(f"  Segments over 20s: {aggregate['segments_over_20s']}")
    if args.output:
        print(f"  Report: {args.output}")
    return 0 if aggregate["episodes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
