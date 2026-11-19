"""Строки колоды сохраняются при обновлениях вместе с положением просмотра."""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QCoreApplication, QEvent, QTimer
from PyQt6.QtWidgets import QLabel

from mnemo.domain.models import Card, CardStatus
from mnemo.services import Library
from mnemo.storage import Database
from mnemo.ui import deck_screen, main_window
from mnemo.ui.main_window import MainWindow


def settle(qapp):
    for _ in range(3):
        qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def view(qapp, monkeypatch):
    monkeypatch.setattr(deck_screen, "CARDS_PAGE_SIZE", 20)
    library = Library(Database(":memory:"))
    deck = library.create_deck("Колода")
    library.cards.add_many(Card(deck.id, f"word{i}", [f"слово{i}"]) for i in range(55))
    win = MainWindow(library)
    win.resize(1100, 800)
    win.show()
    win.activateWindow()
    win.show_deck(deck.id)
    settle(qapp)
    yield win, library, deck.id
    win.close()
    settle(qapp)
    library.close()


def anchor(screen):
    value = screen._scroll.verticalScrollBar().value()
    row = next(r for r in screen.card_rows() if r.y() + r.height() > value)
    return row.card_id, row.y() - value


def test_refresh_reuses_rows_and_does_not_reapply_unchanged_text(view, qapp, monkeypatch):
    win, _, _ = view
    screen = win.deck_screen
    original = screen.card_rows()
    edits = []
    screen.editCard.connect(edits.append)

    def unexpected(*args, **kwargs):
        pytest.fail("unchanged row was rendered again")

    monkeypatch.setattr(deck_screen, "set_front_text", unexpected)
    monkeypatch.setattr(deck_screen, "set_prop", unexpected)
    screen.refresh()
    screen.refresh()
    settle(qapp)
    assert screen.card_rows() == original
    original[0].edit_btn.click()
    assert edits == [original[0].card_id]


def test_show_more_appends_and_return_preserves_search_limit_and_position(view, qapp):
    win, _, deck_id = view
    screen = win.deck_screen
    screen.set_search("word")
    settle(qapp)
    original = screen.card_rows()
    screen.more_btn.click()
    settle(qapp)
    assert screen.visible_card_count == 40
    assert screen.card_rows()[:20] == original
    bar = screen._scroll.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    settle(qapp)
    before = anchor(screen)
    original = screen.card_rows()
    win.show_decks()
    win.show_deck(deck_id)
    settle(qapp)
    assert screen.search.text() == "word"
    assert screen.visible_card_count == 40
    assert screen.card_rows() == original
    assert anchor(screen) == before


