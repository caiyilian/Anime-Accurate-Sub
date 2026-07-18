from pathlib import Path

from scripts.glossary import Glossary
from scripts.series_memory import SeriesMemory, create_k_on_memory


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MEMORY_PATH = PROJECT_ROOT / "data" / "series_memory" / "k-on_s1.json"
GLOSSARY_PATH = PROJECT_ROOT / "data" / "glossary" / "k-on_glossary.json"


def test_production_k_on_memory_has_first_season_cast_and_stable_names():
    memory = create_k_on_memory()

    assert len(memory.data["characters"]) == 9
    assert len(memory.data["terms"]) == 20
    assert memory.get_character("Tsumugi")["full_name_zh"] == "琴吹紬"
    assert memory.get_character("Azusa")["full_name_zh"] == "中野梓"
    assert memory.get_character("Nodoka")["full_name_zh"] == "真锅和"
    assert "䌷" not in memory.to_prompt_block()


def test_series_memory_name_and_term_mappings_match_glossary():
    memory = SeriesMemory(str(MEMORY_PATH))
    glossary = Glossary(str(GLOSSARY_PATH))

    for character in memory.data["characters"].values():
        assert glossary.get(character["full_name_ja"]) == character["full_name_zh"]
        for mapping in character["nicknames"]:
            source, target = mapping.split("→", 1)
            assert glossary.get(source) == target
    for source, term in memory.data["terms"].items():
        assert glossary.get(source) == term["zh"]


def test_prompt_includes_notes_relationships_and_catchphrases():
    memory = SeriesMemory()
    memory.data["series_name"] = "测试系列"
    memory.data["notes"] = "这是系列时间线。"
    memory.add_character(
        "Hero",
        "主人公",
        "主角",
        nicknames=["主人公ちゃん→小主角"],
        speech_style="说话简洁",
        relationships={"Friend": "好友"},
        catchphrases=["やった→太好了"],
    )

    prompt = memory.to_prompt_block()

    assert "系列说明" in prompt and "这是系列时间线" in prompt
    assert "称呼映射" in prompt and "主人公ちゃん→小主角" in prompt
    assert "关系" in prompt and "Friend: 好友" in prompt
    assert "固定说法" in prompt and "やった→太好了" in prompt
