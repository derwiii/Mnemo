"""Экраны управления колодами и карточками: полный CRUD через интерфейс."""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QDialog  # noqa: E402

from mnemo.domain.models import CardStatus  # noqa: E402
from mnemo.services import Library  # noqa: E402
from mnemo.storage import Database  # noqa: E402
from mnemo.ui import main_window as mw  # noqa: E402
from mnemo.ui.main_window import MainWindow  # noqa: E402
from mnemo.ui.session_screen import SessionScreen  # noqa: E402


@pytest.fixture
def library():
    lib = Library(Database(":memory:"))
    yield lib
    lib.close()


@pytest.fixture
def win(qapp, library):
    w = MainWindow(library)
    w.resize(1000, 720)
    w.show()
    qapp.processEvents()
    yield w
    w.close()


def answer_dialog(monkeypatch, **fields):
    """Подменяет показ диалога: заполняет поля и нажимает главную кнопку."""
    seen = {}

    def fake(window, dialog):
        for name, value in fields.items():
            getattr(dialog, name).setText(value)
        dialog._on_primary()
        seen["error"] = dialog.error.text() if hasattr(dialog, "error") else ""
        return dialog.result() == QDialog.DialogCode.Accepted

    monkeypatch.setattr(mw, "run_dialog", fake)
    return seen


def confirm_with(monkeypatch, answer):
    calls = []

    def fake(window, title, text, confirm_text, **kwargs):
        calls.append((title, text))
        return answer

    monkeypatch.setattr(mw, "confirm", fake)
    return calls


def new_deck_with_cards(library, n=3, name="Англ"):
    deck = library.create_deck(name, "", "en", "ru")
    for i in range(n):
        library.save_card(deck.id, f"word{i}", [f"слово{i}"])
    return deck


def fill_card(editor, front, *translations):
    editor.front.setText(front)
    editor.translations.set_values(list(translations))


def test_first_launch_shows_empty_state(win):
    d = win.decks_screen
    assert win.current_page is d
    assert d._empty.isVisibleTo(d) and not d._content.isVisibleTo(d)


def test_create_deck_opens_it(win, library, monkeypatch):
    answer_dialog(monkeypatch, name="Англ", source="en", target="ru")
    win.create_deck()
    assert win.current_page is win.deck_screen
    (s,) = library.deck_summaries()
    assert s.deck.name == "Англ" and s.deck.source_language == "en"
    assert win.deck_screen._title.text() == "Англ"


def test_duplicate_deck_name_shows_error(win, library, monkeypatch):
    library.create_deck("Англ")
    seen = answer_dialog(monkeypatch, name="  англ ")
    win.create_deck()
    assert seen["error"]
    assert len(library.deck_summaries()) == 1
    assert win.current_page is win.decks_screen


def test_deck_list_shows_counts(win, library):
    new_deck_with_cards(library, 3)
    win.decks_screen.refresh()
    (row,) = win.decks_screen.rows()
    assert win.decks_screen._big.text() == "3"
    assert row.count.text() == "3 карточки"
    assert row.due.text() == "3 к повторению"
    assert win.decks_screen.study_btn.isEnabled()


def test_rename_deck(win, library, monkeypatch):
    deck = library.create_deck("Старое")
    answer_dialog(monkeypatch, name="Новое")
    win.rename_deck(deck.id)
    assert library.decks.get(deck.id).name == "Новое"


def test_delete_deck_confirms_with_card_count(win, library, monkeypatch):
    deck = new_deck_with_cards(library, 3)
    calls = confirm_with(monkeypatch, False)
    win.delete_deck(deck.id)
    assert library.decks.get(deck.id) is not None
    assert "3 карточки" in calls[0][1] and "Англ" in calls[0][1]
    confirm_with(monkeypatch, True)
    win.delete_deck(deck.id)
    assert library.decks.get(deck.id) is None
    assert library.cards.counts_by_deck() == {}


