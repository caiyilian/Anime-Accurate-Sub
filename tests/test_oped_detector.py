import numpy as np

from scripts.oped_detector import (
    OPEDRange,
    ThemeReference,
    filter_segments,
    infer_episode_number,
    normalized_match,
    parse_episode_set,
    parse_explicit_ranges,
    select_theme,
)


def test_parse_episode_set_and_file_name_inference():
    assert parse_episode_set("1-3, 5, 7-9") == frozenset({1, 2, 3, 5, 7, 8, 9})
    assert infer_episode_number("K-ON! - EP02.mkv") == 2
    assert infer_episode_number("anime_\u7b2c14\u96c6.mp4") == 14


def test_select_theme_prefers_episode_specific_variant():
    references = [
        ThemeReference("OP", "first", "https://example/op1", frozenset(range(1, 9)), 1),
        ThemeReference("OP", "second", "https://example/op2", frozenset(range(9, 13)), 2),
        ThemeReference("ED", "ending", "https://example/ed", frozenset(), 1),
    ]
    assert select_theme(references, "OP", 2).title == "first"
    assert select_theme(references, "OP", 10).title == "second"
    # Extra episodes use the latest theme whose declared range already started.
    assert select_theme(references, "OP", 14).title == "second"
    assert select_theme(references, "ED", 14).title == "ending"


def test_normalized_match_finds_inserted_theme():
    random = np.random.default_rng(7)
    theme = random.normal(0, 1, 400)
    episode = random.normal(0, 0.03, 3000)
    episode[1234:1634] += theme * 0.8
    index, score = normalized_match(episode, theme)
    assert abs(index - 1234) <= 1
    assert score > 0.99


def test_explicit_ranges_and_segment_filtering():
    ranges = parse_explicit_ranges(["op:10.5-20", "ED:80-90.25"])
    assert ranges == [
        OPEDRange("OP", 10.5, 20.0, source="explicit"),
        OPEDRange("ED", 80.0, 90.25, source="explicit"),
    ]
    segments = [
        {"start": 9.0, "end": 10.0, "text": "before"},
        {"start": 11.0, "end": 12.0, "text": "opening"},
        {"start": 50.0, "end": 51.0, "text": "dialogue"},
        {"start": 89.0, "end": 91.0, "text": "ending"},
    ]
    kept, removed = filter_segments(segments, ranges)
    assert [item["text"] for item in kept] == ["before", "dialogue"]
    assert [(item["text"], item["oped_kind"]) for item in removed] == [
        ("opening", "OP"),
        ("ending", "ED"),
    ]


def test_invalid_explicit_range_is_rejected():
    try:
        parse_explicit_ranges(["op:20-10"])
    except ValueError as error:
        assert "end must be after start" in str(error)
    else:
        raise AssertionError("invalid range should fail")
