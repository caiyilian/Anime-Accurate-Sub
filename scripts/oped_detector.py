"""Detect and remove opening/ending theme ranges before subtitle translation.

The detector uses AnimeThemes metadata plus normalized audio correlation. Theme
videos are cached under ``.omo/oped_cache`` so only the first run needs network
access. Explicit ranges remain available for offline or unusual releases.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = PROJECT_ROOT / ".omo" / "oped_cache"
API_BASE = "https://api.animethemes.moe"
API_HEADERS = {"User-Agent": "Anime-Accurate-Sub/1.0"}


@dataclass(frozen=True)
class ThemeReference:
    kind: str
    title: str
    url: str
    episodes: frozenset[int]
    sequence: int = 1


@dataclass(frozen=True)
class OPEDRange:
    kind: str
    start: float
    end: float
    score: float = 1.0
    source: str = "audio-correlation"

    def to_dict(self) -> dict:
        return asdict(self)


def parse_episode_set(value: str | None) -> frozenset[int]:
    """Parse AnimeThemes episode declarations such as ``1-3, 5``."""
    episodes: set[int] = set()
    for item in re.split(r"[,，]", value or ""):
        item = item.strip()
        if not item:
            continue
        range_match = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", item)
        if range_match:
            start, end = map(int, range_match.groups())
            episodes.update(range(start, end + 1))
            continue
        open_match = re.fullmatch(r"(\d+)\s*[-–]", item)
        if open_match:
            episodes.update(range(int(open_match.group(1)), 1000))
            continue
        if item.isdigit():
            episodes.add(int(item))
    return frozenset(episodes)


def infer_episode_number(path: str | Path) -> int | None:
    """Infer an episode number from common ``EP01`` or Chinese file names."""
    stem = Path(path).stem
    patterns = (
        r"(?:ep|episode|e)[\s._-]*0*(\d{1,3})(?!\d)",
        r"第\s*0*(\d{1,3})\s*[集话話]",
        r"(?:^|[^\d])0*(\d{1,3})(?:v\d+)?(?:[^\d]|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, stem, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def parse_explicit_ranges(values: Iterable[str]) -> list[OPEDRange]:
    """Parse repeated values like ``op:115.1-204.9``."""
    result = []
    for value in values:
        match = re.fullmatch(
            r"\s*(op|ed)\s*:\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*",
            value,
            flags=re.IGNORECASE,
        )
        if not match:
            raise ValueError(
                f"Invalid OP/ED range {value!r}; expected op:START-END or ed:START-END"
            )
        kind, start, end = match.groups()
        if float(end) <= float(start):
            raise ValueError(f"OP/ED range end must be after start: {value!r}")
        result.append(
            OPEDRange(
                kind=kind.upper(),
                start=float(start),
                end=float(end),
                source="explicit",
            )
        )
    return sorted(result, key=lambda item: item.start)


def _request_json(url: str, timeout: int = 60) -> dict:
    last_error = None
    for attempt in range(4):
        request = urllib.request.Request(url, headers=API_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as error:
            last_error = error
            if attempt < 3:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"AnimeThemes API failed after 4 attempts: {last_error}")


def _cache_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _cached_json(path: Path, fetch) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return data


def resolve_anime_slug(series_name: str, cache_dir: str | Path = DEFAULT_CACHE_DIR) -> str:
    cache = Path(cache_dir)
    query = urllib.parse.quote(series_name)
    url = f"{API_BASE}/anime?q={query}&fields[anime]=name,slug,year&page[size]=10"
    data = _cached_json(cache / f"search-{_cache_key(series_name)}.json", lambda: _request_json(url))
    candidates = data.get("anime", [])
    if not candidates:
        raise RuntimeError(f"AnimeThemes returned no series for {series_name!r}")
    exact = [
        item
        for item in candidates
        if str(item.get("name", "")).casefold() == series_name.casefold()
    ]
    selected = (exact or candidates)[0]
    slug = selected.get("slug")
    if not slug:
        raise RuntimeError(f"AnimeThemes result has no slug for {series_name!r}")
    return str(slug)


def fetch_theme_references(
    series_name: str,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
) -> list[ThemeReference]:
    cache = Path(cache_dir)
    slug = resolve_anime_slug(series_name, cache)
    url = (
        f"{API_BASE}/anime/{slug}"
        "?include=animethemes.animethemeentries.videos,animethemes.song"
        "&fields[animetheme]=type,sequence"
        "&fields[animethemeentry]=episodes,version"
        "&fields[video]=link"
        "&fields[song]=title"
    )
    data = _cached_json(cache / f"themes-{slug}.json", lambda: _request_json(url))
    references = []
    for theme in data.get("anime", {}).get("animethemes", []):
        kind = str(theme.get("type", "")).upper()
        if kind not in {"OP", "ED"}:
            continue
        sequence = int(theme.get("sequence") or 1)
        title = str((theme.get("song") or {}).get("title") or kind)
        for entry in theme.get("animethemeentries", []):
            videos = entry.get("videos") or []
            if not videos or not videos[0].get("link"):
                continue
            references.append(
                ThemeReference(
                    kind=kind,
                    title=title,
                    url=str(videos[0]["link"]),
                    episodes=parse_episode_set(entry.get("episodes")),
                    sequence=sequence,
                )
            )
    if not references:
        raise RuntimeError(f"AnimeThemes returned no OP/ED videos for {series_name!r}")
    return references


def select_theme(
    references: Sequence[ThemeReference], kind: str, episode: int | None
) -> ThemeReference | None:
    candidates = [item for item in references if item.kind == kind.upper()]
    if not candidates:
        return None
    if episode is None:
        return candidates[0]
    exact = [item for item in candidates if episode in item.episodes]
    if exact:
        return max(exact, key=lambda item: item.sequence)
    unrestricted = [item for item in candidates if not item.episodes]
    if unrestricted:
        return max(unrestricted, key=lambda item: item.sequence)
    eligible = [
        item for item in candidates if item.episodes and min(item.episodes) <= episode
    ]
    if eligible:
        return max(eligible, key=lambda item: (min(item.episodes), item.sequence))
    return candidates[0]


def download_theme(reference: ThemeReference, cache_dir: str | Path) -> Path:
    cache = Path(cache_dir) / "media"
    cache.mkdir(parents=True, exist_ok=True)
    suffix = Path(urllib.parse.urlparse(reference.url).path).suffix or ".webm"
    destination = cache / f"{_cache_key(reference.url)}{suffix}"
    if destination.exists() and destination.stat().st_size > 10_000:
        return destination
    temporary = destination.with_suffix(destination.suffix + ".part")
    last_error = None
    for attempt in range(4):
        request = urllib.request.Request(reference.url, headers=API_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            break
        except Exception as error:
            last_error = error
            temporary.unlink(missing_ok=True)
            if attempt < 3:
                time.sleep(2 ** attempt)
    else:
        curl = shutil.which("curl") or shutil.which("curl.exe")
        if not curl:
            raise RuntimeError(
                f"Theme download failed after 4 attempts: {last_error}"
            )
        command = [
            curl,
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--retry",
            "4",
            "--retry-delay",
            "2",
            "--retry-all-errors",
            "--user-agent",
            API_HEADERS["User-Agent"],
            "--output",
            str(temporary),
            reference.url,
        ]
        subprocess.run(command, timeout=600, check=True)
    if temporary.stat().st_size <= 10_000:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded theme is unexpectedly small: {reference.url}")
    temporary.replace(destination)
    return destination


def _probe_duration(path: str | Path) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=True)
    return float(result.stdout.strip())


def _decode_audio(
    path: str | Path,
    start: float = 0.0,
    duration: float | None = None,
    sample_rate: int = 8000,
):
    import numpy as np

    command = ["ffmpeg", "-v", "error"]
    if start > 0:
        command += ["-ss", f"{start:.3f}"]
    command += ["-i", str(path)]
    if duration is not None:
        command += ["-t", f"{duration:.3f}"]
    command += ["-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "pipe:1"]
    result = subprocess.run(command, capture_output=True, timeout=300, check=True)
    return np.frombuffer(result.stdout, dtype=np.float32).copy()


def normalized_match(episode_audio, theme_audio) -> tuple[int, float]:
    """Return the best normalized-correlation sample index and score."""
    import numpy as np
    from scipy import signal

    episode = np.asarray(episode_audio, dtype=np.float64)
    theme = np.asarray(theme_audio, dtype=np.float64)
    if len(theme) < 10 or len(episode) < len(theme):
        raise ValueError("Episode audio must be longer than the theme portion")
    episode -= float(episode.mean())
    theme -= float(theme.mean())
    theme_norm = float(np.linalg.norm(theme))
    if theme_norm <= 1e-12:
        raise ValueError("Theme audio has no usable energy")
    correlation = signal.correlate(episode, theme, mode="valid", method="fft")
    squared = np.concatenate(([0.0], np.cumsum(episode * episode)))
    window_energy = np.sqrt(np.maximum(squared[len(theme):] - squared[:-len(theme)], 1e-12))
    scores = correlation / (theme_norm * window_energy)
    index = int(np.argmax(scores))
    return index, float(scores[index])


def match_theme(
    video_path: str | Path,
    theme_path: str | Path,
    search_start: float,
    search_end: float,
    *,
    sample_rate: int = 8000,
    downsample: int = 8,
    theme_portion: float = 0.8,
) -> tuple[float, float, float]:
    """Return ``(theme_start, theme_duration, score)`` in seconds."""
    episode = _decode_audio(
        video_path,
        start=search_start,
        duration=max(1.0, search_end - search_start),
        sample_rate=sample_rate,
    )
    theme = _decode_audio(theme_path, sample_rate=sample_rate)
    theme_duration = len(theme) / sample_rate
    margin = max(0, int(len(theme) * (1.0 - theme_portion) / 2.0))
    portion = theme[margin:len(theme) - margin if margin else len(theme)]
    episode_small = episode[::downsample]
    portion_small = portion[::downsample]
    index, score = normalized_match(episode_small, portion_small)
    match_rate = sample_rate / downsample
    start = search_start + index / match_rate - margin / sample_rate
    return max(0.0, start), theme_duration, score


def detect_oped(
    video_path: str | Path,
    series_name: str,
    episode: int | None = None,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    min_score: float = 0.18,
) -> list[OPEDRange]:
    """Detect OP and ED intervals using cached AnimeThemes references."""
    video_path = Path(video_path)
    episode = episode if episode is not None else infer_episode_number(video_path)
    references = fetch_theme_references(series_name, cache_dir)
    video_duration = _probe_duration(video_path)
    result = []
    for kind in ("OP", "ED"):
        reference = select_theme(references, kind, episode)
        if reference is None:
            continue
        theme_path = download_theme(reference, cache_dir)
        if kind == "OP":
            search_start, search_end = 0.0, min(video_duration, 600.0)
        else:
            search_start, search_end = max(0.0, video_duration - 600.0), video_duration
        start, duration, score = match_theme(
            video_path, theme_path, search_start, search_end
        )
        if score < min_score:
            print(
                f"  Warning: {kind} correlation score {score:.3f} is below {min_score:.3f}"
            )
            continue
        result.append(
            OPEDRange(
                kind=kind,
                start=round(start, 3),
                end=round(min(video_duration, start + duration), 3),
                score=round(score, 4),
            )
        )
    return sorted(result, key=lambda item: item.start)


def filter_segments(
    segments: Sequence[dict], ranges: Sequence[OPEDRange]
) -> tuple[list[dict], list[dict]]:
    """Remove segments whose midpoint falls inside an OP/ED range."""
    kept, removed = [], []
    for segment in segments:
        midpoint = (float(segment["start"]) + float(segment["end"])) / 2.0
        match = next(
            (item for item in ranges if item.start <= midpoint <= item.end), None
        )
        if match:
            removed.append({**segment, "oped_kind": match.kind})
        else:
            kept.append(segment)
    return kept, removed
