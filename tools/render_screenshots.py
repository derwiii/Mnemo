"""Рисует PNG-скриншоты экранов без реального экрана (на временной базе в памяти).

Запуск из корня проекта:
    PYTHONPATH=src python tools/render_screenshots.py screenshots
"""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402
from PyQt6.QtGui import QFontDatabase  # noqa: E402

from mnemo.domain.models import CardStatus, Example, utcnow  # noqa: E402
from mnemo.services import Library  # noqa: E402
from mnemo.storage import Database  # noqa: E402
from mnemo.ui.main_window import MainWindow  # noqa: E402
from mnemo.ui.session_screen import Grade  # noqa: E402
from mnemo.ui.theme import setup_app  # noqa: E402
from mnemo.ui.dialogs import CoverDialog, DeckDialog  # noqa: E402
from mnemo.ui.import_dialog import ImportDialog  # noqa: E402


def seed(library: Library) -> str:
    deck = library.create_deck("Английский: фразовые глаголы", "", "английский", "русский")
    words = [
        ("to give up", ["сдаваться", "бросать (привычку)"], ["Начинается на «сда…»", "Противоположность слову «продолжать»"]),
        ("to come across", ["случайно наткнуться"], ["Глагол с предлогом"]),
        ("to look forward to", ["с нетерпением ждать"], []),
        ("hedgehog", ["ёж", "ёжик"], []),
        ("ubiquitous", ["вездесущий", "повсеместный"], ["Прилагательное"]),
    ]
    ids = []
    for front, translations, hints in words:
        card = library.save_card(
            deck.id, front, translations, [Example(f"Example with {front}.", "Пример.")], hints
        )
        ids.append(card.id)
    state = library.states.get(ids[3])
    state.status, state.interval_days, state.due_at = CardStatus.REVIEW, 30.0, utcnow() + timedelta(days=20)
    library.states.save(state)
    state = library.states.get(ids[4])
    state.status, state.interval_days = CardStatus.LEARNING, 1.0
    library.states.save(state)
    library.create_deck("Немецкий: бытовые слова", "", "немецкий", "русский")
    return deck.id


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    # Windows offscreen не перечисляет системные шрифты автоматически.
    if os.name == "nt" and not QFontDatabase.families():
        for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
            font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))
    setup_app(app)
    library = Library(Database(":memory:"))

    window = MainWindow(library)
    window.resize(1000, 720)
    window.show()

    def shot(name: str) -> None:
        if window.session is not None:
            window.session.finish_animations()
        app.processEvents()
        app.processEvents()
        window.repaint()
        window.grab().save(str(out / f"{name}.png"))

    shot("00_decks_empty")
    deck_id = seed(library)
    window.show_decks()
    shot("01_decks")
    window.show_deck(deck_id)
    shot("02_deck")
    window.deck_screen.set_search("ёж")
    shot("03_deck_search")
    window.deck_screen.set_search("zzz")
    shot("04_deck_nothing_found")
    window.add_card(deck_id)
    shot("05_editor_new")
    ed = window.editor_screen
    ed.front.setText("to give up")
    ed.translations.set_values(["сдаваться", ""])
    ed.save(False)
    shot("06_editor_duplicate_warning")
    ed.front.setText("")
    ed.save(False)
    shot("07_editor_errors")
    window.show_deck(deck_id)
    window.edit_card(library.list_cards(deck_id)[0].card.id)
    shot("08_editor_edit")
    window.show_deck(deck_id)
    window.start_session(deck_id)
    # Show the actual hint state reliably despite the randomized session order.
    session = window.session
    hinted = next(i for i in session._queue if session._cards[i].hints)
    session._queue.remove(hinted)
    session._queue.insert(0, hinted)
    session._show_card()
    shot("09_session")
    window.session.use_hint()
    shot("10_session_hint")
    window.session.reveal()
    shot("11_session_answer")
    window.session.grade(Grade.GOOD)
    window.session.finish()
    shot("12_session_end")
    window.show_session_setup()
    shot("13_session_setup")
    window._setup.random_cards.setChecked(True)
    window._setup.count.setText("999")
    shot("14_session_setup_invalid")
    window.start_free_session(deck_id)
    window.session.forget()
    shot("29_forgotten_answer")
    window.session.next_after_wrong()
    while not window.session.is_finished:
        window.session.reveal()
        window.session.grade(Grade.HARD)
    shot("15_free_session_end")
    window.session.repeat_errors()
    shot("16_repeat_errors")
    window.show_stats()
    shot("17_statistics")
    window.resize(760, 600)
    shot("18_statistics_narrow")
    window.show_deck(deck_id)
    shot("19_deck_narrow")
    window.show_decks()
    shot("20_decks_narrow")
    window.add_card(deck_id)
    shot("21_editor_narrow")
    window.start_free_session(deck_id)
    shot("22_session_narrow")
    window.session.reveal()
    shot("23_answer_narrow")
    window.resize(1000, 720)
    window.show_decks()
    for name, dialog in (
        ("24_cover", CoverDialog(window, "route", lambda _cover: None)),
        ("25_create", DeckDialog(window, "Создать колоду", "Создать", lambda values: None)),
        ("26_import", ImportDialog(window, library, deck_id)),
    ):
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(out / f"{name}.png"))
        dialog.close()
    window.show_deck(deck_id)
    app.processEvents()
    window.deck_screen.settings_btn.click()
    app.processEvents()
    window.deck_screen.settings_menu.grab().save(str(out / "27_deck_settings.png"))
    window.deck_screen.settings_menu.hide()
    from PyQt6.QtWidgets import QToolTip
    target = window._chrome.bar.close_btn
    QToolTip.showText(target.mapToGlobal(target.rect().bottomLeft()), target.toolTip(), target)
    app.processEvents()
    for popup in app.topLevelWidgets():
        if popup.objectName() == "qtooltip_label":
            popup.grab().save(str(out / "28_tooltip.png"))
    QToolTip.hideText()
    long_deck = library.create_deck("Проверка длинного текста")
    library.save_card(long_deck.id,
        "to find yourself in a situation where you have to make a difficult decision",
        ["оказаться в ситуации, требующей трудного решения"],
        hints=["Попробуйте вспомнить выражение по частям. " * 8])
    window.resize(760, 600)
    window.start_free_session(long_deck.id)
    window.session.use_hint()
    shot("30_long_question")
    window.session._study_scroll.ensureWidgetVisible(window.session._forget_btn)
    shot("31_long_question_actions")
    window.close()
    library.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "screenshots")
