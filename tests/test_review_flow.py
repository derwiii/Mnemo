"""Запись ответов: журнал, расписание, подсказки, прерывание."""

import sqlite3
from datetime import timedelta

import pytest

from mnemo.domain.models import AnswerMode, CardStatus, Grade, utcnow
from mnemo.services import Library
from mnemo.storage import Database


@pytest.fixture
def lib():
    library = Library(Database(":memory:"))
    yield library
    library.close()


def setup_card(lib, hints=("h1", "h2")):
    d = lib.create_deck("A")
    return d, lib.save_card(d.id, "w", ["т"], hints=list(hints))


def test_record_updates_state_and_log(lib):
    d, c = setup_card(lib)
    log = lib.record_review(c.id, Grade.GOOD, AnswerMode.SELF, response_time_ms=1500)
    st = lib.states.get(c.id)
    assert st.status is CardStatus.REVIEW and st.reps == 1 and st.interval_days == 1.0
    (stored,) = lib.reviews.list_by_card(c.id)
    assert stored.id == log.id and stored.response_time_ms == 1500
    assert stored.answer_mode is AnswerMode.SELF and stored.typed_answer is None
    assert (stored.interval_before, stored.interval_after) == (0.0, 1.0)


def test_typed_answer_and_override_logged(lib):
    d, c = setup_card(lib)
    lib.record_review(c.id, Grade.GOOD, AnswerMode.TYPED, typed_answer="синоним", overridden=True)
    (log,) = lib.reviews.list_by_card(c.id)
    assert log.answer_mode is AnswerMode.TYPED and log.typed_answer == "синоним" and log.overridden
    # переопределение обрабатывается как верный ответ: карточка не провалена
    assert lib.states.get(c.id).lapses == 0 and lib.states.get(c.id).status is CardStatus.REVIEW


def test_wrong_typed_answer_is_again(lib):
    d, c = setup_card(lib)
    lib.record_review(c.id, Grade.AGAIN, AnswerMode.TYPED, typed_answer="не то")
    st = lib.states.get(c.id)
    assert st.status is CardStatus.LEARNING
    assert st.due_at - utcnow() < timedelta(minutes=11)


def test_easy_with_hint_logged_as_easy_processed_as_good(lib):
    d, c = setup_card(lib)
    d2 = lib.create_deck("B")
    c2 = lib.save_card(d2.id, "x", ["т"], hints=["a", "b"])
    lib.record_review(c.id, Grade.EASY, AnswerMode.SELF, hints_used=1)
    lib.record_review(c2.id, Grade.GOOD, AnswerMode.SELF)
    (log,) = lib.reviews.list_by_card(c.id)
    assert log.grade is Grade.EASY and log.hints_used == 1
    a, b = lib.states.get(c.id), lib.states.get(c2.id)
    assert (a.interval_days, a.ease) == (b.interval_days, b.ease)


def test_untyped_fields_not_stored_for_self_mode(lib):
    d, c = setup_card(lib)
    lib.record_review(c.id, Grade.GOOD, AnswerMode.SELF, typed_answer="x", overridden=True)
    (log,) = lib.reviews.list_by_card(c.id)
    assert log.typed_answer is None and log.overridden is False


def test_answers_survive_closing_midway(tmp_path):
    path = tmp_path / "m.db"
    first = Library(Database(path))
    d = first.create_deck("A")
    cards = [first.save_card(d.id, f"w{i}", ["т"]) for i in range(3)]
    first.record_review(cards[0].id, Grade.GOOD, AnswerMode.SELF)
    first.record_review(cards[1].id, Grade.AGAIN, AnswerMode.TYPED, typed_answer="x")
    first.close()  # приложение закрыто посреди сессии
    again = Library(Database(path))
    assert again.reviews.count() == 2
    assert again.states.get(cards[0].id).status is CardStatus.REVIEW
    assert again.states.get(cards[1].id).status is CardStatus.LEARNING
    again.close()


def test_counts_follow_schedule(lib):
    d, c = setup_card(lib)
    assert lib.deck_summary(d.id).due_count == 1
    lib.record_review(c.id, Grade.GOOD, AnswerMode.SELF)  # теперь повторить через день
    assert lib.deck_summary(d.id).due_count == 0
    assert lib.due_totals() == (0, 0)
    assert lib.session_queue(d.id) == []
    later = utcnow() + timedelta(days=2)
    assert lib.deck_summary(d.id, later).due_count == 1
    assert [x.id for x in lib.session_queue(d.id, later)] == [c.id]


def test_new_cards_capped_in_counts(lib):
    lib.new_limit = 20
    d = lib.create_deck("A")
    lib.cards.add_many(
        __import__("mnemo.domain.models", fromlist=["Card"]).Card(d.id, f"w{i}", ["т"]) for i in range(30)
    )
    assert lib.deck_summary(d.id).due_count == 20
    assert lib.due_totals() == (20, 1)


def test_unknown_card_rejected(lib):
    from mnemo.storage import NotFoundError

    with pytest.raises(NotFoundError):
        lib.record_review("нет такой", Grade.GOOD, AnswerMode.SELF)


def test_no_daily_limits_by_default(lib):
    from mnemo.domain.models import Card

    d = lib.create_deck("A")
    lib.cards.add_many(Card(d.id, f"w{i}", ["т"]) for i in range(130))
    assert lib.deck_summary(d.id).due_count == 130
    assert lib.due_totals() == (130, 1)
    assert len(lib.session_queue(d.id)) == 130
    # после ответов остаток не режется лимитом
    for card in lib.session_queue(d.id)[:30]:
        lib.record_review(card.id, Grade.AGAIN, AnswerMode.SELF)
    assert len(lib.session_queue(d.id, utcnow() + timedelta(hours=1))) == 130


@pytest.mark.parametrize("grade, effective", [(Grade.GOOD, Grade.HARD), (Grade.EASY, Grade.GOOD)])
@pytest.mark.parametrize("used,total", [(1, 1), (1, 5), (5, 5)])
def test_hinted_main_review_keeps_original_grade_and_updates_effective_state(lib, grade, effective, used, total):
    from dataclasses import replace
    from mnemo.domain.scheduler import Sm2Scheduler
    d = lib.create_deck("Hints")
    c = lib.save_card(d.id, "word", ["перевод"], hints=[f"hint {i}" for i in range(total)])
    now = utcnow()
    before = replace(lib.states.get(c.id), status=CardStatus.REVIEW,
                     interval_days=10, ease=2.5, reps=4)
    lib.states.save(before)
    expected = Sm2Scheduler().review(before, effective, now).state
    log = lib.record_review(c.id, grade, AnswerMode.SELF, hints_used=used, now=now)
    assert log.grade is grade and log.hints_used == used
    assert lib.states.get(c.id) == expected
    assert lib.statistics(now).correct_percent == 100


def test_review_transaction_failure_rolls_back_state_and_retry_records_once(lib, monkeypatch):
    _, card = setup_card(lib)
    before = lib.states.get(card.id)
    original = lib.reviews.add
    def fail(log):
        raise sqlite3.OperationalError("write failed")
    monkeypatch.setattr(lib.reviews, "add", fail)
    with pytest.raises(sqlite3.OperationalError):
        lib.record_review(card.id, Grade.GOOD, AnswerMode.SELF)
    assert lib.states.get(card.id) == before and lib.reviews.count() == 0
    monkeypatch.setattr(lib.reviews, "add", original)
    lib.record_review(card.id, Grade.GOOD, AnswerMode.SELF)
    assert lib.reviews.count() == 1 and lib.states.get(card.id).reps == 1
