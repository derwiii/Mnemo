"""Поток экрана сессии: единый ввод/самопроверка, подсказки, оценки."""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402

from mnemo.ui.demo_data import DEMO_DECK_NAME, demo_cards  # noqa: E402
from mnemo.ui.session_screen import Grade, SessionScreen, State  # noqa: E402


@pytest.fixture
def screen(qapp):
    s = SessionScreen(DEMO_DECK_NAME, demo_cards())
    s.resize(1000, 720)
    s.show()
    qapp.processEvents()
    yield s
    s.close()


def _input(s):
    return s._input


def test_starts_with_question(screen):
    assert screen.state is State.QUESTION
    assert screen.current_card.front == "to give up"
    assert screen.primary_text == "Показать ответ"
    assert not screen.hint_column_open


def test_enter_on_empty_reveals(screen):
    QTest.keyClick(_input(screen), Qt.Key.Key_Return)
    assert screen.state is State.REVEALED


def test_space_on_empty_reveals(screen):
    QTest.keyClick(_input(screen), Qt.Key.Key_Space)
    assert screen.state is State.REVEALED


def test_whitespace_only_counts_as_empty(screen):
    _input(screen).setText("   ")
    QTest.keyClick(_input(screen), Qt.Key.Key_Return)
    assert screen.state is State.REVEALED
    assert screen.results == []


def test_space_with_text_types_space(screen):
    _input(screen).setText("бро")
    QTest.keyClick(_input(screen), Qt.Key.Key_Space)
    assert screen.state is State.QUESTION
    assert _input(screen).text() == "бро "


def test_primary_text_switches(screen):
    _input(screen).setText("а")
    assert screen.primary_text == "Проверить"
    _input(screen).setText("")
    assert screen.primary_text == "Показать ответ"


def test_enter_with_correct_text_checks(screen):
    _input(screen).setText("  СДАВАТЬСЯ ")
    QTest.keyClick(_input(screen), Qt.Key.Key_Return)
    assert screen.state is State.TYPED_OK


def test_wrong_answer_then_next_records_again(screen):
    screen.submit_answer("боязливый")
    assert screen.state is State.TYPED_BAD
    QTest.keyClick(screen, Qt.Key.Key_Return)
    r = screen.results[-1]
    assert r["grade"] is Grade.AGAIN
    assert r["mode"] == "typed"
    assert r["typed_answer"] == "боязливый"
    assert r["overridden"] is False
    assert screen.current_card.front == "reluctant"


def test_override_allows_grading(screen, monkeypatch):
    screen.submit_answer("отказаться")
    def save(request):
        request.update(error=None, translations=[*screen.current_card.translations, request["text"]])
    screen.translationRequested.connect(save)
    def accept(window, dialog):
        dialog._on_primary()
        return True
    monkeypatch.setattr("mnemo.ui.session_screen.run_dialog", accept)
    screen.override_correct()
    assert screen.state is State.TYPED_OK
    screen.grade(Grade.AGAIN)  # недоступна
    assert screen.results == []
    screen.grade(Grade.HARD)
    assert screen.results[-1]["overridden"] is True


def test_self_check_grade_keys(screen):
    QTest.keyClick(_input(screen), Qt.Key.Key_Space)
    QTest.keyClick(screen, Qt.Key.Key_4)
    r = screen.results[-1]
    assert r["grade"] is Grade.EASY
    assert r["mode"] == "self"


def test_typo_keeps_original_input_and_normal_success(screen):
    screen.submit_answer("  сдаватсья ")
    assert screen.state is State.TYPED_OK
    assert screen._input.text() == "  сдаватсья "
    assert screen._result.text() == "Верно"
    assert "сдаватсья" not in screen.current_card.translations
    screen.grade(Grade.GOOD)
    assert screen.results[-1]["typed_answer"] == "  сдаватсья "
    assert screen.results[-1]["overridden"] is False


def test_variant_dialog_cancel_keeps_wrong_answer(screen, monkeypatch):
    screen.submit_answer("отказаться")
    before = list(screen.current_card.translations)
    def cancel(window, dialog):
        assert dialog.translation.text() == "отказаться"
        dialog.translation.setText("передумал")
        dialog.reject()
        return False
    monkeypatch.setattr("mnemo.ui.session_screen.run_dialog", cancel)
    screen.override_correct()
    assert screen.state is State.TYPED_BAD
    assert screen.current_card.translations == before
    assert screen.results == []
    assert screen._typed_answer == "отказаться"


def test_enter_after_reveal_is_good(screen):
    screen.reveal()
    QTest.keyClick(screen, Qt.Key.Key_Return)
    assert screen.results[-1]["grade"] is Grade.GOOD


def test_again_returns_card_later(screen):
    screen.forget()
    screen.next_after_wrong()
    fronts = [screen._cards[i].front for i in screen._queue]
    assert fronts.index("to give up") == 3


def test_hint_opens_column_and_hides_after_reveal(screen):
    screen.use_hint()
    screen.finish_animations()
    assert screen.hints_open == 1
    assert screen.hint_column_open
    screen.reveal()
    screen.finish_animations()
    assert not screen.hint_column_open
    screen.grade(Grade.GOOD)
    assert screen.results[-1]["hints_used"] == 1