def test_add_card_via_editor(win, library):
    deck = library.create_deck("Д")
    win.show_deck(deck.id)
    win.add_card(deck.id)
    ed = win.editor_screen
    assert win.current_page is ed
    fill_card(ed, "hello", "привет", "здравствуйте", "")
    ed.examples.set_values([])
    ed.hints.set_values(["h1"])
    assert ed.save(False)
    assert win.current_page is win.deck_screen
    (row,) = library.list_cards(deck.id)
    assert row.card.translations == ["привет", "здравствуйте"]
    assert row.card.hints == ["h1"]
    assert library.states.get(row.card.id).status is CardStatus.NEW


def test_validation_errors_shown_near_fields(win, library):
    deck = library.create_deck("Д")
    win.add_card(deck.id)
    ed = win.editor_screen
    assert not ed.save(False)
    assert win.current_page is ed
    assert ed._front_error.isVisibleTo(ed) and ed._tr_error.isVisibleTo(ed)
    assert library.cards.count_by_deck(deck.id) == 0
    ed.front.setText("x")
    assert not ed._front_error.isVisibleTo(ed)


def test_duplicate_warning_then_confirm(win, library):
    deck = library.create_deck("Д")
    library.save_card(deck.id, "Hello", ["привет"])
    win.add_card(deck.id)
    ed = win.editor_screen
    fill_card(ed, " hello ", "здрасьте")
    assert not ed.save(False)
    assert ed._front_warn.isVisibleTo(ed)
    assert library.cards.count_by_deck(deck.id) == 1
    assert ed.save(False)
    assert library.cards.count_by_deck(deck.id) == 2


def test_save_and_add_another_clears_form(win, library):
    deck = library.create_deck("Д")
    win.add_card(deck.id)
    ed = win.editor_screen
    fill_card(ed, "one", "один")
    assert ed.save(True)
    assert win.current_page is ed
    assert ed.front.text() == "" and ed.deck_id == deck.id and ed.card_id is None
    assert ed._saved_msg.text()
    assert library.cards.count_by_deck(deck.id) == 1


def test_edit_card_keeps_progress(win, library):
    deck = library.create_deck("Д")
    card = library.save_card(deck.id, "a", ["б"])
    st = library.states.get(card.id)
    st.reps, st.status = 4, CardStatus.REVIEW
    library.states.save(st)
    win.edit_card(card.id)
    ed = win.editor_screen
    assert ed.front.text() == "a" and ed.card_id == card.id
    fill_card(ed, "a", "новый перевод")
    assert ed.save(False)
    assert library.cards.get(card.id).translations == ["новый перевод"]
    assert library.states.get(card.id).reps == 4


def test_cancel_with_unsaved_changes_asks(win, library, monkeypatch):
    deck = library.create_deck("Д")
    win.add_card(deck.id)
    ed = win.editor_screen
    assert not ed.is_dirty()
    ed.front.setText("черновик")
    assert ed.is_dirty()
    calls = confirm_with(monkeypatch, False)
    win.close_editor()
    assert win.current_page is ed and calls
    confirm_with(monkeypatch, True)
    win.close_editor()
    assert win.current_page is win.deck_screen
    assert library.cards.count_by_deck(deck.id) == 0


def test_cancel_clean_editor_does_not_ask(win, library, monkeypatch):
    deck = library.create_deck("Д")
    win.add_card(deck.id)
    calls = confirm_with(monkeypatch, False)
    win.close_editor()
    assert not calls and win.current_page is win.deck_screen


def test_delete_card_with_confirmation(win, library, monkeypatch):
    deck = new_deck_with_cards(library, 2)
    win.show_deck(deck.id)
    card = library.list_cards(deck.id)[0].card
    confirm_with(monkeypatch, False)
    win.delete_card(card.id)
    assert library.cards.count_by_deck(deck.id) == 2
    confirm_with(monkeypatch, True)
    win.delete_card(card.id)
    assert library.cards.count_by_deck(deck.id) == 1
    assert len(win.deck_screen.card_rows()) == 1


