"""Настройка свободной сессии из всей библиотеки."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QRadioButton, QVBoxLayout, QWidget

from mnemo.services import Library
from mnemo.ui import strings as S
from mnemo.ui.widgets import button, field, label


class SessionSetup(QWidget):
    back = pyqtSignal()
    startRequested = pyqtSignal(object)  # None: все; int: случайные N

    def __init__(self, library: Library) -> None:
        super().__init__()
        self._library = library
        self._available = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 24, 40, 26)
        self.back_btn = button(S.BACK_TO_DECKS, "back", focus=True)
        self.back_btn.clicked.connect(self.back.emit)
        self.header = QHBoxLayout()
        self.header.addWidget(self.back_btn)
        self.header.addStretch()
        root.addLayout(self.header)
        root.addSpacing(26)
        root.addWidget(label(S.POOL_TITLE, "Heading"))
        self.available = label("", "Meta")
        root.addWidget(self.available)
        root.addSpacing(24)
        panel = QWidget()
        panel.setObjectName("FormPanel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        form = QVBoxLayout(panel)
        form.setContentsMargins(24, 24, 24, 24)
        form.setSpacing(12)
        self.all_cards = QRadioButton(S.POOL_ALL)
        self.random_cards = QRadioButton(S.POOL_RANDOM)
        self.all_cards.setChecked(True)
        form.addWidget(self.all_cards)
        form.addWidget(self.random_cards)
        self.count = field(S.POOL_COUNT)
        self.count.setMaxLength(9)
        self.count.setText("20")
        self.count.setMaximumWidth(360)
        form.addWidget(self.count)
        self.error = label("", "DialogError", wrap=True)
        form.addWidget(self.error)
        form.addSpacing(20)
        form.addWidget(label(S.POOL_HINT, "Meta", wrap=True))
        form.addSpacing(24)
        self.start_btn = button(S.POOL_START, "primary", focus=True)
        self.start_btn.clicked.connect(self._start)
        form.addWidget(self.start_btn, 0, Qt.AlignmentFlag.AlignLeft)
        root.addWidget(panel)
        root.addStretch(1)
        self.all_cards.toggled.connect(self._validate)
        self.count.textChanged.connect(self._validate)
        self.count.returnPressed.connect(self._start)

    def refresh(self) -> None:
        self._available = sum(s.card_count for s in self._library.deck_summaries())
        self.available.setText(S.POOL_AVAILABLE.format(n=self._available))
        self._validate()

    def _validate(self) -> None:
        self.count.setEnabled(self.random_cards.isChecked())
        text = self.count.text().strip()
        valid = self.all_cards.isChecked() or (
            text.isascii() and text.isdecimal() and 1 <= int(text) <= self._available
        )
        self.start_btn.setEnabled(valid and self._available > 0)
        self.error.setText("" if valid else S.POOL_INVALID.format(n=self._available))

    def _start(self) -> None:
        self.refresh()
        if self.start_btn.isEnabled():
            self.startRequested.emit(None if self.all_cards.isChecked() else int(self.count.text()))