def test_hints_limited_and_per_card(screen):
    for _ in range(5):
        screen.use_hint()
    assert screen.hints_open == 2  # у первой карточки две подсказки
    screen.reveal()
    screen.use_hint()  # после ответа игнорируется
    assert screen.hints_open == 2


def test_narrow_window_uses_inline_hints(qapp):
    s = SessionScreen(DEMO_DECK_NAME, demo_cards())
    s.resize(760, 640)
    s.show()
    s.use_hint()
    s.finish_animations()
    assert not s.hint_column_open
    assert not s._inline_hints.isHidden()
    s.close()


def test_full_session_reaches_end(screen):
    guard = 0
    while not screen.is_finished and guard < 50:
        screen.reveal()
        screen.grade(Grade.GOOD)
        guard += 1
    assert screen.is_finished
    assert len(screen.results) == len(demo_cards())


def test_finish_button_ends_session(screen):
    screen.finish()
    assert screen.is_finished
    screen.restart()
    assert screen.state is State.QUESTION


def test_forget_shows_answer_then_records_self_failure(screen):
    screen.use_hint()
    screen._input.setText("черновик")
    screen._forget_btn.click()
    assert screen.state is State.FORGOTTEN
    assert not screen._answer_box.isHidden()
    assert screen._grade_row.isHidden()
    assert screen._override_btn.isHidden()
    assert screen.results == []
    screen.override_correct()
    assert screen.state is State.FORGOTTEN
    QTest.keyClick(screen, Qt.Key.Key_Return)
    result = screen.results[-1]
    assert result["grade"] is Grade.AGAIN
    assert result["mode"] == "self"
    assert result["typed_answer"] is None
    assert result["hints_used"] == 1


def test_reveal_has_only_success_grades(screen):
    screen.reveal()
    assert set(screen._grade_buttons) == {Grade.HARD, Grade.GOOD, Grade.EASY}
    screen.grade(Grade.AGAIN)
    QTest.keyClick(screen, Qt.Key.Key_1)
    assert screen.state is State.REVEALED
    assert screen.results == []


def test_tab_hint_keeps_input_and_stops_after_reveal(screen, qapp):
    screen.activateWindow()
    screen._input.setFocus()
    qapp.processEvents()
    screen._input.setText("черновик")
    QTest.keyClick(screen._input, Qt.Key.Key_Tab)
    assert screen.hints_open == 1
    assert screen._input.text() == "черновик"
    assert screen._input.hasFocus()
    QTest.keyClick(screen._input, Qt.Key.Key_Tab)
    QTest.keyClick(screen._input, Qt.Key.Key_Tab)
    assert screen.hints_open == 2
    screen.reveal()
    assert not screen._hint_shortcut.isEnabled()
    QTest.keyClick(screen, Qt.Key.Key_Tab)
    assert screen.hints_open == 2


def test_forget_save_failure_can_retry(screen):
    def fail(result):
        result["saved"] = False
    screen.answerGiven.connect(fail)
    screen.forget()
    card = screen.current_card
    screen.next_after_wrong()
    assert screen.current_card is card
    assert screen.state is State.FORGOTTEN
    assert not screen.results
    screen.answerGiven.disconnect(fail)
    screen.next_after_wrong()
    assert len(screen.results) == 1


def test_one_forgets_from_input_and_escape_finishes(screen, qapp):
    screen.activateWindow()
    screen._input.setFocus()
    qapp.processEvents()
    screen._input.setText("черновик")
    QTest.keyClick(screen._input, Qt.Key.Key_1)
    assert screen.state is State.FORGOTTEN
    assert screen._input.text() == "черновик"
    assert not screen._forget_shortcut.isEnabled()
    QTest.keyClick(screen, Qt.Key.Key_Return)
    assert screen.results[-1]["grade"] is Grade.AGAIN
    QTest.keyClick(screen._input, Qt.Key.Key_Escape)
    assert screen.is_finished
    assert not screen._finish_shortcut.isEnabled()


def test_escape_on_first_question_exits(screen, qapp):
    exits = []
    screen.exitRequested.connect(lambda: exits.append(True))
    screen.activateWindow()
    screen._input.setFocus()
    qapp.processEvents()
    QTest.keyClick(screen._input, Qt.Key.Key_Escape)
    assert exits == [True]
    assert not screen.results


def test_long_question_scrolls_instead_of_overlapping(qapp):
    from mnemo.ui.demo_data import DemoCard
    from mnemo.ui.theme import apply_theme
    apply_theme(qapp)
    s = SessionScreen("Длинная карточка", [DemoCard(
        "a long expression with several words " * 8, ["перевод"],
        hints=["Длинная подсказка " * 35],
    )])
    s.resize(760, 600)
    s.show()
    s.use_hint()
    s.finish_animations()
    for _ in range(4):
        qapp.processEvents()
    row = s._front_row
    assert row.label.font().pixelSize() == 34
    assert row.height() >= row.label.heightForWidth(row.label.width())
    assert row.geometry().bottom() < s._inline_hints_wrap.geometry().top()
    assert s._inline_hints_wrap.geometry().bottom() < s._input_wrap.geometry().top()
    assert s._study_scroll.verticalScrollBar().maximum() > 0
    s._study_scroll.ensureWidgetVisible(s._forget_btn)
    qapp.processEvents()
    assert s._study_scroll.verticalScrollBar().value() > 0
    s.close()
