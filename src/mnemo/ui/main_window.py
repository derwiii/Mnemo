"""Главное окно: навигация между экранами (docs/specs/design.md, раздел 3)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication, QFileDialog, QMainWindow, QStackedWidget, QWidget

from mnemo.services import Library
from mnemo.settings import (
    APP_NAME,
    WINDOW_HEIGHT,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
    WINDOW_WIDTH,
)
from mnemo.domain.models import AnswerMode, Card
from mnemo.domain.markup import display_text
from mnemo.storage import DuplicateDeckNameError, StorageError
from mnemo.domain.validation import ValidationError
from mnemo.ui import strings as S
from mnemo.ui.card_editor import EditorScreen
from mnemo.ui.deck_screen import DeckScreen
from mnemo.ui.decks_screen import DecksScreen
from mnemo.ui.dialogs import DeckDialog, DeckValues, CoverDialog
from mnemo.ui.import_dialog import ImportDialog
from mnemo.ui.session_cards import to_session_card
from mnemo.ui.session_screen import SessionScreen
from mnemo.ui.session_setup import SessionSetup
from mnemo.ui.stats_screen import StatsScreen
from mnemo.ui.text import cards_count
from mnemo.ui.theme import THEME_NAMES, apply_theme
from mnemo.ui.widgets import RoundedMenu, confirm, info, run_dialog
from mnemo.ui.window_chrome import WindowChrome
from mnemo.ui.windows_frame import SC_MAXIMIZE, SC_MINIMIZE, SC_RESTORE, send_system_command, uses_custom_client_area
from mnemo.ui.inbox_screen import InboxScreen


class MainWindow(QMainWindow):
    def __init__(self, library: Library) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self._library = library
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, library.preferences.get("appearance_theme"))

        self._stack = QStackedWidget()
        self._stack.setObjectName("Root")
        self.setCentralWidget(self._stack)

        self._decks = DecksScreen(library)
        self._deck = DeckScreen(library)
        self._editor = EditorScreen(library)
        self._stats = StatsScreen(library)
        self._setup = SessionSetup(library)
        self.inbox_screen = InboxScreen(library)
        self.desktop = None
        self._session: SessionScreen | None = None
        self._session_origin: str | None = None  # id колоды, откуда запущена сессия, или None
        self._session_from_pool = False
        for page in (self._decks, self._deck, self._editor, self._stats, self._setup, self.inbox_screen):
            self._stack.addWidget(page)

        self._wire()
        self._chrome = WindowChrome(self, self._stack)
        self._stack.currentChanged.connect(lambda _i: self._chrome.attach())
        self.show_decks()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        if hasattr(self, "_chrome"):
            self._chrome.relayout()

    def nativeEvent(self, event_type, message):
        return event_type == b"windows_generic_MSG" and uses_custom_client_area(message), 0

    def _show_window_state(self, command, fallback) -> None:
        if self.isVisible() and QApplication.platformName() == "windows":
            send_system_command(int(self.winId()), command)
        else:
            fallback()

    def showMinimized(self) -> None:
        self._show_window_state(SC_MINIMIZE, super().showMinimized)

    def showMaximized(self) -> None:
        self._show_window_state(SC_MAXIMIZE, super().showMaximized)

    def showNormal(self) -> None:
        self._show_window_state(SC_RESTORE, super().showNormal)

    def changeEvent(self, event) -> None:  # noqa: ANN001
        super().changeEvent(event)
        if (
            event is not None and event.type() == QEvent.Type.WindowActivate
            and hasattr(self, "_chrome") and self.current_page is self._decks
        ):
            self._decks.refresh()
        if event is not None and event.type() == QEvent.Type.WindowStateChange and hasattr(self, "_chrome"):
            self._chrome.relayout()

    # ------------------------------------------------------------ связи

    def _wire(self) -> None:
        d = self._decks
        d.inboxRequested.connect(self.show_inbox)
        self.inbox_screen.settingsRequested.connect(self.show_desktop_settings)
        self.inbox_screen.back.connect(self._leave_inbox)
        self.inbox_screen.changed.connect(self._decks.refresh)
        d.openDeck.connect(self.show_deck)
        d.openDeckFromRail.connect(lambda deck_id: self.show_deck(deck_id, focus_deck=False))
        d.study.connect(self.start_session)
        d.repeatAll.connect(self.start_free_session)
        d.createRequested.connect(self.create_deck)
        d.renameRequested.connect(self.rename_deck)
        d.deleteRequested.connect(self.delete_deck)
        d.importRequested.connect(lambda: self.open_import(None))
        d.exportRequested.connect(self.export_deck)
        d.statsRequested.connect(self.show_stats)
        d.poolRequested.connect(self.show_session_setup)
        d.coverRequested.connect(self.choose_cover)
        d.themeRequested.connect(self.choose_theme)
        d.saveFailed.connect(lambda error: info(self, S.SAVE_FAILED_TITLE, error))
        self._setup.back.connect(self.show_decks)
        self._setup.startRequested.connect(self.start_pool_session)
        self._stats.back.connect(self.show_decks)
        self._stats.editCard.connect(self.edit_card)

        k = self._deck
        k.back.connect(self.show_decks)
        k.study.connect(self.start_session)
        k.repeatAll.connect(self.start_free_session)
        k.addCard.connect(self.add_card)
        k.editCard.connect(self.edit_card)
        k.deleteCard.connect(self.delete_card)
        k.importRequested.connect(self.open_import)
        k.exportRequested.connect(self.export_deck)
        k.coverRequested.connect(self.choose_cover)
        k.renameRequested.connect(self.rename_deck)
        k.deleteRequested.connect(self.delete_deck)

        e = self._editor
        e.closeRequested.connect(self.close_editor)
        e.saved.connect(self._on_card_saved)

    # ------------------------------------------------------------ экраны

    def closeEvent(self, event):
        if self.desktop is not None and self.desktop.hide_to_tray():
            event.ignore()
            return
        super().closeEvent(event)

    def show_inbox(self, entry_id=None):
        if self.current_page is self.inbox_screen and not self.inbox_screen.can_leave():
            return
        self.inbox_screen.refresh(entry_id)
        self._stack.setCurrentWidget(self.inbox_screen)

    def _leave_inbox(self):
        if self._session is not None:
            self._stack.setCurrentWidget(self._session)
        else:
            self.show_decks()

    def show_desktop_settings(self):
        if self.desktop is not None:
            self.desktop.show_settings()
        else:
            info(self, "Настройки", "Настройки трея доступны при обычном запуске приложения.")

    @property
    def current_page(self) -> QWidget | None:
        return self._stack.currentWidget()

    @property
    def decks_screen(self) -> DecksScreen:
        return self._decks

    @property
    def deck_screen(self) -> DeckScreen:
        return self._deck

    @property
    def editor_screen(self) -> EditorScreen:
        return self._editor

    @property
    def session(self) -> SessionScreen | None:
        return self._session

    def show_decks(self) -> None:
        self._drop_session()
        self._decks.refresh()
        self._stack.setCurrentWidget(self._decks)

    def show_stats(self) -> None:
        self._drop_session()
        self._stats.refresh()
        self._stats.setFocus()
        self._stack.setCurrentWidget(self._stats)

    @property
    def stats_screen(self) -> StatsScreen:
        return self._stats

    def show_deck(self, deck_id: str, *, focus_deck: bool = True) -> None:
        self._drop_session()
        self._decks.refresh()
        if focus_deck:
            self._decks.select(deck_id)
        self._deck.show_deck(deck_id)
        self._stack.setCurrentWidget(self._deck)

    # ------------------------------------------------------------ колоды

    def choose_theme(self):
        app = QApplication.instance()
        anchor = self._decks.appearance_btn
        menu = RoundedMenu(anchor)
        for key, name in THEME_NAMES.items():
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(key == app.mnemo_theme)
            action.triggered.connect(lambda _checked=False, palette=key: self._set_theme(palette))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        menu.deleteLater()

    def _set_theme(self, name):
        try:
            self._library.preferences.set("appearance_theme", name)
        except sqlite3.Error as exc:
            info(self, S.SAVE_FAILED_TITLE, f"Не удалось сохранить палитру: {exc}")
            return
        apply_theme(QApplication.instance(), name)

    def choose_cover(self, deck_id: str) -> None:
        if self._library.decks.get(deck_id) is None:
            return

        def submit(cover_id):
            try:
                self._library.set_deck_cover(deck_id, cover_id)
            except sqlite3.Error as exc:
                return f"Не удалось сохранить обложку: {exc}"
            self._decks.update_cover(deck_id)
            if self._deck.deck_id == deck_id:
                self._deck.cover.configure(cover_id)
            return None

        run_dialog(self, CoverDialog(self, self._library.deck_cover(deck_id), submit))

    def create_deck(self) -> None:
        created: list[str] = []

        def submit(values: DeckValues) -> str | None:
            try:
                deck = self._library.create_deck(
                    values.name, values.description, values.source_language, values.target_language
                )
            except ValidationError as exc:
                return exc.problems[0]
            except DuplicateDeckNameError:
                return S.ERROR_DECK_EXISTS
            created.append(deck.id)
            return None

        dialog = DeckDialog(self, S.DIALOG_CREATE_DECK, S.BTN_CREATE, submit)
        if run_dialog(self, dialog) and created:
            self.show_deck(created[0])

    def rename_deck(self, deck_id: str) -> None:
        deck = self._library.decks.get(deck_id)
        if deck is None:
            return

        def submit(values: DeckValues) -> str | None:
            try:
                self._library.update_deck(deck_id, values.name, values.description)
            except ValidationError as exc:
                return exc.problems[0]
            except DuplicateDeckNameError:
                return S.ERROR_DECK_EXISTS
            return None

        dialog = DeckDialog(self, S.DIALOG_RENAME_DECK, S.BTN_SAVE, submit, deck)
        if run_dialog(self, dialog):
            self._decks.refresh()
            if self._deck.deck_id == deck_id:
                self._deck.refresh()

    def delete_deck(self, deck_id: str) -> None:
        summary = self._library.deck_summary(deck_id)
        if summary is None:
            return
        text = S.DELETE_DECK_TEXT.format(
            name=summary.deck.name, cards=cards_count(summary.card_count)
        )
        if confirm(self, S.DIALOG_DELETE_DECK, text, S.BTN_DELETE, danger=True):
            self._library.delete_deck(deck_id)
            self.show_decks()

    # ------------------------------------------------------------ импорт и экспорт

    def open_import(self, deck_id: str | None = None) -> None:
        dialog = ImportDialog(self, self._library, deck_id)
        if not run_dialog(self, dialog) or dialog.report is None:
            return
        report = dialog.report
        info(
            self,
            S.IMPORT_DONE_TITLE,
            S.IMPORT_DONE_TEXT.format(
                added=report.added,
                updated=report.updated,
                skipped=report.skipped,
                errors=report.errors,
            ),
        )
        self.show_deck(report.deck_id, focus_deck=deck_id is None)

    def _choose_save_path(self, default_name: str) -> str:
        path, _ = QFileDialog.getSaveFileName(
            self, S.EXPORT_DIALOG_TITLE, default_name, S.FILE_FILTER
        )
        return path

    def export_deck(self, deck_id: str) -> None:
        deck = self._library.decks.get(deck_id)
        if deck is None:
            return
        safe = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in deck.name).strip() or "deck"
        path = self._choose_save_path(f"{safe}.json")
        if not path:
            return
        try:
            Path(path).write_text(self._library.export_deck(deck_id), encoding="utf-8")
        except OSError as exc:
            info(self, S.EXPORT_FAILED_TITLE, str(exc.strerror or exc))
            return
        info(self, S.EXPORT_DONE_TITLE, S.EXPORT_DONE_TEXT.format(name=deck.name, path=path))

    # ------------------------------------------------------------ карточки

    def add_card(self, deck_id: str) -> None:
        self._editor.start_new(deck_id)
        self._stack.setCurrentWidget(self._editor)

    def edit_card(self, card_id: str) -> None:
        if self._editor.start_edit(card_id):
            self._stack.setCurrentWidget(self._editor)

    def delete_card(self, card_id: str) -> None:
        card = self._library.cards.get(card_id)
        if card is None:
            return
        text = S.DELETE_CARD_TEXT.format(front=display_text(card.front, front=True))
        if confirm(self, S.DIALOG_DELETE_CARD, text, S.BTN_DELETE, danger=True):
            self._library.delete_card(card_id)
            self._deck.refresh()

    def close_editor(self) -> None:
        """Выход из редактора (Отмена или «назад»); при несохранённых правках спрашивает."""
        if self._editor.is_dirty() and not confirm(
            self,
            S.DIALOG_DISCARD,
            S.DISCARD_TEXT,
            S.BTN_DISCARD,
            danger=True,
            cancel_text=S.BTN_KEEP_EDITING,
        ):
            return
        deck_id = self._editor.deck_id
        if deck_id:
            self.show_deck(deck_id, focus_deck=False)
        else:
            self.show_decks()

    def _on_card_saved(self, add_another: bool) -> None:
        if not add_another and self._editor.deck_id:
            self.show_deck(self._editor.deck_id, focus_deck=False)

    # ------------------------------------------------------------ сессия

    def start_session(self, deck_id: str | None) -> None:
        cards = self._library.session_queue(deck_id)
        self._open_session(deck_id, cards)

    def show_session_setup(self) -> None:
        self._drop_session()
        self._setup.refresh()
        self._stack.setCurrentWidget(self._setup)

    def start_pool_session(self, count: int | None) -> None:
        cards = self._library.free_session_queue(count=count)
        self._open_session(None, cards, free=True, from_pool=True)

    def start_free_session(self, deck_id: str) -> None:
        self._open_session(deck_id, self._library.free_session_queue(deck_id), free=True)

    def _open_session(
        self, deck_id: str | None, cards: list[Card],
        *, free: bool = False, from_pool: bool = False,
    ) -> None:
        if not cards:
            return
        if deck_id is None:
            name = "Все колоды"
        else:
            deck = self._library.decks.get(deck_id)
            name = deck.name if deck else ""
        from_home = self.current_page is self._decks
        self._drop_session()
        self._session_origin = None if from_home else deck_id
        self._session_from_pool = from_pool
        self._session = SessionScreen(
            name, [to_session_card(c) for c in cards], allow_restart=False,
            allow_error_repeat=free, free_practice=free,
        )
        # Свободные результаты остаются только в SessionScreen, без БД и планировщика.
        if not free:
            self._session.answerGiven.connect(self._record_answer)
        self._session.translationRequested.connect(self._add_session_translation)
        self._session.exitRequested.connect(self._end_session)
        self._stack.addWidget(self._session)
        self._stack.setCurrentWidget(self._session)
        self._session.setFocus()
        self._session.entrance.start()

    def _add_session_translation(self, request: dict) -> None:
        try:
            card = self._library.add_translation(request["card_id"], request["text"])
        except (ValueError, LookupError, StorageError, sqlite3.Error) as exc:
            request["error"] = str(exc)
            return
        request["translations"] = card.translations
        request["error"] = None

    def _record_answer(self, data: dict) -> None:
        """Основная оценка сразу пишется в журнал и расписание: прерывание ничего не теряет (FR-S7)."""
        data["saved"] = False
        card_id = data.get("card_id")
        if not card_id:
            return
        mode = AnswerMode.TYPED if data["mode"] == "typed" else AnswerMode.SELF
        try:
            self._library.record_review(
                card_id,
                data["grade"],
                mode,
                typed_answer=data.get("typed_answer"),
                overridden=bool(data.get("overridden")),
                hints_used=int(data.get("hints_used", 0)),
                response_time_ms=int(data.get("response_time_ms", 0)),
            )
            data["saved"] = True
        except (StorageError, sqlite3.Error) as exc:
            info(self, S.SAVE_FAILED_TITLE, S.SAVE_FAILED_TEXT.format(reason=exc))

    def _end_session(self) -> None:
        origin = self._session_origin
        if self._session_from_pool:
            self.show_session_setup()
        elif origin is not None and self._library.decks.get(origin) is not None:
            self.show_deck(origin, focus_deck=False)
        else:
            self.show_decks()

    def _drop_session(self) -> None:
        if self._session is not None:
            self._stack.removeWidget(self._session)
            self._session.deleteLater()
            self._session = None