def test_search_and_nothing_found(win, library):
    deck = library.create_deck("Д")
    library.save_card(deck.id, "Hedgehog", ["ёж"])
    library.save_card(deck.id, "cat", ["кот"])
    win.show_deck(deck.id)
    ds = win.deck_screen
    assert len(ds.card_rows()) == 2
    ds.set_search("ЕЖ")
    assert [r.card_id for r in ds.card_rows()] == [library.list_cards(deck.id, "ёж")[0].card.id]
    ds.set_search("zzz")
    assert ds._empty.isVisibleTo(ds) and ds._empty_title.text() == "Ничего не найдено"
    ds.set_search("")
    assert len(ds.card_rows()) == 2


def test_empty_deck_state(win, library):
    deck = library.create_deck("Пусто")
    win.show_deck(deck.id)
    ds = win.deck_screen
    assert ds._empty.isVisibleTo(ds) and ds._empty_actions.isVisibleTo(ds)
    assert not ds.study_btn.isEnabled()


def test_paging_of_long_lists(win, library):
    deck = library.create_deck("Много")
    library.cards.add_many(
        __import__("mnemo.domain.models", fromlist=["Card"]).Card(deck.id, f"w{i}", [f"т{i}"])
        for i in range(250)
    )
    win.show_deck(deck.id)
    ds = win.deck_screen
    assert len(ds.card_rows()) == 200
    ds.more_btn.click()
    assert len(ds.card_rows()) == 250
    assert not ds.more_btn.isVisibleTo(ds)


def test_study_launches_session_and_returns(win, library):
    deck = new_deck_with_cards(library, 2)
    win.show_deck(deck.id)
    win.start_session(deck.id)
    assert isinstance(win.session, SessionScreen) and win.current_page is win.session
    win.session._finish_btn.click()  # без ответов: сразу назад в колоду
    assert win.current_page is win.deck_screen


def test_study_all_returns_to_decks(win, library):
    new_deck_with_cards(library, 2)
    win.decks_screen.refresh()
    win.start_session(None)
    assert win.current_page is win.session
    win.session.reveal()
    win.session.grade(__import__("mnemo.ui.session_screen", fromlist=["Grade"]).Grade.GOOD)
    win.session._finish_btn.click()  # есть ответ: итог
    assert win.session.is_finished
    win.session._exit_btn.click()
    assert win.current_page is win.decks_screen


def test_data_survives_reopen(tmp_path):
    path = tmp_path / "m.db"
    lib = Library(Database(path))
    new_deck_with_cards(lib, 3)
    lib.close()
    lib2 = Library(Database(path))
    (s,) = lib2.deck_summaries()
    assert s.card_count == 3
    lib2.close()


def test_session_answers_are_written_to_journal(win, library, monkeypatch):
    from mnemo.domain.models import AnswerMode, Grade

    deck = new_deck_with_cards(library, 3)
    win.show_deck(deck.id)
    win.start_session(deck.id)
    s = win.session
    # 1) самопроверка, «Хорошо»
    s.reveal()
    s.grade(Grade.GOOD)
    # 2) верный ввод
    card = s.current_card
    s.submit_answer(card.translations[0])
    s.grade(Grade.EASY)
    # 3) Explicitly save a new translation, then grade the original answer.
    s.submit_answer("совсем не то")
    card_id = s.current_card.card_id
    def accept(window, dialog):
        assert dialog.translation.text() == "совсем не то"
        dialog.translation.setText("другой перевод")
        dialog._on_primary()
        assert not dialog.error.text()
        return True
    monkeypatch.setattr("mnemo.ui.session_screen.run_dialog", accept)
    s.override_correct()
    assert library.reviews.count() == 2
    assert library.cards.get(card_id).translations[-1] == "другой перевод"
    assert s._input.text() == "совсем не то"
    s.grade(Grade.HARD)
    logs = [
        log
        for c in library.cards.list_by_deck(deck.id)
        for log in library.reviews.list_by_card(c.id)
    ]
    assert len(logs) == 3
    modes = sorted(log.answer_mode.value for log in logs)
    assert modes == ["self", "typed", "typed"]
    assert sum(1 for log in logs if log.overridden) == 1
    assert {log.grade for log in logs} == {Grade.GOOD, Grade.EASY, Grade.HARD}
    assert s.is_finished
    s._exit_btn.click()
    # всё просмотрено: повторять нечего
    assert library.deck_summary(deck.id).due_count == 0
    assert not win.deck_screen.study_btn.isEnabled()


