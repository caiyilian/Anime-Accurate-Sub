"""Reliable long-form Anime Whisper inference and subtitle-safe segmentation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PREFERRED_MODEL_DIR = PROJECT_ROOT / ".omo" / "efwkjn-anime-whisper"
SENTENCE_ENDINGS = ("。", "!", "！", "?", "？", "…")


@dataclass(frozen=True)
class TimedWord:
    start: float
    end: float
    text: str
    probability: float | None = None


@dataclass(frozen=True)
class ASRSettings:
    beam_size: int = 5
    repetition_penalty: float = 1.05
    no_repeat_ngram_size: int = 5
    max_chars: int = 32
    max_duration_s: float = 6.0
    pause_split_s: float = 0.65
    min_duration_s: float = 0.35
    hallucination_silence_threshold_s: float = 2.0


def resolve_model_path(explicit_path: str | Path | None = None) -> Path:
    """Select a CT2 model that supports stable word timestamps.

    The original ``anime-whisper-ct2`` conversion in this workspace produces
    corrupted long-form timestamps and crashes when word timestamps are enabled.
    ``efwkjn-anime-whisper`` contains a compatible CT2 model and is preferred.
    """
    candidates = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    if os.environ.get("ANIME_WHISPER_MODEL"):
        candidates.append(Path(os.environ["ANIME_WHISPER_MODEL"]))
    candidates.append(PREFERRED_MODEL_DIR)
    for candidate in candidates:
        if (candidate / "model.bin").exists() and (candidate / "tokenizer.json").exists():
            return candidate.resolve()
    raise FileNotFoundError(
        "No usable Anime Whisper CT2 model found. Expected "
        f"{PREFERRED_MODEL_DIR} or set ANIME_WHISPER_MODEL."
    )


def _visible_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def _join_words(words: Sequence[TimedWord]) -> str:
    # Faster Whisper already includes leading spaces for languages that need them.
    return "".join(word.text for word in words).strip()


def collapse_phrase_repetitions(text: str, max_keep: int = 2) -> str:
    """Cap obvious ASR phrase loops while preserving normal emphatic repeats.

    Four or more consecutive copies of a 2-12 character phrase are a common
    Whisper hallucination. Three repetitions (for example ``でもでもでも``)
    and single-character screams remain untouched.
    """
    pattern = re.compile(r"(.{2,12}?)\1{3,}")

    def replace(match: re.Match) -> str:
        phrase = match.group(1)
        if len(set(phrase)) == 1:
            return match.group(0)
        return phrase * max_keep

    previous = None
    while text != previous:
        previous = text
        text = pattern.sub(replace, text)
    return text


def _make_segment(
    words: Sequence[TimedWord], min_duration_s: float, max_duration_s: float
) -> dict:
    start = float(words[0].start)
    end = min(
        max(float(words[-1].end), start + min_duration_s),
        start + max_duration_s,
    )
    probabilities = [word.probability for word in words if word.probability is not None]
    result = {
        "start": round(start, 2),
        "end": round(end, 2),
        "text": collapse_phrase_repetitions(_join_words(words)),
    }
    if probabilities:
        result["confidence"] = round(sum(probabilities) / len(probabilities), 4)
    return result


def segment_timed_words(
    words: Iterable[TimedWord],
    settings: ASRSettings | None = None,
) -> list[dict]:
    """Split word timestamps into readable subtitle-sized Japanese segments."""
    settings = settings or ASRSettings()
    ordered = sorted(words, key=lambda word: (word.start, word.end))
    if not ordered:
        return []

    groups: list[list[TimedWord]] = []
    current: list[TimedWord] = []

    for index, word in enumerate(ordered):
        if not word.text or word.end <= word.start:
            continue
        current.append(word)
        next_word = ordered[index + 1] if index + 1 < len(ordered) else None
        text = _join_words(current)
        duration = current[-1].end - current[0].start
        pause_after = (
            max(0.0, next_word.start - word.end) if next_word is not None else float("inf")
        )
        sentence_end = text.endswith(SENTENCE_ENDINGS) and duration >= settings.min_duration_s
        should_split = (
            next_word is None
            or pause_after >= settings.pause_split_s
            or duration >= settings.max_duration_s
            or _visible_length(text) >= settings.max_chars
            or sentence_end
        )
        if should_split:
            groups.append(current)
            current = []

    if current:
        groups.append(current)

    # Merge isolated punctuation or one-character fragments into a nearby cue.
    merged: list[list[TimedWord]] = []
    for group in groups:
        text = _join_words(group)
        duration = group[-1].end - group[0].start
        if merged and (
            _visible_length(text) <= 1 or duration < settings.min_duration_s
        ):
            previous = merged[-1]
            combined_duration = group[-1].end - previous[0].start
            combined_text = _join_words([*previous, *group])
            gap = group[0].start - previous[-1].end
            if (
                gap <= settings.pause_split_s
                and combined_duration <= settings.max_duration_s
                and _visible_length(combined_text) <= settings.max_chars
            ):
                previous.extend(group)
                continue
        merged.append(group)

    return [
        _make_segment(group, settings.min_duration_s, settings.max_duration_s)
        for group in merged
        if _join_words(group)
    ]


class AnimeWhisperASR:
    """Lazy GPU-backed Anime Whisper engine reusable across a batch."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        settings: ASRSettings | None = None,
        device: str = "cuda",
        compute_type: str = "int8_float16",
    ):
        self.model_path = resolve_model_path(model_path)
        self.settings = settings or ASRSettings()
        self.device = device
        self.compute_type = compute_type
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                str(self.model_path),
                device=self.device,
                compute_type=self.compute_type,
                num_workers=1,
            )
        return self._model

    def transcribe(self, audio_path: str | Path) -> list[dict]:
        segments, _ = self.model.transcribe(
            str(audio_path),
            language="ja",
            beam_size=self.settings.beam_size,
            vad_filter=False,
            condition_on_previous_text=False,
            no_repeat_ngram_size=self.settings.no_repeat_ngram_size,
            repetition_penalty=self.settings.repetition_penalty,
            word_timestamps=True,
            hallucination_silence_threshold=(
                self.settings.hallucination_silence_threshold_s
            ),
        )

        words = []
        fallbacks = []
        for segment in segments:
            if segment.words:
                for word in segment.words:
                    words.append(
                        TimedWord(
                            start=float(word.start),
                            end=float(word.end),
                            text=word.word,
                            probability=(
                                float(word.probability)
                                if word.probability is not None
                                else None
                            ),
                        )
                    )
            elif segment.text.strip() and segment.end > segment.start:
                fallbacks.append(
                    {
                        "start": round(float(segment.start), 2),
                        "end": round(float(segment.end), 2),
                        "text": segment.text.strip(),
                    }
                )

        result = segment_timed_words(words, self.settings)
        result.extend(fallbacks)
        result.sort(key=lambda item: (item["start"], item["end"]))
        self._validate(result)
        return result

    @staticmethod
    def _validate(segments: Sequence[dict]) -> None:
        if not segments:
            raise RuntimeError("Anime Whisper produced no subtitle segments")
        replacement_characters = sum(item["text"].count("\ufffd") for item in segments)
        if replacement_characters:
            raise RuntimeError(
                "Anime Whisper produced corrupted replacement characters: "
                f"{replacement_characters}"
            )
        long_segments = [
            item for item in segments if float(item["end"]) - float(item["start"]) > 10
        ]
        if long_segments:
            raise RuntimeError(
                f"Anime Whisper segmentation produced {len(long_segments)} segments over 10 seconds"
            )
