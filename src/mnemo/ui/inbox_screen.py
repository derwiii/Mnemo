"""Capture now; prepare a learning card later."""

import sqlite3

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QPlainTextEdit, QComboBox, QSplitter, QFrame,
)

from mnemo.domain.validation import ValidationError
from mnemo.storage import StorageError
from mnemo.ui.widgets import Dialog, button, label, scroll_area, confirm, icon_button
from mnemo.ui.identity import StackArt

ERRORS = (ValidationError, StorageError, sqlite3.Error)


def text_box(placeholder: str, height: int):
    edit = QPlainTextEdit()
    edit.setPlaceholderText(placeholder)
    edit.setAccessibleName(placeholder)
    edit.setFixedHeight(height)
    return edit


class QuickAddDialog(Dialog):
    saved = pyqtSignal(str, bool)  # entry id, created
    inboxRequested = pyqtSignal()
    mainRequested = pyqtSignal()
    resized = pyqtSignal()

    def __init__(self, library, text=""):
        # A parentless tool window has neither a main-window owner nor a taskbar entry.
        # The desktop controller retains its Python reference and manages its lifetime.
        super().__init__(None, "Новое слово", 440)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        # Modeless: the global shortcut can raise the same form without replacing input.
        self.setModal(False)
        self.panel.setProperty("capture", True)
        self.body.setContentsMargins(22, 20, 22, 18)
        self.body.setSpacing(10)
        self.library = library
        title = self.body.takeAt(0).widget()
        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(StackArt(logo=True))
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("MNEMO · БЫСТРОЕ ДОБАВЛЕНИЕ", "CaptureEyebrow"))
        titles.addWidget(title)
        header.addLayout(titles, 1)
        close = icon_button("close", "Отмена")
        close.clicked.connect(self.reject)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(header)
        self.body.addWidget(label("Сохраните находку. Перевод можно добавить позже.", "CaptureHint", wrap=True))
        fields = QFrame()
        fields.setObjectName("CaptureFields")
        content = QVBoxLayout(fields)
        content.setContentsMargins(14, 12, 14, 12)
        content.setSpacing(8)
        content.addWidget(label("СЛОВО ИЛИ ФРАЗА", "Caption"))
        self.front = text_box("Например, come across", 58)
        self.front.setAccessibleName("Слово или фраза")
        self.front.setPlainText(text)
        content.addWidget(self.front)
        content.addWidget(label("ПЕРЕВОДЫ · НЕОБЯЗАТЕЛЬНО", "Caption"))
        self.translations = text_box("Каждый перевод с новой строки", 70)
        content.addWidget(self.translations)
        self.body.addWidget(fields)
        self.error = label("", "DialogError", wrap=True)
        self.error.setMinimumHeight(18)
        self.body.addWidget(self.error)
        self.add_buttons("Сохранить слово", "Отмена")
        navigation = QHBoxLayout()
        self.inbox_btn = button(f"Входящие · {library.inbox.count()}", "text", focus=True)
        self.main_btn = button("Открыть Mnemo ↗", "text", focus=True)
        self.inbox_btn.clicked.connect(self.inboxRequested.emit)
        self.main_btn.clicked.connect(self.mainRequested.emit)
        navigation.addWidget(self.inbox_btn)
        navigation.addStretch()
        navigation.addWidget(self.main_btn)
        self.body.addLayout(navigation)
        self.front.setFocus()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()

    def _on_primary(self):
        try:
            entry, created = self.library.capture_word(
                self.front.toPlainText(), self.translations.toPlainText().splitlines())
        except ERRORS as exc:
            self.error.setText(str(exc))
            return
        self.accept()
        self.saved.emit(entry.id, created)