def test_variant_form_validation_failure_retry_and_limit(win, library, monkeypatch):
    from mnemo.storage import StorageError
    from mnemo.ui.session_screen import State
    deck = library.create_deck("Variants")
    card = library.save_card(deck.id, "look good", ["хорошо выглядеть"])
    win.start_session(deck.id)
    s = win.session
    s.submit_answer("отлично смотреться")
    original_update = library.cards.update
    def form(window, dialog):
        for text in ("?!", "  ХОРОШО  ВЫГЛЯДЕТЬ! "):
            dialog.translation.setText(text)
            dialog._on_primary()
            assert dialog.error.text()
            assert s.state is State.TYPED_BAD
        def fail(card):
            raise StorageError("write failed")
        monkeypatch.setattr(library.cards, "update", fail)
        dialog.translation.setText("отлично смотреться")
        dialog._on_primary()
        assert "write failed" in dialog.error.text()
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert s.state is State.TYPED_BAD
        assert library.cards.get(card.id).translations == ["хорошо выглядеть"]
        monkeypatch.setattr(library.cards, "update", original_update)
        dialog._on_primary()
        assert dialog.result() == QDialog.DialogCode.Accepted
        return True
    monkeypatch.setattr("mnemo.ui.session_screen.run_dialog", form)
    s.override_correct()
    assert s.state is State.TYPED_OK
    assert library.reviews.count() == 0
    assert s._translation.text() == "хорошо выглядеть · отлично смотреться"
    for i in range(8):
        library.add_translation(card.id, f"вариант {i}")
    win.start_session(deck.id)
    s = win.session
    s.submit_answer("новый перевод")
    def full(window, dialog):
        assert not dialog.primary.isEnabled()
        assert "10" in dialog.error.text()
        dialog._on_primary()
        dialog.reject()
        return False
    monkeypatch.setattr("mnemo.ui.session_screen.run_dialog", full)
    s.override_correct()
    assert s.state is State.TYPED_BAD
    assert len(library.cards.get(card.id).translations) == 10
    assert library.reviews.count() == 0


def test_interrupted_session_keeps_answers(win, library):
    from mnemo.domain.models import Grade

    deck = new_deck_with_cards(library, 3)
    win.start_session(deck.id)
    win.session.reveal()
    win.session.grade(Grade.GOOD)
    win.session._finish_btn.click()  # прервали после одного ответа
    win.session._exit_btn.click()
    assert library.reviews.count() == 1
    assert library.deck_summary(deck.id).due_count == 2


def test_window_is_frameless_with_own_controls(win):
    from PyQt6.QtCore import Qt

    assert win.windowFlags() & Qt.WindowType.FramelessWindowHint
    chrome = win._chrome
    assert len(chrome.edges) == 8
    assert win.decks_screen.header.indexOf(chrome.bar) >= 0
    assert chrome.bar.width() < win._stack.width()
    chrome.bar.maximize_btn.click()
    assert win.isMaximized()
    assert all(e.isHidden() for e in chrome.edges.values())
    chrome.bar.maximize_btn.click()
    assert not win.isMaximized()
    chrome.bar.minimize_btn.click()
    assert win.isMinimized()
    win.showNormal()
    chrome.bar.close_btn.click()
    assert not win.isVisible()


def test_grade_tiles_are_wide_enough(win, library):
    deck = new_deck_with_cards(library, 2)
    win.start_session(deck.id)
    s = win.session
    s.reveal()
    s.show()
    from PyQt6.QtWidgets import QApplication

    QApplication.processEvents()
    for button in s._grade_buttons.values():
        assert button.width() >= 150, button.width()
