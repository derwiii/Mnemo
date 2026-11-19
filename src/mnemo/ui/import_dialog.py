"""Диалог импорта JSON (docs/specs/design.md, раздел 12.1; docs/specs/import-export.md)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mnemo.domain.importer import DeckInfo, DuplicatePolicy, ParseResult, parse_import
from mnemo.domain.markup import display_text
from mnemo.domain.validation import ValidationError
from mnemo.paths import resource_path
from mnemo.services import ImportFileError, ImportReport, Library, read_import_file
from mnemo.settings import IMPORT_PREVIEW_CARDS
from mnemo.storage import DuplicateDeckNameError, StorageError
from mnemo.ui import strings as S
from mnemo.ui.widgets import Dialog, button, field, label

MAX_SHOWN_ERRORS = 5


def default_pick_file(parent: QWidget) -> str:
    path, _ = QFileDialog.getOpenFileName(parent, S.FILE_DIALOG_TITLE, "", S.FILE_FILTER)
    return path


def default_copy(text: str) -> None:
    clipboard = QApplication.clipboard()
    if clipboard is not None:
        clipboard.setText(text)


def load_prompt() -> str:
    return resource_path("ai_prompt.txt").read_text(encoding="utf-8")


class ImportDialog(Dialog):
    def __init__(
        self,
        parent: QWidget | None,
        library: Library,
        preselect_deck_id: str | None = None,
        pick_file: Callable[[QWidget], str] = default_pick_file,
        copy_text: Callable[[str], None] = default_copy,
    ) -> None:
        super().__init__(parent, S.IMPORT_TITLE, width=720)
        self._library = library
        self._pick_file = pick_file
        self._copy_text = copy_text
        self._decks = library.decks.list()
        self._file_text = ""
        self._parse: ParseResult | None = None
        self._duplicates = 0
        self._deck_id: str | None = None
        self._name_autofilled = True
        self.report: ImportReport | None = None

        columns = QHBoxLayout()
        columns.setSpacing(28)
        columns.addLayout(self._build_source(), 1)
        columns.addLayout(self._build_target(), 1)
        self.body.addLayout(columns)

        self.error = label("", "DialogError", wrap=True)
        self.error.hide()
        self.body.addWidget(self.error)
        self.add_buttons(S.BTN_DO_IMPORT)
        assert self.primary is not None
        self.primary.setEnabled(False)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._reparse)

        # колода по умолчанию
        if self._decks:
            chosen = next((d for d in self._decks if d.id == preselect_deck_id), self._decks[0])
            self.select_deck(chosen.id)
            self.existing_btn.setChecked(True)
        else:
            self.existing_btn.setEnabled(False)
            self.new_btn.setChecked(True)
        self._apply_mode()
        for btn in self._policy_buttons:
            btn.toggled.connect(lambda _c: self._refresh_preview())
        self.existing_btn.toggled.connect(lambda _c: self._on_target_changed())
        self._refresh_preview()

    # ------------------------------------------------------------ сборка

    def _build_source(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(10)
        col.addWidget(label(S.CAPTION_SOURCE, "Caption"))
        row = QVBoxLayout()
        row.setSpacing(10)
        self.file_btn = button(S.BTN_CHOOSE_FILE, "secondary")
        self.file_btn.clicked.connect(self._choose_file)
        self.prompt_btn = button(S.BTN_COPY_PROMPT, "text")
        self.prompt_btn.clicked.connect(self._copy_prompt)
        row.addWidget(self.file_btn, 0, Qt.AlignmentFlag.AlignLeft)
        row.addWidget(self.prompt_btn, 0, Qt.AlignmentFlag.AlignLeft)
        col.addLayout(row)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(S.PASTE_PLACEHOLDER)
        self.text_edit.setMinimumHeight(220)
        self.text_edit.textChanged.connect(self._on_text_changed)
        col.addWidget(self.text_edit, 1)
        self.source_status = label("", "Note", wrap=True)
        col.addWidget(self.source_status)
        return col

    def _build_target(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(10)
        col.addWidget(label(S.CAPTION_TARGET_DECK, "Caption"))

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        self.existing_btn = self._choice(S.TARGET_EXISTING)
        self.new_btn = self._choice(S.TARGET_NEW)
        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self.existing_btn)
        group.addButton(self.new_btn)
        mode_row.addWidget(self.existing_btn)
        mode_row.addWidget(self.new_btn)
        mode_row.addStretch(1)
        col.addLayout(mode_row)

        self.deck_btn = button("", "choice")
        self.deck_btn.clicked.connect(self._show_deck_menu)
        col.addWidget(self.deck_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.new_name = field(S.NEW_DECK_PLACEHOLDER)
        self.new_name.textEdited.connect(self._on_name_edited)
        self.new_name.textChanged.connect(lambda _t: self._update_import_enabled())
        col.addWidget(self.new_name)

        col.addSpacing(6)
        col.addWidget(label(S.CAPTION_DUPLICATES, "Caption"))
        policy_row = QHBoxLayout()
        policy_row.setSpacing(8)
        self.skip_btn = self._choice(S.POLICY_SKIP)
        self.add_btn = self._choice(S.POLICY_ADD)
        self.update_btn = self._choice(S.POLICY_UPDATE)
        policies = QButtonGroup(self)
        policies.setExclusive(True)
        for btn in (self.skip_btn, self.add_btn, self.update_btn):
            policies.addButton(btn)
            policy_row.addWidget(btn)
        policy_row.addStretch(1)
        self.skip_btn.setChecked(True)
        # сигналы подключаем после сборки всего окна: обработчики обращаются к его элементам
        self._policy_buttons = (self.skip_btn, self.add_btn, self.update_btn)
        col.addLayout(policy_row)

        col.addSpacing(6)
        col.addWidget(label(S.CAPTION_PREVIEW, "Caption"))
        self.stats = label("", "ImportStat", wrap=True)
        self.sample = label("", "ImportSample", wrap=True)
        self.sample.setTextFormat(Qt.TextFormat.PlainText)
        self.problems = label("", "DialogError", wrap=True)
        self.warnings = label("", "ImportWarn", wrap=True)
        for lab in (self.stats, self.sample, self.problems, self.warnings):
            col.addWidget(lab)
        col.addStretch(1)
        return col

    @staticmethod
    def _choice(text: str) -> QPushButton:
        btn = button(text, "choice")
        btn.setCheckable(True)
        return btn

    # ------------------------------------------------------------ источник

    def set_source_text(self, text: str) -> None:
        """Подставляет JSON как вставленный текст и сразу разбирает его."""
        self._file_text = ""
        self.text_edit.blockSignals(True)
        self.text_edit.setPlainText(text)
        self.text_edit.blockSignals(False)
        self.source_status.setText("")
        self._reparse()

    def _choose_file(self) -> None:
        path = self._pick_file(self)
        if path:
            self.load_file(path)

    def load_file(self, path: str) -> None:
        try:
            text = read_import_file(path)
        except ImportFileError as exc:
            self._file_text = ""
            self.source_status.setText(str(exc))
            self._parse = None
            self._refresh_preview()
            return
        self.text_edit.blockSignals(True)
        self.text_edit.clear()
        self.text_edit.blockSignals(False)
        self._file_text = text
        self.source_status.setText(S.FILE_LOADED.format(name=Path(path).name))
        self._reparse()

    def _copy_prompt(self) -> None:
        self._copy_text(load_prompt())
        self.source_status.setText(S.PROMPT_COPIED)

    def _on_text_changed(self) -> None:
        self._file_text = ""
        self.source_status.setText("")
        self._timer.start()

    def _current_text(self) -> str:
        return self.text_edit.toPlainText().strip() or self._file_text

    def _reparse(self) -> None:
        text = self._current_text()
        self._parse = parse_import(text) if text else None
        parse = self._parse
        if parse and parse.ok and parse.deck and parse.deck.name and self._name_autofilled:
            self.new_name.blockSignals(True)
            self.new_name.setText(parse.deck.name)
            self.new_name.blockSignals(False)
        self._refresh_preview()

    # ------------------------------------------------------------ колода

    @property
    def target_is_new(self) -> bool:
        return self.new_btn.isChecked()

    def select_deck(self, deck_id: str) -> None:
        self._deck_id = deck_id
        deck = next((d for d in self._decks if d.id == deck_id), None)
        self.deck_btn.setText(f"{deck.name}  ▾" if deck else S.NO_DECK_CHOSEN)
        self._refresh_preview()

    def _show_deck_menu(self) -> None:
        menu = QMenu(self)
        for deck in self._decks:
            menu.addAction(deck.name, lambda d=deck.id: self.select_deck(d))
        menu.exec(self.deck_btn.mapToGlobal(self.deck_btn.rect().bottomLeft()))

    def _on_target_changed(self) -> None:
        self._apply_mode()
        self._refresh_preview()

    def _apply_mode(self) -> None:
        new = self.target_is_new
        self.deck_btn.setVisible(not new)
        self.new_name.setVisible(new)

    def _on_name_edited(self, _text: str) -> None:
        self._name_autofilled = False

    # ------------------------------------------------------------ предпросмотр

    @property
    def policy(self) -> DuplicatePolicy:
        if self.add_btn.isChecked():
            return DuplicatePolicy.ADD
        if self.update_btn.isChecked():
            return DuplicatePolicy.UPDATE
        return DuplicatePolicy.SKIP

    def _refresh_preview(self) -> None:
        parse = self._parse
        self.error.hide()
        for lab in (self.stats, self.sample, self.problems, self.warnings):
            lab.setText("")
        if parse is None:
            self.stats.setText(S.PREVIEW_WAITING)
            self._duplicates = 0
        elif not parse.ok:
            self.problems.setText(parse.fatal or "")
            self._duplicates = 0
        else:
            deck_id = None if self.target_is_new else self._deck_id
            self._duplicates = self._library.preview_import(parse, deck_id).duplicates
            self.stats.setText(
                S.PREVIEW_STATS.format(
                    valid=len(parse.cards), errors=len(parse.errors), dups=self._duplicates
                )
            )
            self.sample.setText(
                "\n".join(
                    f"{display_text(p.card.front, front=True)} — {display_text(p.card.translations[0])}"
                    for p in parse.cards[:IMPORT_PREVIEW_CARDS]
                )
            )
            lines = [str(e) for e in parse.errors[:MAX_SHOWN_ERRORS]]
            if len(parse.errors) > MAX_SHOWN_ERRORS:
                lines.append(S.PREVIEW_MORE_ERRORS.format(n=len(parse.errors) - MAX_SHOWN_ERRORS))
            if self._nothing_new():
                lines.append(S.PREVIEW_NOTHING_NEW)
            self.problems.setText("\n".join(lines))
            self.warnings.setText("\n".join(parse.warnings))
        self._update_import_enabled()

    def _nothing_new(self) -> bool:
        parse = self._parse
        if parse is None or not parse.ok or not parse.cards:
            return False
        return self.policy is DuplicatePolicy.SKIP and self._duplicates >= len(parse.cards)

    def _update_import_enabled(self) -> None:
        if self.primary is None:
            return
        parse = self._parse
        has_cards = bool(parse and parse.ok and parse.cards)
        if self.target_is_new:
            target_ok = bool(self.new_name.text().strip())
        else:
            target_ok = self._deck_id is not None
        self.primary.setEnabled(has_cards and target_ok and not self._nothing_new())

    # ------------------------------------------------------------ импорт

    def _on_primary(self) -> None:
        parse = self._parse
        if parse is None or not parse.ok:
            return
        try:
            if self.target_is_new:
                info = parse.deck or DeckInfo()
                new_deck = DeckInfo(
                    self.new_name.text(), info.description, info.source_language, info.target_language
                )
                report = self._library.apply_import(parse, self.policy, new_deck=new_deck)
            else:
                report = self._library.apply_import(parse, self.policy, deck_id=self._deck_id)
        except DuplicateDeckNameError:
            self._show_error(S.ERROR_DECK_EXISTS)
            return
        except ValidationError as exc:
            self._show_error(exc.problems[0])
            return
        except (StorageError, ValueError, OSError) as exc:
            self._show_error(S.IMPORT_FAILED.format(reason=exc))
            return
        self.report = report
        self.accept()

    def _show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.show()
