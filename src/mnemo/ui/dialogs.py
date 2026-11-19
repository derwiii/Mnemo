"""Диалоги колод."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QGridLayout, QVBoxLayout

from mnemo.domain.models import Deck
from mnemo.ui import strings as S
from mnemo.ui.widgets import Dialog, field, label, button
from mnemo.ui.identity import CoverTile, COVER_NAMES
from mnemo.settings import TRANSLATIONS_MAX


class TranslationDialog(Dialog):
    """An explicit save is required before accepting the answer."""

    def __init__(self, parent, text: str, count: int, submit: Callable[[str], str | None]):
        super().__init__(parent, S.BTN_I_WAS_RIGHT, 520)
        self._submit = submit
        self.body.addWidget(label("Новый вариант перевода", "DialogText", wrap=True))
        self.translation = field("Перевод")
        self.translation.setText(text)
        self.body.addWidget(self.translation)
        self.error = label("", "DialogError", wrap=True)
        self.body.addWidget(self.error)
        self.add_buttons(S.BTN_SAVE, "Назад")
        self._full = count >= TRANSLATIONS_MAX
        if self._full:
            self.error.setText(f"Переводов не больше {TRANSLATIONS_MAX}. Измените варианты в редакторе карточки.")
            self.primary.setEnabled(False)
        self.translation.setFocus()

    def _on_primary(self) -> None:
        if self._full:
            return
        error = self._submit(self.translation.text())
        if error:
            self.error.setText(error)
        else:
            self.accept()


@dataclass
class DeckValues:
    name: str
    description: str
    source_language: str
    target_language: str


class CoverDialog(Dialog):
    def __init__(self, parent, cover_id, submit):
        super().__init__(parent, "Обложка колоды", 500)
        self._current = cover_id
        self._choices = {}
        grid = QGridLayout()
        self.error = label("", "DialogError", wrap=True)
        for index, (key, title) in enumerate(COVER_NAMES.items()):
            tile = button("", "choice", focus=True)
            tile.setAccessibleName(title)
            tile.setCheckable(True)
            tile.setChecked(key == cover_id)
            self._choices[key] = tile
            tile.clicked.connect(lambda checked, k=key: self._choose(k, submit))
            cell = QVBoxLayout(tile)
            cell.setContentsMargins(10, 9, 10, 9)
            cell.addWidget(CoverTile(key), alignment=Qt.AlignmentFlag.AlignHCenter)
            caption = label(title)
            caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.addWidget(caption)
            tile.setMinimumHeight(108)
            grid.addWidget(tile, index // 3, index % 3)
        self.body.addLayout(grid)
        self.body.addWidget(self.error)

    def _choose(self, cover_id, submit):
        error = submit(cover_id)
        if error:
            self.error.setText(error)
            for key, tile in self._choices.items():
                tile.setChecked(key == self._current)
        else:
            self.accept()


class DeckDialog(Dialog):
    """Создание и переименование колоды.

    `submit` получает значения и возвращает текст ошибки (диалог остаётся открытым)
    или None (диалог закрывается успешно).
    """

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        primary_text: str,
        submit: Callable[[DeckValues], str | None],
        deck: Deck | None = None,
    ) -> None:
        super().__init__(parent, title)
        self._submit = submit
        self.name = field(S.FIELD_DECK_NAME)
        self.description = field(S.FIELD_DECK_DESCRIPTION)
        self.source = field(S.FIELD_SOURCE_LANG)
        self.target = field(S.FIELD_TARGET_LANG)
        if deck is not None:
            self.name.setText(deck.name)
            self.description.setText(deck.description)
            self.source.setText(deck.source_language)
            self.target.setText(deck.target_language)
        for edit in (self.name, self.description, self.source, self.target):
            self.body.addWidget(edit)
        self.error = label("", "DialogError", wrap=True)
        self.error.hide()
        self.body.addWidget(self.error)
        self.add_buttons(primary_text)
        self.name.setFocus()

    def values(self) -> DeckValues:
        return DeckValues(
            self.name.text(),
            self.description.text(),
            self.source.text(),
            self.target.text(),
        )

    def _on_primary(self) -> None:
        error = self._submit(self.values())
        if error:
            self.error.setText(error)
            self.error.show()
            self.name.setFocus()
            return
        self.accept()
