import random
from dataclasses import replace
from datetime import timedelta

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from mnemo.domain.models import AnswerMode, CardStatus, Grade, utcnow
from mnemo.services import Library
from mnemo.storage import Database, StorageError
from mnemo.ui.main_window import MainWindow


@pytest.fixture
def app_window(qapp):
    lib = Library(Database(":memory:"))
    w = MainWindow(lib)
    w.show()
    qapp.processEvents()
    yield w, lib
    w.close()
    lib.close()


def test_repeat_deck_and_corrected_errors(app_window):
    w, lib = app_window
    d = lib.create_deck("A")
    cards = [lib.save_card(d.id, str(i), ["т"]) for i in range(3)]
    for c in cards:
        lib.record_review(c.id, Grade.GOOD, AnswerMode.SELF)
    w.show_deck(d.id)
    assert not w.deck_screen.study_btn.isEnabled()
    w.deck_screen.repeat_btn.click()
    s = w.session
    failed_id = s.current_card.card_id
    s.submit_answer("ошибка")
    s.next_after_wrong()
    while not s.is_finished:
        s.reveal()
        s.grade(Grade.HARD)
    assert len(s.results) == 4
    assert lib.reviews.count() == 3
    s._errors_btn.click()
    assert s.current_card.card_id == failed_id
    s.reveal()
    s.grade(Grade.GOOD)
    assert s.is_finished and len(s.results) == 1
    assert s._counter.text() == "1 / 1"
    assert not s._errors_btn.isEnabled()
    s.exitRequested.emit()
    assert w.current_page is w.deck_screen
    w.deck_screen.repeat_btn.click()
    assert len(w.session._queue) == 3


def test_failed_save_keeps_current_card_and_can_retry(app_window, monkeypatch):
    w, lib = app_window
    d = lib.create_deck("A")
    c = lib.save_card(d.id, "w", ["т"])
    w.start_session(d.id)
    s = w.session
    original = lib.record_review
    monkeypatch.setattr("mnemo.ui.main_window.info", lambda *args: None)
    def fail(*args, **kwargs):
        raise StorageError("disk full")
    monkeypatch.setattr(lib, "record_review", fail)
    s.reveal()
    s.grade(Grade.GOOD)
    assert not s.is_finished and s.current_card.card_id == c.id
    assert s.results == [] and lib.reviews.count() == 0
    monkeypatch.setattr(lib, "record_review", original)
    s.grade(Grade.GOOD)
    assert s.is_finished and lib.reviews.count() == 1


def test_pool_validates_count_and_returns_to_setup(app_window):
    w, lib = app_window
    d = lib.create_deck("A")
    for i in range(3):
        lib.save_card(d.id, str(i), ["т"])
    w.show_decks()
    w.decks_screen.pool_btn.click()
    setup = w._setup
    setup.random_cards.setChecked(True)
    setup.count.setText("4")
    assert not setup.start_btn.isEnabled() and "3" in setup.error.text()
    setup.count.setText("2")
    setup.start_btn.click()
    s = w.session
    assert len(s._queue) == 2
    while not s.is_finished:
        s.reveal()
        s.grade(Grade.GOOD)
    s.exitRequested.emit()
    assert w.current_page is setup


def test_empty_deck_and_empty_pool_cannot_start(app_window):
    w, lib = app_window
    d = lib.create_deck("A")
    w.show_deck(d.id)
    assert not w.deck_screen.repeat_btn.isEnabled()
    w.show_session_setup()
    assert not w._setup.start_btn.isEnabled()


def test_single_card_repeats_immediately_and_results_stay_in_memory(app_window):
    w, lib = app_window
    d = lib.create_deck("A")
    c = lib.save_card(d.id, "w", ["т"])
    w.start_free_session(d.id)
    s = w.session
    for _ in range(2):
        s.forget()
        s.next_after_wrong()
        assert s.current_card.card_id == c.id
    s.finish()  # две подтверждённые попытки остаются лишь в итогах прохода
    assert lib.reviews.count() == 0
    s.repeat_errors()
    s.reveal()
    s.grade(Grade.HARD)
    assert s.is_finished
    stats = lib.statistics()
    assert (stats.reviews_period, stats.failures_period, stats.unique_cards_period) == (0, 0, 0)


