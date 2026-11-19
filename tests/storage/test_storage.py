import time

import pytest

from mnemo.domain.models import AnswerMode, Card, CardStatus, Deck, Example, Grade, ReviewLog
from mnemo.storage import (
    CardRepository,
    Database,
    DeckRepository,
    DuplicateDeckNameError,
    ReviewRepository,
    StateRepository,
    StorageError,
)


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.db")
    yield d
    d.close()


def make(db):
    decks, cards = DeckRepository(db), CardRepository(db)
    deck = decks.add(Deck("Английский"))
    return decks, cards, deck


def test_persists_between_opens(tmp_path):
    path = tmp_path / "p.db"
    db1 = Database(path)
    deck = DeckRepository(db1).add(Deck("Д"))
    card = CardRepository(db1).add(
        Card(deck.id, "ёж", ["hedgehog"], examples=[Example("ex", "пр")], hints=["h"], tags=["t"])
    )
    db1.close()
    db2 = Database(path)
    got = CardRepository(db2).get(card.id)
    assert got.front == "ёж" and got.examples == [Example("ex", "пр")]
    assert got.hints == ["h"] and got.tags == ["t"]
    assert db2.schema_version == 4
    db2.close()


def test_card_state_created_with_card(db):
    _, cards, deck = make(db)
    card = cards.add(Card(deck.id, "a", ["б"]))
    state = StateRepository(db).get(card.id)
    assert state.status is CardStatus.NEW and state.reps == 0


def test_deck_name_unique_case_insensitive_cyrillic(db):
    decks, _, _ = make(db)
    with pytest.raises(DuplicateDeckNameError):
        decks.add(Deck("  АНГЛИЙСКИЙ "))
    assert decks.get_by_name("английский") is not None


def test_cascade_delete_deck(db):
    decks, cards, deck = make(db)
    card = cards.add(Card(deck.id, "a", ["б"]))
    ReviewRepository(db).add(ReviewLog(card.id, Grade.GOOD, AnswerMode.SELF))
    decks.delete(deck.id)
    for table in ("decks", "cards", "card_states", "review_logs"):
        assert db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_edit_card_keeps_state_and_log(db):
    _, cards, deck = make(db)
    card = cards.add(Card(deck.id, "a", ["б"]))
    states, reviews = StateRepository(db), ReviewRepository(db)
    st = states.get(card.id)
    st.reps, st.status, st.interval_days = 3, CardStatus.REVIEW, 6.0
    states.save(st)
    reviews.add(ReviewLog(card.id, Grade.GOOD, AnswerMode.TYPED, typed_answer="б", overridden=True))
    card.front, card.translations = "a2", ["в"]
    cards.update(card)
    st2 = states.get(card.id)
    assert (st2.reps, st2.status, st2.interval_days) == (3, CardStatus.REVIEW, 6.0)
    logs = reviews.list_by_card(card.id)
    assert len(logs) == 1 and logs[0].overridden and logs[0].typed_answer == "б"
    assert cards.get(card.id).front == "a2"


def test_batch_rolls_back_on_error(db):
    _, cards, deck = make(db)
    good = Card(deck.id, "ok", ["x"])
    bad = Card("no-such-deck", "bad", ["y"])
    with pytest.raises(Exception):
        cards.add_many([good, bad])
    assert cards.count_by_deck(deck.id) == 0
    assert db.conn.execute("SELECT COUNT(*) FROM card_states").fetchone()[0] == 0


def test_nested_transaction_rolls_back_outer(db):
    _, cards, deck = make(db)
    with pytest.raises(RuntimeError):
        with db.transaction():
            cards.add(Card(deck.id, "a", ["б"]))
            raise RuntimeError
    assert cards.count_by_deck(deck.id) == 0


def test_search_ignores_case_and_yo(db):
    _, cards, deck = make(db)
    cards.add(Card(deck.id, "Hedgehog", ["ёж", "ёжик"]))
    cards.add(Card(deck.id, "cat", ["кот"]))
    assert [c.front for c in cards.list_by_deck(deck.id, "ЕЖИ")] == ["Hedgehog"]
    assert [c.front for c in cards.list_by_deck(deck.id, "hedge")] == ["Hedgehog"]
    assert cards.list_by_deck(deck.id, "100%") == []


def test_find_by_front_duplicates(db):
    _, cards, deck = make(db)
    cards.add(Card(deck.id, "To  Go", ["идти"]))
    assert len(cards.find_by_front(deck.id, "to go")) == 1


def test_newer_schema_rejected(tmp_path):
    path = tmp_path / "n.db"
    db = Database(path)
    db.conn.execute("PRAGMA user_version = 99")
    db.close()
    with pytest.raises(StorageError):
        Database(path)


def test_data_dir_override(monkeypatch, tmp_path):
    from mnemo.paths import data_dir, db_path

    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path / "x"))
    assert data_dir() == tmp_path / "x"
    assert db_path().name == "mnemo.db"


def test_ten_thousand_cards_fast(db):
    decks, cards, deck = make(db)
    cards.add_many(Card(deck.id, f"word{i}", [f"слово{i}"], hints=["h"]) for i in range(10_000))
    t = time.perf_counter()
    assert len(cards.list_by_deck(deck.id)) == 10_000
    assert len(cards.list_by_deck(deck.id, "word99")) == 111
    assert time.perf_counter() - t < 1.0
