import json

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import QLabel

from mnemo.services import Library
from mnemo.storage import Database
from mnemo.ui.card_text import set_front_text
from mnemo.ui.demo_data import DemoCard
from mnemo.ui.import_dialog import ImportDialog, load_prompt
from mnemo.ui.session_screen import SessionScreen, State
from mnemo.ui.main_window import MainWindow
from mnemo.domain.models import AnswerMode, Grade


def test_front_highlights_only_target_and_escapes_card_html(qapp):
    label = QLabel()
    set_front_text(label, "[[short]] {hair|nose} <img src='remote'> & <b>text</b>")
    doc = QTextDocument()
    doc.setHtml(label.text())
    assert doc.toPlainText() == "short [hair / nose] <img src='remote'> & <b>text</b>"
    assert doc.find("short").charFormat().fontWeight() == 700
    assert doc.find("hair").charFormat().fontWeight() == 400
    assert label.accessibleName() == doc.toPlainText()
    set_front_text(label, "<b>ordinary</b>")
    assert label.textFormat() == Qt.TextFormat.PlainText
    assert label.text() == "<b>ordinary</b>"
    set_front_text(label, "[[broken")
    assert label.text() == "[[broken"
    assert label.textFormat() == Qt.TextFormat.PlainText


@pytest.mark.parametrize("front,translations,answer,caption", [
    ("[[short]] {hair|nose}", ["короткий (о длине)"], "короткий", "СЛОВАРНОЙ"),
    ("thin lips", ["тонкие губы"], "тонкие губы", "ПЕРЕВЕДИТЕ"),
    ("[[thin lips]]", ["тонкие губы"], "тонкие губы", "ЦЕЛИКОМ"),  # legacy cards remain valid
    ("look old for one's age", ["Выглядеть старше {своих лет|своего возраста}"],
     "Выглядеть старше своего возраста", "ПЕРЕВЕДИТЕ"),
    ("[[put off]] the meeting", ["{отложить|перенести} (встречу)"], "перенести", "ЦЕЛИКОМ"),
    ("You look good for your age", ["Ты {хорошо|отлично} выглядишь {для своих лет|для своего возраста}"],
     "Ты отлично выглядишь для своего возраста", "ПЕРЕВЕДИТЕ"),
])
def test_session_displays_markup_and_accepts_a_branch(qapp, front, translations, answer, caption):
    screen = SessionScreen("Разметка", [DemoCard(front, translations)])
    screen.resize(760, 600)
    screen.show()
    qapp.processEvents()
    assert caption in screen._caption.text().upper()
    assert "{" not in screen._translation.text()
    assert "|" not in screen._translation.text()
    assert "[" not in screen._translation.text()
    if front == "look old for one's age":
        assert screen._translation.text() == "Выглядеть старше своих лет / своего возраста"
    screen.submit_answer(answer)
    assert screen.state is State.TYPED_OK
    assert screen.current_card.front == front
    assert screen.current_card.translations == translations
    screen.close()


def test_import_preview_and_storage_preserve_raw_notation(qapp):
    lib = Library(Database(":memory:"))
    front = "[[short]] {hair|nose}"
    raw = json.dumps({"schema_version": 1, "deck": {"name": "Разметка"}, "cards": [
        {"front": front, "translations": ["{короткий|недлинный} (о длине)"]},
        {"front": "[[bad]] {a|}", "translations": ["ошибка"]},
    ]})
    dlg = ImportDialog(None, lib)
    dlg.set_source_text(raw)
    assert "short [hair / nose]" in dlg.sample.text()
    assert "короткий / недлинный" in dlg.sample.text()
    assert "[короткий" not in dlg.sample.text()
    assert len(dlg._parse.errors) == 1
    dlg._on_primary()
    assert dlg.report.added == 1
    deck = lib.deck_summaries()[0].deck
    stored = lib.cards.list_by_deck(deck.id)[0]
    assert stored.front == front
    assert stored.translations == ["{короткий|недлинный} (о длине)"]
    exported = json.loads(lib.export_deck(deck.id))
    assert exported["cards"][0]["front"] == front
    assert exported["cards"][0]["translations"] == stored.translations
    lib.close()


def test_deck_stats_and_editor_use_display_or_raw_text_as_needed(qapp):
    lib = Library(Database(":memory:"))
    deck = lib.create_deck("Разметка")
    card = lib.save_card(deck.id, "[[short]] {hair|nose}", ["{короткий|недлинный}"])
    lib.record_review(card.id, Grade.AGAIN, AnswerMode.SELF)
    win = MainWindow(lib)
    win.show_deck(deck.id)
    word = win.deck_screen.findChild(QLabel, "CardWord")
    assert word.accessibleName() == "short [hair / nose]"
    assert win.deck_screen.findChild(QLabel, "CardTranslations").text() == "короткий / недлинный"
    win.show_stats()
    assert win.stats_screen.findChild(QLabel, "CardWord").accessibleName() == "short [hair / nose]"
    win.edit_card(card.id)
    assert win.editor_screen.front.text() == card.front
    assert win.editor_screen.translations.values() == card.translations
    win.close()
    lib.close()


def test_copied_prompt_contains_new_dialect():
    prompt = load_prompt()
    assert "[[short]] {hair|nose}" in prompt
    assert "grey hair" in prompt
    assert "256" in prompt
    assert "## Что проверить перед внедрением" not in prompt