class InboxScreen(QWidget):
    back = pyqtSignal()
    changed = pyqtSignal()
    settingsRequested = pyqtSignal()

    def __init__(self, library):
        super().__init__()
        self.library = library
        self.entry_id = None
        self._snapshot = None
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 24, 40, 24)
        root.setSpacing(14)
        top = QHBoxLayout()
        back = button("← К колодам", "back", focus=True)
        back.clicked.connect(self._back)
        top.addWidget(back)
        self.heading = label("Входящие", "Heading")
        top.addWidget(StackArt(logo=True))
        top.addWidget(self.heading)
        top.addStretch()
        self.settings_btn = icon_button("settings", "Настройки входящих")
        self.settings_btn.clicked.connect(self.settingsRequested.emit)
        top.addWidget(self.settings_btn)
        self.header = top
        root.addLayout(top)
        root.addWidget(label("Сохраните сейчас — подготовьте к изучению позже.", "DeckMeta", wrap=True))
        split = QSplitter(Qt.Orientation.Horizontal)
        self.items = QListWidget()
        self.items.setObjectName("InboxList")
        self.items.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.items.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.items.setAccessibleName("Входящие слова")
        self.items.setMinimumWidth(210)
        self.items.currentItemChanged.connect(self._selected)
        split.addWidget(self.items)
        self.details = QFrame()
        self.details.setObjectName("InboxDetails")
        form = QVBoxLayout(self.details)
        form.setContentsMargins(18, 18, 18, 18)
        form.setSpacing(8)
        self.detail_caption = label("ЗАГОТОВКА", "CaptureEyebrow")
        form.addWidget(self.detail_caption)
        self.detail_title = label("Выберите слово", "InboxDetailTitle", wrap=True)
        form.addWidget(self.detail_title)
        self.detail_meta = label("", "CaptureHint", wrap=True)
        form.addWidget(self.detail_meta)
        self.front = text_box("Слово или фраза", 58)
        self.translations = text_box("Каждый перевод с новой строки", 76)
        self.context = text_box("Исходное предложение · необязательно", 70)
        for title, widget in (("Слово или фраза", self.front),
                              ("Переводы · до 10", self.translations),
                              ("Контекст · станет примером карточки", self.context)):
            form.addWidget(label(title, "Caption", wrap=True))
            form.addWidget(widget)
        actions = QHBoxLayout()
        self.save_btn = button("Сохранить правки", "secondary", focus=True)
        self.delete_btn = button("Удалить", "text", focus=True)
        actions.addWidget(self.save_btn)
        actions.addWidget(self.delete_btn)
        form.addLayout(actions)
        destination = QFrame()
        destination.setObjectName("InboxDestination")
        target = QVBoxLayout(destination)
        target.setContentsMargins(12, 12, 12, 12)
        target.setSpacing(8)
        target.addWidget(label("ГОТОВО К ИЗУЧЕНИЮ?", "CaptureEyebrow"))
        target.addWidget(label("Выберите колоду и добавьте минимум один перевод.", "CaptureHint", wrap=True))
        self.deck = QComboBox()
        self.deck.setObjectName("InboxDeck")
        self.deck.setAccessibleName("Колода назначения")
        target.addWidget(self.deck)
        self.create_btn = button("Создать карточку", "primary", focus=True)
        target.addWidget(self.create_btn)
        form.addWidget(destination)
        self.error = label("", "DialogError", wrap=True)
        form.addWidget(self.error)
        form.addStretch()
        split.addWidget(scroll_area(self.details))
        split.setHandleWidth(12)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)
        self.empty = label("Входящих пока нет. Добавьте слово через значок Mnemo в трее.", "EmptyText", wrap=True)
        root.addWidget(self.empty)
        self.save_btn.clicked.connect(self.save)
        self.delete_btn.clicked.connect(self.delete)
        self.create_btn.clicked.connect(self.promote)

    def values(self):
        return (self.front.toPlainText(), self.translations.toPlainText(), self.context.toPlainText())

    def can_leave(self):
        return self._snapshot is None or self.values() == self._snapshot or confirm(
            self, "Несохранённые правки", "Отменить изменения заготовки?", "Отменить правки")

    def _back(self):
        if self.can_leave():
            self._snapshot = None
            self.back.emit()

    def refresh(self, select_id=None):
        entries = self.library.inbox.list()
        self.items.blockSignals(True)
        self.items.clear()
        self.heading.setText(f"Входящие · {len(entries)}")
        chosen = None
        for entry in entries:
            stamp = entry.created_at.astimezone().strftime("%d.%m.%Y")
            preview = " ".join(entry.context.split())
            if len(preview) > 60:
                preview = preview[:57] + "…"
            status = "Есть перевод" if entry.translations else "Без перевода"
            item = QListWidgetItem(f"{entry.front}\n{preview or 'Контекст не добавлен'}\n{status} · {stamp}")
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setToolTip(entry.front + ("\n" + entry.context if entry.context else ""))
            self.items.addItem(item)
            if entry.id == select_id:
                chosen = item
        self.items.setCurrentItem(chosen or self.items.item(0))
        self.items.blockSignals(False)
        self.empty.setVisible(not entries)
        self.details.setEnabled(bool(entries))
        selected_deck = self.deck.currentData()
        self.deck.clear()
        for deck in self.library.decks.list():
            self.deck.addItem(deck.name, deck.id)
        index = self.deck.findData(selected_deck)
        if index >= 0:
            self.deck.setCurrentIndex(index)
        self.create_btn.setEnabled(bool(entries) and self.deck.count() > 0)
        if not self.deck.count():
            self.deck.setPlaceholderText("Сначала создайте колоду")
        self._load(self.items.currentItem())

    def _selected(self, current, previous):
        if not self.can_leave():
            self.items.blockSignals(True)
            self.items.setCurrentItem(previous)
            self.items.blockSignals(False)
            return
        self._load(current)

    def _load(self, item):
        self.entry_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        entry = self.library.inbox.get(self.entry_id) if self.entry_id else None
        self.front.setPlainText(entry.front if entry else "")
        self.translations.setPlainText("\n".join(entry.translations) if entry else "")
        self.context.setPlainText(entry.context if entry else "")
        self.detail_title.setText(entry.front if entry else "Выберите слово")
        self.detail_meta.setText(
            f"Добавлено {entry.created_at.astimezone():%d.%m.%Y} · "
            + (f"Переводов: {len(entry.translations)}" if entry.translations else "Ожидает перевода")
            if entry else "Сохранённые слова появятся в списке слева.")
        self.error.clear()
        self._snapshot = self.values() if entry else None

    def save(self):
        if not self.entry_id:
            return
        try:
            self.library.save_inbox(self.entry_id, self.front.toPlainText(),
                                   self.translations.toPlainText().splitlines(), self.context.toPlainText())
        except ERRORS as exc:
            self.error.setText(str(exc))
            return
        self.refresh(self.entry_id)
        self.changed.emit()

    def delete(self):
        if not self.entry_id or not confirm(self, "Удалить заготовку", "Удалить это слово из входящих?", "Удалить", danger=True):
            return
        try:
            self.library.inbox.delete(self.entry_id)
        except ERRORS as exc:
            self.error.setText(str(exc))
            return
        self.refresh()
        self.changed.emit()

    def promote(self):
        if not self.entry_id:
            return
        front, translations, context = self.values()
        deck_id = self.deck.currentData()
        duplicate = bool(deck_id and self.library.find_duplicates(deck_id, front))
        if duplicate and not confirm(self, "Слово уже есть", "Создать ещё одну карточку в этой колоде?", "Создать дубликат"):
            return
        try:
            self.library.promote_inbox(self.entry_id, deck_id, front, translations.splitlines(),
                                       context, allow_duplicate=duplicate)
        except ERRORS as exc:
            self.error.setText(str(exc))
            return
        self.refresh()
        self.changed.emit()
