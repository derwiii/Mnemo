from datetime import timedelta

import pytest

from mnemo.domain.models import CardStatus, Example, utcnow
from mnemo.domain.validation import ValidationError
from mnemo.services import DisplayStatus, Library
from mnemo.storage import Database, DuplicateDeckNameError


@pytest.fixture
def lib():
    library = Library(Database(":memory:"))
    yield library
    library.close()


def test_deck_lifecycle_and_summaries(lib):
    d = lib.create_deck("  Англ  ", "desc", "en", "ru")
    lib.save_card(d.id, "a", ["б"])
    lib.save_card(d.id, "c", ["д"])
    (s,) = lib.deck_summaries()
    assert (s.deck.name, s.card_count, s.due_count) == ("Англ", 2, 2)
    assert lib.due_totals() == (2, 1)
    lib.update_deck(d.id, "Новое имя", "x")
    assert lib.deck_summary(d.id).deck.name == "Новое имя"
    assert lib.deck_summary(d.id).deck.source_language == "en"
    lib.delete_deck(d.id)
    assert lib.deck_summaries() == []


def test_duplicate_and_empty_deck_name(lib):
    lib.create_deck("A")
    with pytest.raises(DuplicateDeckNameError):
        lib.create_deck("a")
    with pytest.raises(ValidationError):
        lib.create_deck("  ")
    other = lib.create_deck("B")
    with pytest.raises(DuplicateDeckNameError):
        lib.update_deck(other.id, "A")


def test_save_card_validation_fields(lib):
    d = lib.create_deck("A")
    with pytest.raises(ValidationError) as e:
        lib.save_card(d.id, "", [" "])
    assert set(e.value.fields) == {"front", "translations"}


def test_add_translation_preserves_fields_progress_and_journal(lib):
    deck = lib.create_deck("Test")
    card = lib.save_card(deck.id, "look good", ["хорошо выглядеть"],
                         [Example("example", "пример")], ["hint"], ["tag"])
    before = lib.states.get(card.id)
    updated = lib.add_translation(card.id, "  неплохо смотреться  ")
    assert updated.translations == ["хорошо выглядеть", "неплохо смотреться"]
    stored = lib.cards.get(card.id)
    assert stored.examples == card.examples
    assert stored.hints == card.hints and stored.tags == card.tags
    assert lib.states.get(card.id) == before
    assert lib.reviews.count() == 0


def test_add_translation_rejects_empty_duplicate_and_limit(lib):
    deck = lib.create_deck("Test")
    card = lib.save_card(deck.id, "hedgehog", ["ёжик"])
    for value in ("", "?!", "  ЕЖИК! "):
        with pytest.raises(ValidationError):
            lib.add_translation(card.id, value)
        assert lib.cards.get(card.id).translations == ["ёжик"]
    for i in range(9):
        lib.add_translation(card.id, f"вариант {i}")
    with pytest.raises(ValidationError):
        lib.add_translation(card.id, "одиннадцатый")
    assert len(lib.cards.get(card.id).translations) == 10


def test_add_translation_failure_leaves_database_unchanged(lib, monkeypatch):
    from mnemo.storage import StorageError
    deck = lib.create_deck("Test")
    card = lib.save_card(deck.id, "a", ["б"])
    def fail(card):
        raise StorageError("write failed")
    monkeypatch.setattr(lib.cards, "update", fail)
    with pytest.raises(StorageError):
        lib.add_translation(card.id, "в")
    assert lib.cards.get(card.id).translations == ["б"]
    assert lib.reviews.count() == 0


def test_edit_keeps_progress(lib):
    d = lib.create_deck("A")
    c = lib.save_card(d.id, "a", ["б"], [Example("ex", "пр")], ["h"])
    st = lib.states.get(c.id)
    st.status, st.interval_days, st.reps = CardStatus.REVIEW, 30.0, 5
    lib.states.save(st)
    c2 = lib.save_card(d.id, "a2", ["в", "г"], card_id=c.id)
    assert c2.id == c.id and c2.translations == ["в", "г"] and c2.examples == []
    assert lib.states.get(c.id).reps == 5
    (row,) = lib.list_cards(d.id)
    assert row.status is DisplayStatus.LEARNED


