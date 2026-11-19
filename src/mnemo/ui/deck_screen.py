"""Экран «Колода»: список карточек и поиск (docs/specs/design.md, раздел 9; docs/specs/cards.md)."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from mnemo.services import CardRow as CardData
from mnemo.services import DeckSummary, DisplayStatus, Library
from mnemo.settings import CARDS_PAGE_SIZE
from mnemo.ui import strings as S
from mnemo.ui.text import cards_count
from mnemo.ui.card_text import set_front_text
from mnemo.domain.markup import translation_text
from mnemo.ui.widgets import button, field, label, scroll_area, set_prop, icon_button, RoundedMenu
from mnemo.ui.identity import CoverTile, StackArt

_STATUS_TEXT = {
    DisplayStatus.NEW: S.STATUS_NEW,
    DisplayStatus.LEARNING: S.STATUS_LEARNING,
    DisplayStatus.LEARNED: S.STATUS_LEARNED,
}


class CardRowWidget(QFrame):
    editRequested = pyqtSignal(str)
    deleteRequested = pyqtSignal(str)

    def __init__(self, data: CardData) -> None:
        super().__init__()
        self.setObjectName("CardRow")
        self.card_id = data.card.id
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 13, 22, 13)
        lay.setSpacing(16)

        word = label("", "CardWord")
        self._word = word
        word.setMinimumWidth(140)
        word.setMaximumWidth(260)
        word.setWordWrap(True)
        translations = label("", "CardTranslations")
        self._translations = translations
        translations.setTextFormat(Qt.TextFormat.PlainText)
        translations.setWordWrap(True)
        translations.setMinimumWidth(0)
        status = label("", "Status")
        self._status = status
        status.setFixedWidth(72)
        status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.edit_btn = icon_button("edit", S.BTN_EDIT)
        self.delete_btn = icon_button("delete", S.BTN_DELETE)
        self.edit_btn.clicked.connect(lambda: self.editRequested.emit(self.card_id))
        self.delete_btn.clicked.connect(lambda: self.deleteRequested.emit(self.card_id))
        lay.addWidget(word, 2)
        lay.addWidget(translations, 3)
        lay.addWidget(status)
        lay.addWidget(self.edit_btn)
        lay.addWidget(self.delete_btn)
        self._displayed: tuple | None = None
        self.update_data(data)

    def update_data(self, data: CardData) -> None:
        """Обновляет изменившиеся поля, сохраняя строку и её кнопки."""
        displayed = (data.card.front, tuple(data.card.translations), data.status)
        previous = self._displayed
        if previous is None or previous[0] != displayed[0]:
            set_front_text(self._word, data.card.front)
        if previous is None or previous[1] != displayed[1]:
            self._translations.setText(translation_text(data.card.translations))
        if previous is None or previous[2] != displayed[2]:
            self._status.setText(_STATUS_TEXT[data.status])
            set_prop(self._status, "kind", data.status.value)
        self._displayed = displayed


class DeckScreen(QWidget):
    back = pyqtSignal()
    study = pyqtSignal(str)
    repeatAll = pyqtSignal(str)
    addCard = pyqtSignal(str)
    editCard = pyqtSignal(str)
    deleteCard = pyqtSignal(str)
    importRequested = pyqtSignal(str)
    exportRequested = pyqtSignal(str)
    coverRequested = pyqtSignal(str)
    renameRequested = pyqtSignal(str)
    deleteRequested = pyqtSignal(str)

    def __init__(self, library: Library) -> None:
        super().__init__()
        self._library = library
        self._deck_id: str | None = None
        self._limit = CARDS_PAGE_SIZE
        self._summary: DeckSummary | None = None
        self._row_widgets: dict[str, CardRowWidget] = {}
        self._pending_position: tuple[list[str], int, int] | None = None
        self._position_passes = 0
        self._position_timer = QTimer(self)
        self._position_timer.setSingleShot(True)
        self._position_timer.timeout.connect(self._restore_position)

        root = QVBoxLayout(self)
        root.setContentsMargins(56, 24, 56, 26)
        root.setSpacing(0)

        top = QHBoxLayout()
        self.back_btn = button(S.BACK_TO_DECKS, "back", focus=True)
        self.back_btn.clicked.connect(self.back.emit)
        self.study_btn = button("", "primary")
        self.study_btn.clicked.connect(self._on_study)
        top.addWidget(self.back_btn)
        top.addStretch(1)
        self.settings_btn = icon_button("settings", "Настройки колоды")
        self.settings_menu = RoundedMenu(self)
        self.rename_action = self.settings_menu.addAction(S.MENU_RENAME, lambda: self.renameRequested.emit(self._deck_id))
        self.cover_action = self.settings_menu.addAction("Обложка колоды", lambda: self.coverRequested.emit(self._deck_id))
        self.settings_menu.addSeparator()
        self.import_action = self.settings_menu.addAction(S.BTN_IMPORT_TO_DECK, self._on_import)
        self.export_action = self.settings_menu.addAction(S.MENU_EXPORT, self._on_export)
        self.settings_menu.addSeparator()
        self.delete_action = self.settings_menu.addAction(S.MENU_DELETE, lambda: self.deleteRequested.emit(self._deck_id))
        self.settings_btn.clicked.connect(lambda: self.settings_menu.popup(self.settings_btn.mapToGlobal(self.settings_btn.rect().bottomLeft())))
        top.addWidget(self.settings_btn)
        top.addSpacing(10)
        top.addWidget(self.study_btn)
        self.header = top
        root.addLayout(top)

        root.addSpacing(26)
        self._title = label("", "Heading")
        self._meta = label("", "Meta")
        self._title.setWordWrap(True)
        title_row = QHBoxLayout()
        title_row.setSpacing(20)
        self.cover = CoverTile()
        title_row.addWidget(self.cover)
        title_row.addWidget(self._title, 1)
        root.addLayout(title_row)
        root.addSpacing(6)
        root.addWidget(self._meta)

        root.addSpacing(28)
        self.repeat_btn = button(S.BTN_REPEAT_DECK, "secondary")
        self.repeat_btn.clicked.connect(
            lambda: self.repeatAll.emit(self._deck_id) if self._deck_id else None
        )
        root.addWidget(self.repeat_btn, 0, Qt.AlignmentFlag.AlignLeft)
        root.addSpacing(16)
        controls = QHBoxLayout()
        controls.setSpacing(18)
        self.search = field(S.SEARCH_PLACEHOLDER)
        self.search.setMinimumWidth(140)
        self.search.setMaximumWidth(380)
        self.search.setClearButtonEnabled(False)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._apply_search)
        self.search.textChanged.connect(lambda _text: self._timer.start())
        self.add_btn = button(S.BTN_ADD_CARD, "secondary")
        self.add_btn.clicked.connect(self._on_add)
        controls.addWidget(self.search, 2)
        controls.addStretch(1)
        controls.addWidget(self.add_btn)
        root.addLayout(controls)
        root.addSpacing(18)

        # список
        self._list_view = QWidget()
        list_lay = QVBoxLayout(self._list_view)
        list_lay.setContentsMargins(0, 0, 0, 0)
        list_lay.setSpacing(8)
        self._rows_host = QWidget()
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(6)
        self.column_headers = QWidget()
        header = QHBoxLayout(self.column_headers)
        header.setContentsMargins(22, 4, 22, 4)
        header.setSpacing(16)
        word_header = label("Слово", "ColumnHeader")
        word_header.setMinimumWidth(140)
        word_header.setMaximumWidth(260)
        header.addWidget(word_header, 2)
        header.addWidget(label("Перевод", "ColumnHeader"), 3)
        status_header = label("Статус", "ColumnHeader")
        status_header.setFixedWidth(72)
        status_header.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(status_header)
        for _ in range(2):
            placeholder = QWidget()
            placeholder.setFixedWidth(36)
            header.addWidget(placeholder)
        self._rows.addWidget(self.column_headers)
        self._rows.addStretch(1)
        self._scroll = scroll_area(self._rows_host)
        list_lay.addWidget(self._scroll, 1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        self._shown = label("", "Meta")
        self.more_btn = button(S.BTN_SHOW_MORE, "textsmall")
        self.more_btn.clicked.connect(self._show_more)
        footer.addWidget(self._shown)
        footer.addWidget(self.more_btn)
        footer.addStretch(1)
        list_lay.addLayout(footer)
        root.addWidget(self._list_view, 1)

        # пустые состояния
        self._empty = QWidget()
        empty = QVBoxLayout(self._empty)
        empty.addStretch(2)
        art = StackArt()
        art.setFixedSize(180, 110)
        empty.addWidget(art, 0, Qt.AlignmentFlag.AlignHCenter)
        self._empty_title = label("", "EmptyTitle")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.addWidget(self._empty_title)
        empty.addSpacing(24)
        self._empty_actions = QWidget()
        actions = QHBoxLayout(self._empty_actions)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch(1)
        self.empty_add_btn = button(S.BTN_ADD_CARD, "secondary")
        self.empty_add_btn.clicked.connect(self._on_add)
        self.empty_import_btn = button(S.BTN_IMPORT_TO_DECK, "text")
        self.empty_import_btn.clicked.connect(self._on_import)
        actions.addWidget(self.empty_add_btn)
        actions.addWidget(self.empty_import_btn)
        actions.addStretch(1)
        empty.addWidget(self._empty_actions)
        empty.addStretch(3)
        root.addWidget(self._empty, 1)

    # ------------------------------------------------------------ данные

    @property
    def deck_id(self) -> str | None:
        return self._deck_id

    def show_deck(self, deck_id: str) -> None:
        self._timer.stop()
        if deck_id != self._deck_id:
            self._position_timer.stop()
            self._pending_position = None
            self._clear_rows()
            self._deck_id = deck_id
            self._limit = CARDS_PAGE_SIZE
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self._scroll.verticalScrollBar().setValue(0)
        self.refresh()

    def refresh(self) -> None:
        if self._deck_id is None:
            return
        summary = self._library.deck_summary(self._deck_id)
        if summary is None:
            self.back.emit()
            return
        self._summary = summary
        self.cover.configure(self._library.deck_cover(self._deck_id))
        self._title.setText(summary.deck.name)
        parts = [cards_count(summary.card_count)]
        if summary.deck.source_language or summary.deck.target_language:
            parts.append(f"{summary.deck.source_language or '…'} → {summary.deck.target_language or '…'}")
        parts.append(S.DECK_META_DUE.format(n=summary.due_count))
        self._meta.setText(" · ".join(parts))
        self.study_btn.setText(S.BTN_STUDY_N.format(n=summary.due_count))
        self.study_btn.setEnabled(summary.due_count > 0)
        self.repeat_btn.setEnabled(summary.card_count > 0)
        self._render()

    def set_search(self, text: str) -> None:
        """Применяет поиск сразу, без задержки ввода (для тестов и скриншотов)."""
        self._timer.stop()
        self.search.blockSignals(True)
        self.search.setText(text)
        self.search.blockSignals(False)
        self._apply_search()

    def _apply_search(self) -> None:
        self._limit = CARDS_PAGE_SIZE
        self._render(reset_position=True)

    def _render(self, *, reset_position: bool = False) -> None:
        if self._deck_id is None or self._summary is None:
            return
        position = ([], 0, 0) if reset_position else self._pending_position or self._capture_position()
        query = self.search.text()
        rows = self._library.list_cards(self._deck_id, query)
        total = len(rows)
        visible = rows[: self._limit]

        empty_deck = self._summary.card_count == 0
        no_match = total == 0 and not empty_deck
        self._list_view.setVisible(not empty_deck and not no_match)
        self._empty.setVisible(empty_deck or no_match)
        self._empty_title.setText(S.EMPTY_DECK_TITLE if empty_deck else S.NOTHING_FOUND)
        self._empty_actions.setVisible(empty_deck)
        # поиск остаётся доступным, пока в колоде есть карточки
        self.search.setEnabled(not empty_deck)

        wanted = {data.card.id for data in visible}
        for card_id, row in list(self._row_widgets.items()):
            if card_id not in wanted:
                self._remove_row(row)
                del self._row_widgets[card_id]
        for index, data in enumerate(visible, start=1):
            row = self._row_widgets.get(data.card.id)
            if row is None:
                row = CardRowWidget(data)
                row.editRequested.connect(self.editCard.emit)
                row.deleteRequested.connect(self.deleteCard.emit)
                self._row_widgets[data.card.id] = row
                self._rows.insertWidget(index, row)
            else:
                row.update_data(data)
                if self._rows.itemAt(index).widget() is not row:
                    self._rows.removeWidget(row)
                    self._rows.insertWidget(index, row)
        self._shown.setText(S.SHOWN_OF.format(shown=len(visible), total=total))
        self.more_btn.setVisible(len(visible) < total)
        self._pending_position = position
        # Qt должен сначала пересчитать высоту строк и диапазон прокрутки.
        self._position_passes = 2
        self._position_timer.start(0)

    def _capture_position(self) -> tuple[list[str], int, int]:
        value = self._scroll.verticalScrollBar().value()
        rows = self.card_rows()
        for index, row in enumerate(rows):
            if row.y() + row.height() > value:
                candidates = rows[index:] + list(reversed(rows[:index]))
                return [r.card_id for r in candidates], row.y() - value, value
        return [], 0, value

    def _restore_position(self) -> None:
        if self._pending_position is None:
            return
        candidates, offset, value = self._pending_position
        self._rows.activate()
        for card_id in candidates:
            row = self._row_widgets.get(card_id)
            if row is not None:
                value = row.y() - offset
                break
        self._scroll.verticalScrollBar().setValue(value)
        self._position_passes -= 1
        if self._position_passes:
            # Смена фокуса/диапазона может вызвать ещё один перерасчёт переноса текста.
            self._position_timer.start(0)
        else:
            self._pending_position = None

    def _remove_row(self, row: CardRowWidget) -> None:
        if row.hasFocus() or (self.focusWidget() is not None and row.isAncestorOf(self.focusWidget())):
            (self.search if self.search.isEnabled() else self.back_btn).setFocus()
        self._rows.removeWidget(row)
        row.hide()
        row.setParent(None)
        row.deleteLater()

    def _clear_rows(self) -> None:
        for row in self._row_widgets.values():
            self._remove_row(row)
        self._row_widgets.clear()

    @property
    def visible_card_count(self) -> int:
        return self._rows.count() - 2

    def card_rows(self) -> list[CardRowWidget]:
        found = []
        for i in range(self._rows.count()):
            item = self._rows.itemAt(i)
            widget = item.widget() if item is not None else None
            if isinstance(widget, CardRowWidget):
                found.append(widget)
        return found

    # ------------------------------------------------------------ действия

    def _show_more(self) -> None:
        self._limit += CARDS_PAGE_SIZE
        self._render()

    def _on_study(self) -> None:
        if self._deck_id:
            self.study.emit(self._deck_id)

    def _on_import(self) -> None:
        if self._deck_id:
            self.importRequested.emit(self._deck_id)

    def _on_export(self) -> None:
        if self._deck_id:
            self.exportRequested.emit(self._deck_id)

    def _on_add(self) -> None:
        if self._deck_id:
            self.addCard.emit(self._deck_id)
