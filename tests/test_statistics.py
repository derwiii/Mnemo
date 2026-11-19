from datetime import timedelta

import pytest

from mnemo.domain.models import AnswerMode, CardStatus, Grade, ReviewLog, utcnow
from mnemo.services import Library
from mnemo.storage import Database


@pytest.fixture
def lib():
    library = Library(Database(":memory:"))
    yield library
    library.close()


def test_empty_database_gives_zeros(lib):
    st = lib.statistics()
    assert (st.total_cards, st.reviews_today, st.reviews_period) == (0, 0, 0)
    assert st.correct_percent is None and st.hardest == []


def test_numbers_on_prepared_journal(lib):
    d = lib.create_deck("A")
    cards = [lib.save_card(d.id, f"w{i}", ["т"]) for i in range(6)]
    now = utcnow()

    def log(card, grade, when):
        lib.reviews.add(ReviewLog(card.id, grade, AnswerMode.SELF, reviewed_at=when))

    # сегодня: 4 попытки (3 успеха); 10 дней назад: 2 успеха; 45 дней назад: вне периода
    for g in (Grade.GOOD, Grade.EASY, Grade.GOOD, Grade.AGAIN):
        log(cards[0], g, now)
    for g in (Grade.HARD, Grade.EASY):
        log(cards[1], g, now - timedelta(days=10))
    for _ in range(5):
        log(cards[2], Grade.GOOD, now - timedelta(days=45))
    for c, status in ((cards[0], CardStatus.REVIEW), (cards[1], CardStatus.LEARNING)):
        s = lib.states.get(c.id)
        s.status = status
        lib.states.save(s)
    st = lib.statistics(now)
    assert (st.total_cards, st.new_cards, st.learning_cards, st.review_cards) == (6, 4, 1, 1)
    assert st.reviews_today == 4
    assert st.reviews_period == 6
    assert st.correct_percent == round(100 * 5 / 6)
    assert st.failures_period == 1
    assert st.unique_cards_period == 2


def test_hardest_ordering_and_filters(lib):
    d = lib.create_deck("A")
    ids = [lib.save_card(d.id, f"w{i}", ["т"]).id for i in range(5)]
    setups = {  # lapses, ease, reps
        ids[0]: (5, 1.5, 9),
        ids[1]: (2, 2.0, 6),
        ids[2]: (0, 2.5, 4),  # не трудная
        ids[3]: (9, 1.3, 0),  # ни разу не отвечали: не показывается
    }
    for cid, (lapses, ease, reps) in setups.items():
        s = lib.states.get(cid)
        s.lapses, s.ease, s.reps = lapses, ease, reps
        lib.states.save(s)
    hardest = lib.statistics().hardest
    assert [h.card.id for h in hardest] == [ids[0], ids[1]]
    assert hardest[0].state.lapses == 5


def test_hardest_limited(lib):
    d = lib.create_deck("A")
    for i in range(15):
        c = lib.save_card(d.id, f"w{i}", ["т"])
        s = lib.states.get(c.id)
        s.lapses, s.reps = i + 1, 3
        lib.states.save(s)
    assert len(lib.statistics().hardest) == 10
    assert lib.statistics().hardest[0].state.lapses == 15


def test_recomputed_after_new_answers(lib):
    d = lib.create_deck("A")
    c = lib.save_card(d.id, "w", ["т"])
    assert lib.statistics().reviews_today == 0
    lib.record_review(c.id, Grade.GOOD, AnswerMode.SELF)
    st = lib.statistics()
    assert st.reviews_today == 1 and st.correct_percent == 100 and st.review_cards == 1