def test_display_status_rules(lib):
    from mnemo.services import display_status
    from mnemo.domain.models import CardState

    assert display_status(None) is DisplayStatus.NEW
    assert display_status(CardState("x", CardStatus.LEARNING)) is DisplayStatus.LEARNING
    assert display_status(CardState("x", CardStatus.REVIEW, interval_days=20.9)) is DisplayStatus.LEARNING
    assert display_status(CardState("x", CardStatus.REVIEW, interval_days=21)) is DisplayStatus.LEARNED


def test_duplicates_and_search(lib):
    d = lib.create_deck("A")
    c = lib.save_card(d.id, "To Go", ["идти"])
    assert lib.find_duplicates(d.id, " to  go ")
    assert lib.find_duplicates(d.id, "to go", exclude_id=c.id) == []
    assert [r.card.front for r in lib.list_cards(d.id, "ИДТ")] == ["To Go"]
    assert lib.list_cards(d.id, "zzz") == []


def test_due_logic(lib):
    d = lib.create_deck("A")
    c1 = lib.save_card(d.id, "a", ["б"])
    c2 = lib.save_card(d.id, "c", ["д"])
    st = lib.states.get(c2.id)
    st.status, st.due_at = CardStatus.REVIEW, utcnow() + timedelta(days=3)
    lib.states.save(st)
    assert [c.id for c in lib.due_cards(d.id)] == [c1.id]
    assert lib.deck_summary(d.id).due_count == 1
    assert lib.due_totals() == (1, 1)
    assert len(lib.due_cards(None, utcnow() + timedelta(days=4))) == 2
    lib.delete_card(c1.id)
    assert lib.due_totals() == (0, 0)


# ---------------- импорт и экспорт ----------------

import json  # noqa: E402

from mnemo.domain.importer import DeckInfo, DuplicatePolicy, parse_import  # noqa: E402
from mnemo.services import ImportFileError, read_import_file  # noqa: E402


def _doc(n, start=0):
    cards = [{"front": f"w{i}", "translations": [f"т{i}"]} for i in range(start, start + n)]
    return json.dumps({"schema_version": 1, "cards": cards}, ensure_ascii=False)


def test_import_into_new_deck_and_repeat_skips(lib):
    parse = parse_import(_doc(200))
    report = lib.apply_import(parse, DuplicatePolicy.SKIP, new_deck=DeckInfo("Импорт", "", "en", "ru"))
    assert report.added == 200
    deck_id = report.deck_id
    assert lib.deck_summary(deck_id).card_count == 200
    assert all(lib.states.get(r.card.id).status is CardStatus.NEW for r in lib.list_cards(deck_id)[:5])
    again = lib.apply_import(parse, DuplicatePolicy.SKIP, deck_id=deck_id)
    assert (again.added, again.skipped) == (0, 200)
    assert lib.deck_summary(deck_id).card_count == 200
    assert lib.preview_import(parse, deck_id).duplicates == 200
    assert lib.preview_import(parse, None).duplicates == 0


def test_import_add_and_update_policies(lib):
    d = lib.create_deck("A")
    lib.save_card(d.id, "w0", ["старый"], hints=["x"])
    parse = parse_import(_doc(2))
    r = lib.apply_import(parse, DuplicatePolicy.ADD, deck_id=d.id)
    assert (r.added, r.skipped) == (2, 0) and lib.cards.count_by_deck(d.id) == 3
    d2 = lib.create_deck("B")
    existing = lib.save_card(d2.id, "w0", ["старый"])
    st = lib.states.get(existing.id)
    st.reps = 7
    lib.states.save(st)
    r = lib.apply_import(parse, DuplicatePolicy.UPDATE, deck_id=d2.id)
    assert (r.added, r.updated) == (1, 1)
    assert lib.cards.get(existing.id).translations == ["т0"]
    assert lib.states.get(existing.id).reps == 7


def test_import_error_records_do_not_block(lib):
    cards = [{"front": f"w{i}", "translations": ["т"]} for i in range(50)]
    for i in (3, 20, 40):
        cards[i]["translations"] = []
    parse = parse_import(json.dumps({"schema_version": 1, "cards": cards}))
    r = lib.apply_import(parse, DuplicatePolicy.SKIP, new_deck=DeckInfo("X"))
    assert (r.added, r.errors) == (47, 3)