@pytest.mark.parametrize("victim_position", ["above", "anchor", "below", "last"])
def test_delete_preserves_anchor_and_surviving_rows(view, qapp, monkeypatch, victim_position):
    win, library, deck_id = view
    screen = win.deck_screen
    bar = screen._scroll.verticalScrollBar()
    if victim_position == "last":
        screen.more_btn.click()
        screen.more_btn.click()
        settle(qapp)
        bar.setValue(bar.maximum())
    else:
        bar.setValue(bar.maximum() // 2)
    settle(qapp)
    before_id, before_offset = anchor(screen)
    rows = screen.card_rows()
    top_index = next(i for i, r in enumerate(rows) if r.card_id == before_id)
    if victim_position == "above":
        victim = rows[0]
    elif victim_position == "anchor":
        victim = rows[top_index]
    elif victim_position == "last":
        victim = rows[-1]
    else:
        victim = rows[top_index + 2]
    expected_id = rows[top_index + 1].card_id if victim.card_id == before_id else before_id
    survivors = {r.card_id: r for r in rows if r is not victim}
    if victim_position in ("anchor", "below", "last"):
        victim.delete_btn.setFocus()
        settle(qapp)
        assert victim.delete_btn.hasFocus()
    monkeypatch.setattr(main_window, "confirm", lambda *a, **kw: True)
    win.delete_card(victim.card_id)
    settle(qapp)
    assert library.cards.count_by_deck(deck_id) == 54
    assert all(screen._row_widgets[key] is row for key, row in survivors.items())
    assert victim.card_id not in screen._row_widgets
    if victim_position == "last":
        # После удаления у конца диапазон уменьшается: допустимо только ограничение максимумом.
        assert bar.value() == bar.maximum()
    else:
        assert anchor(screen) == (expected_id, before_offset)
        assert screen.visible_card_count == 20  # следующая карточка заполняет страницу


def test_edit_and_learning_status_update_existing_row(view, qapp):
    win, library, deck_id = view
    screen = win.deck_screen
    rows = screen.card_rows()
    row = rows[2]
    win.edit_card(row.card_id)
    editor = win.editor_screen
    editor.front.setText("[[edited]] {word|phrase}")
    editor.translations.set_values(["новый {перевод|вариант}"])
    assert editor.save(False)
    settle(qapp)
    assert screen.card_rows() == rows
    assert row.findChild(QLabel, "CardWord").accessibleName() == "edited [word / phrase]"
    assert row.findChild(QLabel, "CardTranslations").text() == "новый перевод / вариант"
    state = library.states.get(row.card_id)
    state.status = CardStatus.REVIEW
    state.interval_days = 100
    library.states.save(state)
    win.show_deck(deck_id)
    settle(qapp)
    assert screen.card_rows() == rows
    assert row.findChild(QLabel, "Status").property("kind") == "learned"


def test_changed_search_resets_paging_and_pending_scroll_restore(view, qapp):
    win, _, _ = view
    screen = win.deck_screen
    screen.more_btn.click()
    settle(qapp)
    bar = screen._scroll.verticalScrollBar()
    bar.setValue(bar.maximum())
    screen.refresh()  # восстановление старой позиции ещё стоит в очереди
    screen.search.setText("word1")
    screen._timer.timeout.emit()
    screen._timer.stop()
    settle(qapp)
    assert screen.visible_card_count == 11
    assert screen._limit == 20
    assert bar.value() == 0
    screen.set_search("no match")
    settle(qapp)
    assert screen.visible_card_count == 0
    assert screen._empty.isVisibleTo(screen)
    screen.set_search("")
    settle(qapp)
    assert screen.visible_card_count == 20


def test_switch_deck_resets_state_and_ignores_old_restore(view, qapp):
    win, library, _ = view
    screen = win.deck_screen
    screen.more_btn.click()
    settle(qapp)
    screen._scroll.verticalScrollBar().setValue(500)
    screen.refresh()
    other = library.create_deck("Другая")
    card = library.save_card(other.id, "other", ["другой"])
    win.show_deck(other.id)
    settle(qapp)
    assert [r.card_id for r in screen.card_rows()] == [card.id]
    assert screen.search.text() == ""
    assert screen._limit == 20
    assert screen._scroll.verticalScrollBar().value() == 0


def test_cancel_delete_and_failed_write_keep_rows(view, monkeypatch):
    win, library, _ = view
    screen = win.deck_screen
    rows = screen.card_rows()
    monkeypatch.setattr(main_window, "confirm", lambda *a, **kw: False)
    win.delete_card(rows[0].card_id)
    assert screen.card_rows() == rows
    monkeypatch.setattr(main_window, "confirm", lambda *a, **kw: True)

    def fail(*args):
        raise RuntimeError("database write failed")

    monkeypatch.setattr(library, "delete_card", fail)
    with pytest.raises(RuntimeError, match="database write failed"):
        win.delete_card(rows[0].card_id)
    assert screen.card_rows() == rows


@pytest.mark.parametrize("accept", [True, False])
def test_real_confirmation_keeps_view_position(view, qapp, accept):
    win, library, deck_id = view
    screen = win.deck_screen
    bar = screen._scroll.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    settle(qapp)
    before = anchor(screen)
    rows = screen.card_rows()
    index = next(i for i, row in enumerate(rows) if row.card_id == before[0])
    victim = rows[index + 2]
    victim.delete_btn.setFocus()
    settle(qapp)

    def answer():
        dialog = qapp.activeModalWidget()
        if accept:
            dialog.primary.setFocus()
            dialog.primary.click()
        else:
            dialog.reject()

    QTimer.singleShot(0, answer)
    win.delete_card(victim.card_id)
    win.activateWindow()
    settle(qapp)
    assert anchor(screen) == before
    assert library.cards.count_by_deck(deck_id) == 55 - int(accept)
    assert all(screen._row_widgets[row.card_id] is row for row in rows if row is not victim)


def test_delete_last_card_shows_empty_state(view, qapp, monkeypatch):
    win, library, deck_id = view
    cards = library.cards.list_by_deck(deck_id)
    for card in cards[1:]:
        library.delete_card(card.id)
    screen = win.deck_screen
    screen.refresh()
    settle(qapp)
    row = screen.card_rows()[0]
    row.delete_btn.setFocus()
    monkeypatch.setattr(main_window, "confirm", lambda *a, **kw: True)
    win.delete_card(row.card_id)
    settle(qapp)
    assert screen.visible_card_count == 0
    assert screen._empty.isVisibleTo(screen)
    assert not screen.search.isEnabled()


def test_destroy_screen_before_pending_restore(qapp):
    from PyQt6 import sip

    library = Library(Database(":memory:"))
    try:
        deck = library.create_deck("Временная")
        library.save_card(deck.id, "word", ["слово"])
        screen = deck_screen.DeckScreen(library)
        screen.show_deck(deck.id)
        sip.delete(screen)
        settle(qapp)
    finally:
        library.close()


def test_changed_row_height_above_view_keeps_anchor(view, qapp):
    win, library, deck_id = view
    screen = win.deck_screen
    bar = screen._scroll.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    settle(qapp)
    before = anchor(screen)
    row = screen.card_rows()[0]
    library.save_card(deck_id, "word0", ["длинный перевод " * 35], card_id=row.card_id)
    screen.refresh()
    settle(qapp)
    assert screen.card_rows()[0] is row
    assert anchor(screen) == before
