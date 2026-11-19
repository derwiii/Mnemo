"""Редактор карточки: отдельный экран (docs/specs/design.md, раздел 10; docs/specs/cards.md)."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from mnemo.domain.models import Example
from mnemo.domain.validation import ValidationError, clean_strings
from mnemo.services import Library
from mnemo.settings import EXAMPLES_MAX, HINTS_MAX, TRANSLATIONS_MAX
from mnemo.ui import strings as S
from mnemo.ui.widgets import button, field, label, scroll_area, set_prop


class LineList(QWidget):
    """Список однострочных полей с кнопкой «+ Добавить…» (переводы, подсказки)."""

    def __init__(
        self, maximum: int, add_text: str, size: str | None, numbered: bool = False, start_rows: int = 1
    ) -> None:
        super().__init__()
        self._max = maximum
        self._size = size
        self._numbered = numbered
        self._start_rows = start_rows
        self._edits: list[QLineEdit] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        self._rows = QVBoxLayout()
        self._rows.setSpacing(8)
        outer.addLayout(self._rows)
        self.add_btn = button(add_text, "link")
        self.add_btn.clicked.connect(lambda: self.add_row(focus=True))
        outer.addWidget(self.add_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.set_values([])

    def set_values(self, values: list[str]) -> None:
        for edit in self._edits:
            edit.setParent(None)
            edit.deleteLater()
        self._edits = []
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for value in values[: self._max]:
            self.add_row(value)
        while len(self._edits) < self._start_rows:
            self.add_row()
        self._update_add_button()

    def add_row(self, text: str = "", focus: bool = False) -> QLineEdit | None:
        if len(self._edits) >= self._max:
            return None
        edit = field(size=self._size)
        edit.setText(text)
        if self._numbered:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(12)
            lay.addWidget(label(str(len(self._edits) + 1), "Number"))
            lay.addWidget(edit, 1)
            self._rows.addWidget(row)
        else:
            self._rows.addWidget(edit)
        self._edits.append(edit)
        self._update_add_button()
        if focus:
            edit.setFocus()
        return edit

    def values(self) -> list[str]:
        return [e.text() for e in self._edits]

    @property
    def edits(self) -> list[QLineEdit]:
        return list(self._edits)

    def _update_add_button(self) -> None:
        self.add_btn.setEnabled(len(self._edits) < self._max)


class ExampleList(QWidget):
    """Пары «пример + перевод примера»."""

    def __init__(self, maximum: int = EXAMPLES_MAX) -> None:
        super().__init__()
        self._max = maximum
        self._pairs: list[tuple[QLineEdit, QLineEdit]] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        self._rows = QVBoxLayout()
        self._rows.setSpacing(14)
        outer.addLayout(self._rows)
        self.add_btn = button(S.ADD_EXAMPLE, "link")
        self.add_btn.clicked.connect(lambda: self.add_row(focus=True))
        outer.addWidget(self.add_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.set_values([])

    def set_values(self, values: list[Example]) -> None:
        self._pairs = []
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for ex in values[: self._max]:
            self.add_row(ex.text, ex.translation or "")
        if not self._pairs:
            self.add_row()
        self._update_add_button()

    def add_row(self, text: str = "", translation: str = "", focus: bool = False) -> None:
        if len(self._pairs) >= self._max:
            return
        block = QWidget()
        lay = QVBoxLayout(block)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        first = field(S.EXAMPLE_PLACEHOLDER)
        second = field(S.EXAMPLE_TR_PLACEHOLDER, "small")
        first.setText(text)
        second.setText(translation)
        lay.addWidget(first)
        lay.addWidget(second)
        self._rows.addWidget(block)
        self._pairs.append((first, second))
        self._update_add_button()
        if focus:
            first.setFocus()

    def values(self) -> list[Example]:
        return [Example(a.text(), b.text()) for a, b in self._pairs]

    @property
    def pairs(self) -> list[tuple[QLineEdit, QLineEdit]]:
        return list(self._pairs)

    def _update_add_button(self) -> None:
        self.add_btn.setEnabled(len(self._pairs) < self._max)


class EditorScreen(QWidget):
    closeRequested = pyqtSignal()
    saved = pyqtSignal(bool)  # True: «Сохранить и добавить ещё»

    def __init__(self, library: Library) -> None:
        super().__init__()
        self._library = library
        self._deck_id: str | None = None
        self._card_id: str | None = None
        self._initial: tuple = ()
        self._dup_ack: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(56, 24, 56, 26)
        root.setSpacing(0)

        top = QHBoxLayout()
        self.back_btn = button("← …", "back", focus=True)
        self.back_btn.clicked.connect(self.closeRequested.emit)
        top.addWidget(self.back_btn)
        top.addStretch(1)
        self.header = top
        root.addLayout(top)
        root.addSpacing(22)
        self._title = label(S.EDITOR_TITLE_NEW, "Heading")
        root.addWidget(self._title)
        root.addSpacing(26)

        columns = QWidget()
        cols = QHBoxLayout(columns)
        self._columns = cols
        cols.setContentsMargins(0, 0, 8, 0)
        cols.setSpacing(20)

        left_panel = QWidget()
        left_panel.setObjectName("FormPanel")
        left_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        left = QVBoxLayout(left_panel)
        left.setContentsMargins(20, 22, 20, 20)
        left.setSpacing(0)
        left.addWidget(label(S.CAPTION_FRONT, "Caption"))
        left.addSpacing(10)
        self.front = field(size="big")
        self.front.setToolTip("Если переводится вся строка, скобки не нужны. [[цель]] выделяет только часть с внешним контекстом; {контекст|контекст} — варианты контекста.")
        self.front.textChanged.connect(self._on_front_changed)
        left.addWidget(self.front)
        self._front_error = label("", "FieldError", wrap=True)
        self._front_warn = label("", "FieldWarn", wrap=True)
        for lab in (self._front_error, self._front_warn):
            lab.hide()
            left.addWidget(lab)
        left.addSpacing(30)
        left.addWidget(label(S.CAPTION_TRANSLATIONS, "Caption"))
        left.addSpacing(10)
        self.translations = LineList(TRANSLATIONS_MAX, S.ADD_TRANSLATION, "mid")
        left.addWidget(self.translations)
        left.addWidget(label("Общие части перевода пишите один раз: старше {своих лет|своего возраста}. На карточке — через / без скобок. Разные переводы — отдельными строками; (пояснение) необязательно.", "Note", wrap=True))
        self._tr_error = label("", "FieldError", wrap=True)
        self._tr_error.hide()
        left.addWidget(self._tr_error)
        left.addStretch(1)

        right_panel = QWidget()
        right_panel.setObjectName("FormPanel")
        right_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        right = QVBoxLayout(right_panel)
        right.setContentsMargins(20, 22, 20, 20)
        right.setSpacing(0)
        right.addWidget(label(S.CAPTION_EXAMPLES, "Caption"))
        right.addSpacing(10)
        self.examples = ExampleList()
        right.addWidget(self.examples)
        self._ex_error = label("", "FieldError", wrap=True)
        self._ex_error.hide()
        right.addWidget(self._ex_error)
        right.addSpacing(30)
        right.addWidget(label(S.CAPTION_HINTS_EDITOR, "Caption"))
        right.addSpacing(10)
        self.hints = LineList(HINTS_MAX, S.ADD_HINT, None, numbered=True)
        right.addWidget(self.hints)
        self._hints_error = label("", "FieldError", wrap=True)
        self._hints_error.hide()
        right.addWidget(self._hints_error)
        right.addSpacing(8)
        right.addWidget(label(S.HINTS_NOTE, "Note", wrap=True))
        right.addStretch(1)

        cols.addWidget(left_panel, 1)
        cols.addWidget(right_panel, 1)
        root.addWidget(scroll_area(columns), 1)

        root.addSpacing(16)
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.save_btn = button(S.BTN_SAVE, "primary")
        self.save_btn.clicked.connect(lambda: self.save(False))
        self.save_add_btn = button(S.BTN_SAVE_AND_ADD, "secondary")
        self.save_add_btn.clicked.connect(lambda: self.save(True))
        self.cancel_btn = button(S.BTN_CANCEL, "text")
        self.cancel_btn.clicked.connect(self.closeRequested.emit)
        self._saved_msg = label("", "SavedMessage")
        bottom.addWidget(self.save_btn)
        bottom.addWidget(self.save_add_btn)
        bottom.addWidget(self._saved_msg)
        bottom.addStretch(1)
        bottom.addWidget(self.cancel_btn)
        root.addLayout(bottom)

        QShortcut(QKeySequence("Ctrl+S"), self, activated=lambda: self.save(False))

    # ------------------------------------------------------------ запуск

    def resizeEvent(self, event):
        super().resizeEvent(event)
        direction = self._columns.Direction
        self._columns.setDirection(direction.TopToBottom if self.width() < 860 else direction.LeftToRight)

    @property
    def deck_id(self) -> str | None:
        return self._deck_id

    @property
    def card_id(self) -> str | None:
        return self._card_id

    def start_new(self, deck_id: str) -> None:
        self._deck_id = deck_id
        self._card_id = None
        self._title.setText(S.EDITOR_TITLE_NEW)
        self._load(front="", translations=[], examples=[], hints=[])

    def start_edit(self, card_id: str) -> bool:
        card = self._library.cards.get(card_id)
        if card is None:
            return False
        self._deck_id = card.deck_id
        self._card_id = card.id
        self._title.setText(S.EDITOR_TITLE_EDIT)
        self._load(card.front, card.translations, card.examples, card.hints)
        return True

    def _load(
        self, front: str, translations: list[str], examples: list[Example], hints: list[str]
    ) -> None:
        deck = self._library.decks.get(self._deck_id) if self._deck_id else None
        name = deck.name if deck else ""
        self.back_btn.setText(f"← {name}")
        self.front.blockSignals(True)
        self.front.setText(front)
        self.front.blockSignals(False)
        self.translations.set_values(translations)
        self.examples.set_values(examples)
        self.hints.set_values(hints)
        self._clear_errors()
        self._saved_msg.setText("")
        self._dup_ack = None
        self._initial = self._snapshot()
        self.front.setFocus()

    # ------------------------------------------------------------ состояние

    def _snapshot(self) -> tuple:
        return (
            self.front.text().strip(),
            tuple(clean_strings(self.translations.values())),
            tuple(
                (e.text.strip(), (e.translation or "").strip())
                for e in self.examples.values()
                if e.text.strip()
            ),
            tuple(clean_strings(self.hints.values())),
        )

    def is_dirty(self) -> bool:
        return self._snapshot() != self._initial

    def _clear_errors(self) -> None:
        for lab in (
            self._front_error,
            self._front_warn,
            self._tr_error,
            self._ex_error,
            self._hints_error,
        ):
            lab.setText("")
            lab.hide()
        set_prop(self.front, "state", "")
        for edit in self.translations.edits:
            set_prop(edit, "state", "")

    def _show_error(self, label_widget, text: str) -> None:
        label_widget.setText(text)
        label_widget.show()

    def _on_front_changed(self, _text: str) -> None:
        self._dup_ack = None
        self._front_warn.hide()
        if self._front_error.isVisible():
            self._front_error.hide()
            set_prop(self.front, "state", "")
        self._saved_msg.setText("")

    # ------------------------------------------------------------ сохранение

    def save(self, add_another: bool = False) -> bool:
        """Сохраняет карточку. False, если есть ошибки или нужно подтвердить дубликат."""
        if self._deck_id is None:
            return False
        self._clear_errors()
        front = self.front.text()

        if front.strip():
            key = " ".join(front.split()).casefold()
            duplicates = self._library.find_duplicates(self._deck_id, front, self._card_id)
            if duplicates and self._dup_ack != key:
                self._dup_ack = key
                self._show_error(self._front_warn, S.DUPLICATE_WARNING)
                return False

        try:
            self._library.save_card(
                self._deck_id,
                front,
                self.translations.values(),
                self.examples.values(),
                self.hints.values(),
                card_id=self._card_id,
            )
        except ValidationError as exc:
            self._show_validation(exc)
            return False

        self.saved.emit(add_another)
        if add_another:
            self.start_new(self._deck_id)
            self._saved_msg.setText(S.SAVED_MESSAGE)
        else:
            self._initial = self._snapshot()
        return True

    def _show_validation(self, exc: ValidationError) -> None:
        fields = exc.fields
        if "front" in fields:
            self._show_error(self._front_error, fields["front"])
            set_prop(self.front, "state", "bad")
        if "translations" in fields:
            self._show_error(self._tr_error, fields["translations"])
            for edit in self.translations.edits:
                if not edit.text().strip():
                    set_prop(edit, "state", "bad")
        if "examples" in fields:
            self._show_error(self._ex_error, fields["examples"])
        if "hints" in fields:
            self._show_error(self._hints_error, fields["hints"])
        if "front" in fields:
            self.front.setFocus()
        elif "translations" in fields and self.translations.edits:
            self.translations.edits[0].setFocus()