@pytest.mark.parametrize("entry", ["home", "deck", "direct", "pool_all", "pool_random"])
@pytest.mark.parametrize("status", list(CardStatus))
def test_free_entries_never_write_or_schedule(app_window, monkeypatch, entry, status):
    w, lib = app_window
    now = utcnow()
    deck = lib.create_deck("Practice")
    card = lib.save_card(deck.id, "word", ["перевод"], hints=["h1", "h2"])
    state = replace(lib.states.get(card.id), status=status,
                    due_at=now + timedelta(days=1 if status is CardStatus.REVIEW else -1),
                    interval_days=10 if status is CardStatus.REVIEW else 0,
                    ease=2.1, lapses=2, reps=0 if status is CardStatus.NEW else 3)
    lib.states.save(state)
    before_stats = lib.statistics(now)
    before_queue = lib.session_queue(now=now, rng=random.Random(7))
    before_due = lib.due_totals(now)
    before_changes = lib.db.conn.total_changes

    def forbidden(*args, **kwargs):
        pytest.fail("Free practice called the persistent review path")
    monkeypatch.setattr(lib, "record_review", forbidden)
    monkeypatch.setattr(lib.scheduler, "review", forbidden)
    if entry == "home":
        w.show_decks()
        w.decks_screen.repeat_btn.click()
    elif entry == "deck":
        w.show_deck(deck.id)
        w.deck_screen.repeat_btn.click()
    elif entry == "direct":
        w.start_free_session(deck.id)
    else:
        w.show_session_setup()
        w.start_pool_session(1 if entry == "pool_random" else None)
    session = w.session
    session.use_hint()
    session.submit_answer("ошибка")
    session.next_after_wrong()
    assert session.current_card.card_id == card.id and session.hints_open == 0
    session.use_hint()
    session.use_hint()
    session.reveal()
    session.grade(Grade.EASY)
    assert session.is_finished
    assert session.results[-1]["grade"] is Grade.EASY
    assert "Успешных: 1" in session._end_summary.text()
    assert "Провалов: 1" in session._end_summary.text()
    assert "Успешность: 50%" in session._end_summary.text()
    session.repeat_errors()
    session.reveal()
    session.grade(Grade.HARD)
    assert len(session.results) == 1
    assert "Успешность: 100%" in session._end_summary.text()
    assert "Провалов: 0" in session._end_summary.text()
    session.exitRequested.emit()
    assert lib.states.get(card.id) == state
    assert lib.reviews.count() == 0
    assert lib.statistics(now) == before_stats
    assert lib.session_queue(now=now, rng=random.Random(7)) == before_queue
    assert lib.due_totals(now) == before_due
    assert lib.db.conn.total_changes == before_changes


def test_free_results_disappear_on_reopen_but_explicit_translation_survives(qapp, tmp_path):
    path = tmp_path / "practice.db"
    lib = Library(Database(path))
    deck = lib.create_deck("Practice")
    card = lib.save_card(deck.id, "word", ["перевод"])
    before = lib.states.get(card.id)
    w = MainWindow(lib)
    w.start_free_session(deck.id)
    session = w.session
    for _ in range(2):
        session.forget()
        session.next_after_wrong()
    session.submit_answer("новый вариант")
    assert session.save_variant("новый вариант") is None
    session.grade(Grade.GOOD)
    assert "Успешных: 1" in session._end_summary.text()
    assert "Провалов: 2" in session._end_summary.text()
    assert "Успешность: 33%" in session._end_summary.text()
    session.exitRequested.emit()
    assert w.session is None
    w.close()
    qapp.processEvents()
    lib.close()
    reopened = Library(Database(path))
    try:
        assert reopened.cards.get(card.id).translations == ["перевод", "новый вариант"]
        assert reopened.states.get(card.id) == before
        assert reopened.reviews.count() == 0
        assert reopened.statistics().reviews_period == 0
        tables = reopened.db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        assert not any("practice" in row[0] or "session" in row[0] for row in tables)
    finally:
        reopened.close()


def test_free_partial_finish_and_no_answer_do_not_count_unconfirmed_attempts(app_window):
    w, lib = app_window
    deck = lib.create_deck("Practice")
    for i in range(3):
        lib.save_card(deck.id, str(i), ["перевод"])
    w.start_free_session(deck.id)
    session = w.session
    session.reveal()
    session.grade(Grade.GOOD)
    session.submit_answer("ошибка")
    session._on_finish_clicked()
    assert len(session.results) == 1
    assert session._end_title.text() == "Сессия завершена"
    assert "Успешность: 100%" in session._end_summary.text()
    assert "Провалов: 0" in session._end_summary.text()
    assert not session._errors_btn.isEnabled()
    session.exitRequested.emit()
    w.start_free_session(deck.id)
    session = w.session
    session.finish()
    assert "Успешность: —" in session._end_summary.text()
    session.exitRequested.emit()
    w.start_free_session(deck.id)
    w.session._on_finish_clicked()
    assert w.session is None and lib.reviews.count() == 0
