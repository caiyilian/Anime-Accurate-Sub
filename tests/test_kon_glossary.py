from pathlib import Path

from scripts.glossary import Glossary
from scripts.translation_engine import PipelineTranslator


PROJECT_ROOT = Path(__file__).resolve().parent.parent
GLOSSARY_PATH = PROJECT_ROOT / "data" / "glossary" / "k-on_glossary.json"


def test_kon_glossary_normalizes_common_asr_name_spellings():
    glossary = Glossary(str(GLOSSARY_PATH))

    assert glossary.get("結衣") == "唯"
    assert glossary.get("ゆい") == "唯"
    assert glossary.get("ユイ") == "唯"
    assert glossary.get("美桜") == "澪"
    assert glossary.get("ミヨ") == "澪"
    assert glossary.get("タイナカ") == "田井中"
    assert glossary.get("リツ") == "律"
    assert glossary.get("のどか") == "和"
    assert glossary.get("ムギ") == "小紬"
    assert glossary.get("あずさ") == "梓"
    assert glossary.get("あずにゃん") == "梓喵"
    assert glossary.get("うい") == "忧"
    assert glossary.get("純ちゃん") == "小纯"
    assert glossary.get("さわちゃん") == "小佐和"


def test_kon_glossary_uses_stable_names_and_has_no_duplicate_sources():
    glossary = Glossary(str(GLOSSARY_PATH))
    sources = [source for source, _ in glossary.terms]

    assert glossary.get("琴吹紬") == "琴吹紬"
    assert glossary.get("紬") == "紬"
    assert glossary.get("中野梓") == "中野梓"
    assert glossary.get("放課後ティータイム") == "放学后茶会"
    assert glossary.get("ギー太") == "吉太"
    assert len(sources) == len(set(sources))


def test_only_aliases_present_in_the_batch_are_injected():
    glossary = Glossary(str(GLOSSARY_PATH))
    engine = PipelineTranslator(adapter=object(), glossary=glossary)

    terms = engine._matching_glossary_terms(
        ["もしかして、あなたが平沢結衣さん?", "こっちはベースの秋山美桜"]
    )

    assert ("平沢", "平泽") in terms
    assert ("結衣", "唯") in terms
    assert ("秋山", "秋山") in terms
    assert ("美桜", "澪") in terms
    assert ("タイナカ", "田井中") not in terms
