import json
import time

from mnemo.domain.importer import DuplicatePolicy, count_duplicates, parse_import, plan_import
from mnemo.domain.validation import front_key


def doc(cards, **extra):
    return json.dumps({"schema_version": 1, **extra, "cards": cards}, ensure_ascii=False)


def card(i):
    return {"front": f"word{i}", "translations": [f"слово{i}"], "hints": ["h"]}


def test_full_format_and_deck_block():
    r = parse_import(doc([card(1)], deck={"name": "D", "source_language": "en"}))
    assert r.ok and len(r.cards) == 1 and r.errors == []
    assert r.deck.name == "D" and r.deck.source_language == "en"


def test_simplified_root_array():
    r = parse_import(json.dumps([card(1), card(2)]))
    assert r.ok and len(r.cards) == 2 and r.deck is None


def test_unknown_version_rejected():
    r = parse_import(json.dumps({"schema_version": 2, "cards": []}))
    assert not r.ok and "версия" in r.fatal.lower()
    assert not parse_import(json.dumps({"cards": []})).ok
    assert not parse_import(json.dumps({"schema_version": True, "cards": []})).ok


def test_bad_json_gives_readable_error():
    r = parse_import('{"schema_version": 1, "cards": [')
    assert not r.ok and "JSON" in r.fatal and "строка" in r.fatal


def test_three_of_fifty_invalid():
    cards = [card(i) for i in range(50)]
    cards[4]["translations"] = []
    cards[10]["front"] = "  "
    cards[30] = "не объект"
    r = parse_import(doc(cards))
    assert len(r.cards) == 47
    assert [e.number for e in r.errors] == [5, 11, 31]
    assert all(e.message for e in r.errors)


def test_unknown_fields_warn_not_fail():
    c = card(1)
    c["extra"] = 1
    r = parse_import(doc([c]))
    assert len(r.cards) == 1 and r.warnings and "extra" in r.warnings[0]


def test_types_validated():
    r = parse_import(doc([{"front": 5, "translations": ["а"]}, {"front": "a", "translations": [1]}]))
    assert len(r.errors) == 2 and not r.cards


def test_examples_forms():
    r = parse_import(
        doc([{"front": "a", "translations": ["б"], "examples": ["просто", {"text": "t", "translation": "т"}]}])
    )
    ex = r.cards[0].card.examples
    assert [(e.text, e.translation) for e in ex] == [("просто", None), ("t", "т")]


def test_limits():
    assert "много" in parse_import(doc([card(i) for i in range(6)]), max_cards=5).fatal
    assert "большой" in parse_import(doc([card(1)]), max_bytes=10).fatal


def test_duplicate_policies():
    r = parse_import(doc([card(1), card(2), {"front": "WORD1 ", "translations": ["другое"]}]))
    existing = {front_key("word2"): "id2"}
    assert count_duplicates(r, existing) == 2  # word2 в колоде, WORD1 повтор в файле
    skip = plan_import(r, existing, DuplicatePolicy.SKIP)
    assert len(skip.to_add) == 1 and skip.skipped == 2
    add = plan_import(r, existing, DuplicatePolicy.ADD)
    assert len(add.to_add) == 3 and add.skipped == 0
    upd = plan_import(r, existing, DuplicatePolicy.UPDATE)
    assert [i for i, _ in upd.to_update] == ["id2"] and len(upd.to_add) == 1 and upd.skipped == 1


def test_200_cards_fast():
    t = time.perf_counter()
    r = parse_import(doc([card(i) for i in range(200)]))
    assert len(r.cards) == 200 and time.perf_counter() - t < 2
