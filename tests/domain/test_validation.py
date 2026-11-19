import pytest

from mnemo.domain.models import Card, Example
from mnemo.domain.validation import (
    ValidationError,
    clean_card_fields,
    clean_deck_name,
    find_duplicates,
)


def test_empty_front_rejected():
    with pytest.raises(ValidationError) as e:
        clean_card_fields("  ", ["a"])
    assert e.value.problems


def test_empty_translations_rejected():
    with pytest.raises(ValidationError):
        clean_card_fields("word", ["", "  ", None])


def test_blank_items_dropped():
    c = clean_card_fields(" w ", [" а ", ""], [Example(" ex ", " "), Example("", "x")], ["", "h"], [" t "])
    assert c.front == "w"
    assert c.translations == ["а"]
    assert c.examples == [Example("ex", None)]
    assert c.hints == ["h"]
    assert c.tags == ["t"]


def test_limits():
    with pytest.raises(ValidationError):
        clean_card_fields("x" * 501, ["a"])
    with pytest.raises(ValidationError):
        clean_card_fields("x", [str(i) for i in range(11)])
    with pytest.raises(ValidationError):
        clean_card_fields("x", ["a"], hints=[str(i) for i in range(6)])
    with pytest.raises(ValidationError):
        clean_card_fields("x", ["a"], examples=[Example(str(i)) for i in range(11)])


def test_all_problems_reported_together():
    with pytest.raises(ValidationError) as e:
        clean_card_fields("", [])
    assert len(e.value.problems) == 2


def test_deck_name():
    assert clean_deck_name("  Моя  ") == "Моя"
    with pytest.raises(ValidationError):
        clean_deck_name(" ")
    with pytest.raises(ValidationError):
        clean_deck_name("x" * 101)


def test_duplicates_ignore_case_and_spaces():
    existing = [Card("d", "To  Give up", ["a"]), Card("d", "other", ["b"])]
    assert len(find_duplicates("to give UP ", existing)) == 1
    assert find_duplicates("to give UP", existing, exclude_id=existing[0].id) == []