def test_import_is_atomic_when_deck_name_taken(lib):
    lib.create_deck("Занято")
    with pytest.raises(DuplicateDeckNameError):
        lib.apply_import(parse_import(_doc(3)), DuplicatePolicy.SKIP, new_deck=DeckInfo("занято"))
    assert len(lib.deck_summaries()) == 1 and lib.cards.counts_by_deck() == {}


def test_import_rolls_back_on_failure(lib, monkeypatch):
    d = lib.create_deck("A")
    calls = {"n": 0}
    real_add = lib.cards.add

    def flaky(card):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("сбой")
        return real_add(card)

    monkeypatch.setattr(lib.cards, "add", flaky)
    with pytest.raises(RuntimeError):
        lib.apply_import(parse_import(_doc(5)), DuplicatePolicy.SKIP, deck_id=d.id)
    assert lib.cards.count_by_deck(d.id) == 0


def test_export_then_import_roundtrip(lib):
    d = lib.create_deck("Исходная", "описание", "en", "ru")
    lib.save_card(
        d.id, "to give up", ["сдаваться", "бросать (привычку)"],
        [Example("Don't give up.", "Не сдавайся."), Example("Only text")], ["h1", "h2"], ["tag"],
    )
    lib.save_card(d.id, "ёж", ["hedgehog"])
    text = lib.export_deck(d.id)
    assert json.loads(text)["schema_version"] == 1
    parse = parse_import(text)
    assert parse.ok and not parse.errors and parse.deck.name == "Исходная"
    report = lib.apply_import(parse, DuplicatePolicy.SKIP, new_deck=DeckInfo("Копия", "", "en", "ru"))
    a = [r.card for r in lib.list_cards(d.id)]
    b = [r.card for r in lib.list_cards(report.deck_id)]
    key = lambda c: (c.front, c.translations, c.examples, c.hints, c.tags)  # noqa: E731
    assert [key(c) for c in a] == [key(c) for c in b]


def test_read_import_file(tmp_path):
    p = tmp_path / "a.json"
    p.write_bytes("﻿[]".encode("utf-8"))
    assert read_import_file(p) == "[]"
    p.write_bytes("привет".encode("cp1251"))
    with pytest.raises(ImportFileError):
        read_import_file(p)
    with pytest.raises(ImportFileError):
        read_import_file(tmp_path / "нет.json")


# ---------------- очередь сессии и дневные лимиты ----------------

import random  # noqa: E402

from mnemo.domain.models import AnswerMode, Grade, ReviewLog  # noqa: E402
from mnemo.services import local_day_start  # noqa: E402


def test_session_queue_respects_daily_new_limit(lib):
    lib.new_limit = 20
    d = lib.create_deck("A")
    for i in range(30):
        lib.save_card(d.id, f"w{i}", ["т"])
    q = lib.session_queue(d.id, rng=random.Random(1))
    assert len(q) == 20  # дневной лимит новых
    # 5 карточек начаты сегодня: лимит уменьшается
    for card in q[:5]:
        lib.reviews.add(ReviewLog(card.id, Grade.GOOD, AnswerMode.SELF))
        st = lib.states.get(card.id)
        st.status = CardStatus.REVIEW
        st.due_at = utcnow() + timedelta(days=1)
        lib.states.save(st)
    assert len(lib.session_queue(d.id, rng=random.Random(1))) == 15
    assert lib.reviews.daily_counts(local_day_start(utcnow())) == (5, 0)


def test_session_queue_all_decks_and_empty(lib):
    a, b = lib.create_deck("A"), lib.create_deck("B")
    lib.save_card(a.id, "x", ["т"])
    lib.save_card(b.id, "y", ["т"])
    assert len(lib.session_queue(None, rng=random.Random(1))) == 2
    assert len(lib.session_queue(a.id, rng=random.Random(1))) == 1
    assert lib.session_queue(lib.create_deck("C").id) == []


def test_old_reviews_count_against_review_limit(lib):
    d = lib.create_deck("A")
    c = lib.save_card(d.id, "x", ["т"])
    old = utcnow() - timedelta(days=3)
    lib.reviews.add(ReviewLog(c.id, Grade.GOOD, AnswerMode.SELF, reviewed_at=old))
    lib.reviews.add(ReviewLog(c.id, Grade.GOOD, AnswerMode.SELF))
    assert lib.reviews.daily_counts(local_day_start(utcnow())) == (0, 1)
