"""Экран «Статистика»: числа и самые трудные карточки, без графиков (docs/specs/design.md, раздел 12.2; docs/specs/repetition.md)."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from mnemo.services import Library, Statistics
from mnemo.domain.markup import translation_text
from mnemo.ui import strings as S
from mnemo.ui.card_text import set_front_text
from mnemo.ui.widgets import button, label, scroll_area


class StatsScreen(QWidget):
    back = pyqtSignal()
    editCard = pyqtSignal(str)

    def __init__(self, library: Library) -> None:
        super().__init__()
        self._library = library
        root = QVBoxLayout(self)
        root.setContentsMargins(56, 24, 56, 26)
        root.setSpacing(0)

        top = QHBoxLayout()
        self.back_btn = button(S.BACK_TO_DECKS, "back", focus=True)
        self.back_btn.clicked.connect(self.back.emit)
        top.addWidget(self.back_btn)
        top.addStretch(1)
        self.header = top
        root.addLayout(top)
        root.addSpacing(26)
        root.addWidget(label(S.STATS_TITLE, "Heading"))
        root.addSpacing(30)

        numbers = QHBoxLayout()
        numbers.setSpacing(12)
        self._values: dict[str, tuple] = {}
        for key, caption in (
            ("total", S.STAT_TOTAL),
            ("today", S.STAT_TODAY),
            ("period", S.STAT_PERIOD),
            ("correct", S.STAT_CORRECT),
        ):
            tile = QFrame()
            tile.setObjectName("StatTile")
            box = QVBoxLayout(tile)
            box.setContentsMargins(16, 12, 16, 16)
            box.setSpacing(4)
            value = label("0", "StatNumber")
            box.addWidget(value)
            box.addWidget(label(caption, "StatCaption", wrap=True))
            numbers.addWidget(tile, 1)
            self._values[key] = (value,)

        root.addLayout(numbers)
        extra = QHBoxLayout()
        extra.setSpacing(12)
        for key, caption in (("failures", S.STAT_FAILURES), ("unique", S.STAT_UNIQUE)):
            tile = QFrame()
            tile.setObjectName("StatTile")
            box = QVBoxLayout(tile)
            box.setContentsMargins(16, 12, 16, 16)
            box.setSpacing(4)
            value = label("0", "StatNumber")
            box.addWidget(value)
            box.addWidget(label(caption, "StatCaption", wrap=True))
            box.addStretch(1)
            extra.addWidget(tile, 1)
            self._values[key] = (value,)

        root.addSpacing(14)
        root.addLayout(extra)
        root.addSpacing(14)
        self._breakdown = label("", "Meta")
        root.addWidget(self._breakdown)

        root.addSpacing(34)
        root.addWidget(label(S.CAPTION_HARDEST, "Caption"))
        root.addSpacing(12)
        self._empty = label(S.HARDEST_EMPTY, "EmptyHint")
        root.addWidget(self._empty)
        self._rows_host = QWidget()
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(6)
        self._rows.addStretch(1)
        root.addWidget(scroll_area(self._rows_host), 1)

    def refresh(self) -> Statistics:
        stats = self._library.statistics()
        self._values["total"][0].setText(str(stats.total_cards))
        self._values["today"][0].setText(str(stats.reviews_today))
        self._values["period"][0].setText(str(stats.reviews_period))
        self._values["failures"][0].setText(str(stats.failures_period))
        self._values["unique"][0].setText(str(stats.unique_cards_period))
        correct = stats.correct_percent
        self._values["correct"][0].setText(S.STAT_NO_ANSWERS if correct is None else f"{correct}%")
        self._breakdown.setText(
            S.STATUS_BREAKDOWN.format(
                new=stats.new_cards, learning=stats.learning_cards, review=stats.review_cards
            )
        )
        while self._rows.count() > 1:
            item = self._rows.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for hard in stats.hardest:
            row = QFrame()
            row.setObjectName("CardRow")
            lay = QHBoxLayout(row)
            lay.setContentsMargins(22, 13, 22, 13)
            lay.setSpacing(16)
            word = label("", "CardWord")
            set_front_text(word, hard.card.front)
            word.setFixedWidth(140)
            word.setWordWrap(True)
            translations = label(translation_text(hard.card.translations), "CardTranslations", wrap=True)
            translations.setTextFormat(Qt.TextFormat.PlainText)
            lapses = label(S.LAPSES_LABEL.format(n=hard.state.lapses), "Lapses")
            lapses.setToolTip(S.LAPSES_HINT)
            lapses.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            edit = button(S.BTN_EDIT, "textsmall")
            edit.clicked.connect(lambda _c=False, cid=hard.card.id: self.editCard.emit(cid))
            lay.addWidget(word)
            lay.addWidget(translations, 1)
            lay.addWidget(lapses)
            lay.addWidget(edit)
            self._rows.insertWidget(self._rows.count() - 1, row)
        self._empty.setVisible(not stats.hardest)
        return stats

    @property
    def hardest_row_count(self) -> int:
        return self._rows.count() - 1

    def number_text(self, key: str) -> str:
        return self._values[key][0].text()
