"""Экран сессии в стиле «Фокус» (docs/specs/repetition.md, разделы 2.1 и 5.1; docs/specs/design.md, раздел 7).

Ввод и самопроверка живут на одном экране без переключателя:
Enter с текстом проверяет ввод, Enter или Space на пустом поле показывают ответ.
Хранилище и планировщик подключаются главным окном через answerGiven.
"""

from __future__ import annotations

import time
import random
from enum import Enum

from PyQt6.QtCore import QEvent, QEasingCurve, QPropertyAnimation, QSize, Qt, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QKeySequence, QResizeEvent, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QFrame,
    QLayout,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mnemo.settings import (
    AGAIN_REINSERT_OFFSET,
    HINT_COLUMN_GAP,
    HINT_COLUMN_WIDTH,
    HINT_SHIFT_MS,
    LONG_FRONT_CHARS,
    MIN_MAIN_BLOCK_WIDTH,
    SESSION_MARGIN_X,
)
from mnemo.ui import strings as S
from mnemo.domain.answers import is_correct
from mnemo.domain.markup import display_text, target_text, translation_text
from mnemo.ui.card_text import set_front_text
from mnemo.domain.models import Grade
from mnemo.ui.demo_data import DemoCard
from mnemo.ui.identity import StackArt, SessionEntrance
from mnemo.ui.dialogs import TranslationDialog
from mnemo.ui.widgets import run_dialog


class State(Enum):
    QUESTION = "question"
    REVEALED = "revealed"  # ответ показан, самопроверка
    FORGOTTEN = "forgotten"  # «Не помню»: ответ и переход далее
    TYPED_OK = "typed_ok"  # введённый ответ верен
    TYPED_BAD = "typed_bad"  # введённый ответ неверен
    END = "end"


def _repolish(widget: QWidget) -> None:
    """Заставляет Qt заново применить QSS после смены динамического свойства."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _set_prop(widget: QWidget, name: str, value: str) -> None:
    widget.setProperty(name, value)
    _repolish(widget)


class AnswerInput(QLineEdit):
    """Поле ответа: Enter и Space на пустом поле отправляют сигнал `submitted`."""

    submitted = pyqtSignal()

    def event(self, event):
        # QLineEdit normally claims numeric shortcuts as text input.
        if (event.type() == QEvent.Type.ShortcutOverride
                and event.key() == Qt.Key.Key_1
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            event.ignore()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        if event is None:
            return
        key = event.key()
        is_enter = key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        is_space_on_empty = key == Qt.Key.Key_Space and not self.text().strip()
        if is_enter or is_space_on_empty:
            if not event.isAutoRepeat():
                self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)


GRADE_TILE_HEIGHT = 72  # две подписи (17 и 12 px) с отступами не должны обрезаться


class GradeButton(QPushButton):
    """Плитка оценки: название оценки цветом и подпись клавиши."""

    def __init__(self, grade: Grade, label: str, key_text: str) -> None:
        super().__init__()
        self.grade = grade
        self.setProperty("role", "grade")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(GRADE_TILE_HEIGHT)
        self.setMinimumWidth(110)
        self.setAccessibleName(label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        name = QLabel(label)
        name.setObjectName("GradeLabel")
        name.setProperty("grade", grade.value)
        key = QLabel(key_text)
        key.setObjectName("GradeKey")
        for lab in (name, key):
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            layout.addWidget(lab)


class FrontRow(QWidget):
    """Слово по центру; справа от него на расстоянии 24 px висит кнопка подсказки.

    Если слово слишком длинное и кнопка справа не помещается, кнопка переходит
    под слово по центру (docs/specs/design.md, раздел 7.5).
    """

    ROW_HEIGHT = 80
    GAP = 24

    def __init__(self) -> None:
        super().__init__()
        self.label = QLabel(self)
        self.label.setObjectName("Front")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.hint_button = QPushButton(self)
        self.hint_button.setProperty("role", "hint")
        self.hint_button.setProperty("active", "false")
        self.hint_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hint_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._height = self.ROW_HEIGHT
        self.setFixedHeight(self._height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_front(self, text: str) -> None:
        set_front_text(self.label, text)
        _set_prop(self.label, "frontLength", "long" if len(display_text(text, front=True)) > LONG_FRONT_CHARS else "normal")
        self.relayout()

    def relayout(self) -> None:
        width = self.width()
        self.label.ensurePolished()
        self.hint_button.ensurePolished()
        label_w = min(self.label.sizeHint().width(), max(width, 1))
        label_x = (width - label_w) // 2
        text_height = max(self.ROW_HEIGHT, self.label.heightForWidth(label_w))
        self.label.setGeometry(label_x, 0, label_w, text_height)

        button_size = self.hint_button.sizeHint()
        bw, bh = button_size.width(), button_size.height()
        fits = label_w <= width - 2 * (self.GAP + bw)
        if fits or not self.hint_button.isVisibleTo(self):
            self._set_height(text_height)
            self.hint_button.setGeometry(label_x + label_w + self.GAP, (text_height - bh) // 2, bw, bh)
        else:
            self._set_height(text_height + 8 + bh)
            self.hint_button.setGeometry((width - bw) // 2, text_height + 4, bw, bh)

    def _set_height(self, value: int) -> None:
        if value != self._height:
            self._height = value
            self.setFixedHeight(value)

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self.relayout()

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        self.relayout()

    def sizeHint(self) -> QSize:
        return QSize(400, self._height)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self._height)


class HintColumn(QWidget):
    """Правая колонка «ПОДСКАЗКИ»: ширина плавно меняется от 0 до 24 + 220 px.

    Содержимое не использует layout самой колонки, поэтому колонка может
    сжиматься до нуля, а текст не перестраивается во время анимации.
    """

    FULL_WIDTH = HINT_COLUMN_GAP + HINT_COLUMN_WIDTH
    TOP_PADDING = 8

    def __init__(self) -> None:
        super().__init__()
        self._reveal = 0
        self.setFixedWidth(0)
        self._inner = QWidget(self)
        layout = QVBoxLayout(self._inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        title = QLabel(S.CAPTION_HINTS)
        title.setObjectName("Caption")
        layout.addWidget(title)
        self._rows = QVBoxLayout()
        self._rows.setSpacing(12)
        layout.addLayout(self._rows)
        layout.addStretch(1)

    def _get_reveal(self) -> int:
        return self._reveal

    def _set_reveal(self, value: int) -> None:
        self._reveal = value
        self.setFixedWidth(max(0, value))

    reveal = pyqtProperty(int, _get_reveal, _set_reveal)

    def clear(self) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def add_hint(self, number: int, text: str) -> None:
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        num = QLabel(str(number))
        num.setObjectName("HintNum")
        num.setAlignment(Qt.AlignmentFlag.AlignTop)
        body = QLabel(text)
        body.setObjectName("HintText")
        body.setWordWrap(True)
        box.addWidget(num, 0, Qt.AlignmentFlag.AlignTop)
        box.addWidget(body, 1)
        self._rows.addWidget(row)

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self._inner.setGeometry(
            HINT_COLUMN_GAP, self.TOP_PADDING, HINT_COLUMN_WIDTH, max(0, self.height() - self.TOP_PADDING)
        )


class SessionScreen(QWidget):
    """Экран сессии. Вся логика состояний здесь, данные карточек приходят снаружи."""

    answerGiven = pyqtSignal(dict)  # каждая оценка сразу уходит наружу для записи (FR-S5, FR-S7)
    translationRequested = pyqtSignal(dict)
    exitRequested = pyqtSignal()  # «Завершить» без ответов или «К колодам» на экране итога

    def __init__(
        self, deck_name: str, cards: list[DemoCard], allow_restart: bool = True,
        *, allow_error_repeat: bool = False, free_practice: bool = False,
    ) -> None:
        super().__init__()
        self._allow_restart = allow_restart
        self._allow_error_repeat = allow_error_repeat
        self._free_practice = free_practice
        self._shown_at = time.monotonic()
        self._response_ms = 0
        self.setObjectName("Root")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._deck_name = deck_name
        self._cards = cards
        self._queue: list[int] = []
        self._done = 0
        self._results: list[dict] = []
        self._state = State.QUESTION
        self._hints_open = 0
        self._typed_answer = ""
        self._overridden = False
        self._column_target = False

        self._build_ui()
        self._hint_anim = QPropertyAnimation(self._hint_col, b"reveal", self)
        self._hint_anim.setDuration(HINT_SHIFT_MS)
        self._hint_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hint_shortcut = QShortcut(QKeySequence("Tab"), self, activated=self.use_hint)
        self._hint_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._hint_shortcut.setAutoRepeat(False)
        self._forget_shortcut = QShortcut(QKeySequence("1"), self, activated=self.forget)
        self._finish_shortcut = QShortcut(QKeySequence("Esc"), self, activated=self._on_finish_clicked)
        for shortcut in (self._forget_shortcut, self._finish_shortcut):
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.setAutoRepeat(False)
        self.restart()
        self.entrance = SessionEntrance(self)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(SESSION_MARGIN_X, 24, SESSION_MARGIN_X, 26)
        root.setSpacing(0)

        # верхняя строка
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(StackArt(logo=True))
        brand = QLabel("Mnemo")
        brand.setObjectName("Brand")
        deck = QLabel(self._deck_name)
        deck.setObjectName("DeckName")
        deck.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        deck.setToolTip(self._deck_name)
        self._finish_btn = QPushButton(S.BTN_FINISH + " · Esc")
        self._finish_btn.setProperty("role", "finish")
        self._finish_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._finish_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._finish_btn.clicked.connect(self._on_finish_clicked)
        top.addWidget(brand)
        top.addWidget(deck, 1)
        top.addStretch(1)
        top.addWidget(self._finish_btn)
        self.header = top
        root.addLayout(top)

        # прогресс
        root.addSpacing(14)
        progress_row = QHBoxLayout()
        progress_row.setSpacing(12)
        progress_row.addStretch(1)
        self._progress = QProgressBar()
        self._progress.setObjectName("Progress")
        self._progress.setTextVisible(False)
        self._progress.setFixedSize(360, 4)
        self._counter = QLabel()
        self._counter.setObjectName("Counter")
        progress_row.addWidget(self._progress, 0, Qt.AlignmentFlag.AlignVCenter)
        progress_row.addWidget(self._counter)
        progress_row.addStretch(1)
        root.addLayout(progress_row)
        root.addSpacing(24)

        # тело: основной блок + колонка подсказок
        self._body = QWidget()
        body_layout = QHBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self._main_col = self._build_main_column()
        self._study_scroll = QScrollArea()
        self._study_scroll.setWidgetResizable(True)
        self._study_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._study_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._study_scroll.setWidget(self._main_col)
        self._hint_col = HintColumn()
        body_layout.addWidget(self._study_scroll, 1)
        body_layout.addWidget(self._hint_col, 0)
        root.addWidget(self._body, 1)

        self._end_body = self._build_end_body()
        root.addWidget(self._end_body, 1)

    def _build_main_column(self) -> QWidget:
        col = QWidget()
        col.setObjectName("StudyCard")
        col.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(col)
        lay.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        lay.setContentsMargins(18, 24, 18, 16)
        lay.setSpacing(0)
        center = Qt.AlignmentFlag.AlignHCenter

        caption = QLabel(S.CAPTION_TRANSLATE)
        self._caption = caption
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(caption)
        lay.addSpacing(16)

        self._front_row = FrontRow()
        self._front_row.hint_button.clicked.connect(self.use_hint)
        lay.addWidget(self._front_row)

        # подсказки в потоке блока (узкое окно)
        self._inline_hints = QLabel()
        self._inline_hints.setObjectName("HintInline")
        self._inline_hints.setWordWrap(True)
        self._inline_hints.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._inline_hints.setMaximumWidth(460)
        self._inline_hints_wrap = QWidget()
        wrap_lay = QHBoxLayout(self._inline_hints_wrap)
        wrap_lay.setContentsMargins(0, 8, 0, 0)
        wrap_lay.addStretch(1)
        wrap_lay.addWidget(self._inline_hints, 1000)
        wrap_lay.addStretch(1)
        self._inline_hints_wrap.hide()
        lay.addWidget(self._inline_hints_wrap)

        # поле ввода, результат и главная кнопка
        self._input_wrap = QWidget()
        self._input_lay = QVBoxLayout(self._input_wrap)
        self._input_lay.setContentsMargins(0, 40, 0, 0)
        self._input_lay.setSpacing(0)
        self._input = AnswerInput()
        self._input.setObjectName("AnswerInput")
        self._input.setPlaceholderText(S.INPUT_PLACEHOLDER)
        self._input.setAccessibleName(S.INPUT_ACCESSIBLE_NAME)
        self._input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._input.setFixedWidth(460)
        self._input.submitted.connect(self.submit)
        self._input.textChanged.connect(self._update_primary_text)
        self._input_lay.addWidget(self._input, 0, center)

        self._result = QLabel()
        self._result.setObjectName("Result")
        self._result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result.setContentsMargins(0, 10, 0, 0)
        self._input_lay.addWidget(self._result)

        self._primary_wrap = QWidget()
        pw = QHBoxLayout(self._primary_wrap)
        pw.setSpacing(12)
        pw.setContentsMargins(0, 34, 0, 0)
        self._primary = QPushButton(S.BTN_SHOW_ANSWER)
        self._primary.setProperty("role", "primary")
        self._primary.setCursor(Qt.CursorShape.PointingHandCursor)
        self._primary.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._primary.clicked.connect(self.submit)
        self._forget_btn = QPushButton(S.GRADE_AGAIN + " · 1")
        self._forget_btn.setProperty("role", "forget")
        self._forget_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._forget_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._forget_btn.clicked.connect(self.forget)
        pw.addStretch(1)
        pw.addWidget(self._forget_btn)
        pw.addWidget(self._primary)
        pw.addStretch(1)
        self._input_lay.addWidget(self._primary_wrap)
        lay.addWidget(self._input_wrap)

        # ответ: переводы и примеры
        self._answer_box = QWidget()
        self._answer_lay = QVBoxLayout(self._answer_box)
        self._answer_lay.setContentsMargins(0, 36, 0, 0)
        self._answer_lay.setSpacing(0)
        self._translation = QLabel()
        self._translation.setTextFormat(Qt.TextFormat.PlainText)
        self._translation.setObjectName("Translation")
        self._translation.setWordWrap(True)
        self._translation.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._answer_lay.addWidget(self._translation)
        self._examples_box = QWidget()
        self._examples_lay = QVBoxLayout(self._examples_box)
        self._examples_lay.setContentsMargins(0, 28, 0, 0)
        self._examples_lay.setSpacing(12)
        self._answer_lay.addWidget(self._examples_box)
        lay.addWidget(self._answer_box)

        lay.addStretch(1)

        # плитки оценок
        # Внешний контейнер занимает всю ширину, плитки внутри него центрируются распорками
        # и растут до 760 px. (Центрирование через alignment сжимало плитки до минимума.)
        self._grade_row = QWidget()
        outer_lay = QHBoxLayout(self._grade_row)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(0)
        tiles = QWidget()
        tiles.setMaximumWidth(760)
        grade_lay = QHBoxLayout(tiles)
        grade_lay.setContentsMargins(0, 0, 0, 0)
        grade_lay.setSpacing(10)
        outer_lay.addStretch(1)
        outer_lay.addWidget(tiles, 1000)
        outer_lay.addStretch(1)
        self._grade_buttons: dict[Grade, GradeButton] = {}
        for grade, label, key in (
            (Grade.HARD, S.GRADE_HARD, S.KEY_HARD),
            (Grade.GOOD, S.GRADE_GOOD, S.KEY_GOOD),
            (Grade.EASY, S.GRADE_EASY, S.KEY_EASY),
        ):
            button = GradeButton(grade, label, key)
            button.clicked.connect(lambda _checked=False, g=grade: self.grade(g))
            grade_lay.addWidget(button, 1)
            self._grade_buttons[grade] = button
        lay.addWidget(self._grade_row)

        # кнопки после неверного ответа
        self._wrong_row = QWidget()
        wrong_lay = QHBoxLayout(self._wrong_row)
        wrong_lay.setContentsMargins(0, 0, 0, 0)
        wrong_lay.setSpacing(10)
        self._override_btn = QPushButton(S.BTN_I_WAS_RIGHT)
        self._override_btn.setProperty("role", "text")
        self._next_btn = QPushButton(S.BTN_NEXT)
        self._next_btn.setProperty("role", "primary")
        for btn in (self._override_btn, self._next_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._override_btn.clicked.connect(self.override_correct)
        self._next_btn.clicked.connect(self.next_after_wrong)
        wrong_lay.addStretch(1)
        wrong_lay.addWidget(self._override_btn)
        wrong_lay.addWidget(self._next_btn)
        wrong_lay.addStretch(1)
        lay.addWidget(self._wrong_row)

        lay.addSpacing(16)
        self._footer = QLabel()
        self._footer.setWordWrap(True)
        self._footer.setObjectName("Shortcuts")
        self._footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._footer.setMinimumHeight(18)
        lay.addWidget(self._footer)
        return col

    def _build_end_body(self) -> QWidget:
        box = QWidget()
        box.setObjectName("CompletionCard")
        box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addStretch(2)
        self._end_art = StackArt()
        self._end_art.setFixedSize(220, 150)
        lay.addWidget(self._end_art, 0, Qt.AlignmentFlag.AlignHCenter)
        title = QLabel(S.END_TITLE)
        self._end_title = title
        title.setObjectName("EndTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._end_summary = QLabel()
        self._end_summary.setObjectName("EndSummary")
        self._end_summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._restart_btn = QPushButton(S.BTN_RESTART)
        self._restart_btn.setProperty("role", "primary")
        self._restart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._restart_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._restart_btn.clicked.connect(self.restart)
        lay.addWidget(title)
        lay.addSpacing(16)
        lay.addWidget(self._end_summary)
        lay.addSpacing(36)
        self._restart_btn.setVisible(self._allow_restart)
        lay.addWidget(self._restart_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        self._errors_btn = QPushButton(S.BTN_REPEAT_ERRORS)
        self._errors_btn.setProperty("role", "secondary")
        self._errors_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._errors_btn.clicked.connect(self.repeat_errors)
        self._errors_btn.setVisible(self._allow_error_repeat)
        lay.addWidget(self._errors_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(8)
        self._exit_btn = QPushButton(S.BTN_BACK)
        self._exit_btn.setProperty("role", "text" if self._allow_restart else "primary")
        self._exit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._exit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._exit_btn.clicked.connect(self.exitRequested.emit)
        lay.addWidget(self._exit_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(3)
        return box

    # ------------------------------------------------------------ свойства

    @property
    def state(self) -> State:
        return self._state

    @property
    def is_finished(self) -> bool:
        return self._state is State.END

    @property
    def results(self) -> list[dict]:
        return list(self._results)

    @property
    def current_card(self) -> DemoCard | None:
        return self._cards[self._queue[0]] if self._queue else None

    @property
    def hints_open(self) -> int:
        return self._hints_open

    @property
    def hint_column_open(self) -> bool:
        """Колонка подсказок раскрыта (или раскрывается)."""
        return self._column_target

    @property
    def primary_text(self) -> str:
        return self._primary.text()

    # ----------------------------------------------------------- сессия

    def restart(self) -> None:
        self._queue = list(range(len(self._cards)))
        self._start_pass()

    def repeat_errors(self) -> None:
        if self._state is not State.END or not self._allow_error_repeat:
            return
        failed = {r["card_id"] for r in self._results if r["grade"] is Grade.AGAIN}
        self._queue = [i for i, c in enumerate(self._cards) if c.card_id in failed]
        if not self._queue:
            return
        random.shuffle(self._queue)
        self._start_pass()

    def _start_pass(self) -> None:
        self._pass_total = len(self._queue)
        self._done = 0
        self._results = []
        self._end_body.hide()
        self._body.show()
        self._finish_btn.show()
        self._show_card()

    def _on_finish_clicked(self) -> None:
        # Если ни одного ответа не дано, показывать итог незачем: сразу назад.
        if self._results:
            self.finish()
        else:
            self.exitRequested.emit()

    def finish(self) -> None:
        """Завершить сессию досрочно или после последней карточки."""
        self._set_hint_view(column=False, inline=False, animate=False)
        self._state = State.END
        self._hint_shortcut.setEnabled(False)
        self._forget_shortcut.setEnabled(False)
        self._finish_shortcut.setEnabled(False)
        counts = {g: 0 for g in Grade}
        for item in self._results:
            counts[item["grade"]] += 1
        self._end_summary.setText(
            S.END_SUMMARY.format(
                total=len(self._results),
                again=counts[Grade.AGAIN],
                hard=counts[Grade.HARD],
                good=counts[Grade.GOOD],
                easy=counts[Grade.EASY],
            )
        )
        if self._free_practice:
            total = len(self._results)
            failures = counts[Grade.AGAIN]
            successes = total - failures
            percent = f"{round(100 * successes / total)}%" if total else "—"
            self._end_summary.setText(
                self._end_summary.text() + "\n" + S.FREE_END_SUMMARY.format(
                    successes=successes, failures=failures, percent=percent,
                )
            )
        self._body.hide()
        self._end_body.show()
        self._end_title.setText("Колода повторена" if not self._queue else S.END_TITLE)
        self._end_art.gather()
        self._errors_btn.setEnabled(any(r["grade"] is Grade.AGAIN for r in self._results))
        self._finish_btn.hide()
        self._update_progress()
        self.setFocus()

    def _show_card(self) -> None:
        card = self.current_card
        if card is None:
            self.finish()
            return
        self._hints_open = 0
        self._typed_answer = ""
        self._overridden = False
        self._shown_at = time.monotonic()
        self._response_ms = 0
        self._front_row.set_front(card.front)
        target = target_text(card.front)
        if target is None:
            self._caption.setText(S.CAPTION_TRANSLATE)
        elif len(target.split()) == 1:
            self._caption.setText("ПЕРЕВЕДИТЕ ВЫДЕЛЕННОЕ СЛОВО В СЛОВАРНОЙ ФОРМЕ")
        else:
            self._caption.setText("ПЕРЕВЕДИТЕ ВЫДЕЛЕННОЕ ВЫРАЖЕНИЕ ЦЕЛИКОМ")
        self._caption.setToolTip("Для отдельного слова: прилагательное — мужской род, единственное число; "
                                 "глагол — инфинитив; существительное — именительный падеж. "
                                 "Контексты через / показаны одновременно. В ответе достаточно одного варианта.")
        self._front_row.hint_button.setVisible(bool(card.hints))
        self._update_hint_button()
        self._hint_col.clear()
        self._inline_hints.setText("")
        self._translation.setText(translation_text(card.translations))
        self._fill_examples(card)
        self._input.setReadOnly(False)
        self._input.clear()
        _set_prop(self._input, "state", "")
        self._set_state(State.QUESTION)
        self._update_progress()

    def _fill_examples(self, card: DemoCard) -> None:
        while self._examples_lay.count():
            item = self._examples_lay.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._examples_box.setVisible(bool(card.examples))
        for original, translated in card.examples:
            block = QWidget()
            box = QVBoxLayout(block)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(4)
            one = QLabel(original)
            one.setObjectName("Example")
            two = QLabel(translated)
            two.setObjectName("ExampleTr")
            for lab in (one, two):
                lab.setWordWrap(True)
                lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
                box.addWidget(lab)
            two.setVisible(bool(translated))
            self._examples_lay.addWidget(block)

    def _update_progress(self) -> None:
        total = self._pass_total
        position = total if self._state is State.END else min(self._done + 1, total)
        self._progress.setMaximum(max(total, 1))
        self._progress.setValue(position)
        self._counter.setText(f"{position} / {total}")

    def _advance(self, grade: Grade) -> None:
        """Записывает результат текущей карточки и переходит к следующей."""
        card_index = self._queue[0]
        result = {
                "card_id": self._cards[card_index].card_id,
                "response_time_ms": self._response_ms,
                "front": self._cards[card_index].front,
                "grade": grade,
                "mode": "typed" if self._typed_answer else "self",
                "typed_answer": self._typed_answer or None,
                "hints_used": self._hints_open,
                "overridden": self._overridden,
        }
        self.answerGiven.emit(result)
        if result.get("saved") is False:
            return
        self._queue.pop(0)
        self._results.append(result)
        if grade is Grade.AGAIN:
            self._queue.insert(min(AGAIN_REINSERT_OFFSET, len(self._queue)), card_index)
        else:
            self._done += 1
        self._show_card()

    # ---------------------------------------------------------- действия

    def submit(self) -> None:
        """Единая точка входа: непустой ввод проверяется, пустой открывает ответ."""
        if self._state is not State.QUESTION:
            return
        text = self._input.text().strip()
        if text:
            self.submit_answer(text)
        else:
            self.reveal()

    def reveal(self) -> None:
        if self._state is not State.QUESTION:
            return
        self._mark_response_time()
        self._set_state(State.REVEALED)

    def forget(self) -> None:
        if self._state is not State.QUESTION:
            return
        self._typed_answer = ""
        self._mark_response_time()
        self._set_state(State.FORGOTTEN)

    def _mark_response_time(self) -> None:
        self._response_ms = int((time.monotonic() - self._shown_at) * 1000)

    def submit_answer(self, text: str) -> None:
        if self._state is not State.QUESTION:
            return
        if not text.strip():
            self.reveal()
            return
        card = self.current_card
        assert card is not None
        self._typed_answer = text
        self._mark_response_time()
        self._input.setText(text)
        correct = is_correct(text, card.translations)
        self._set_state(State.TYPED_OK if correct else State.TYPED_BAD)

    def override_correct(self) -> None:
        if self._state is not State.TYPED_BAD:
            return
        card = self.current_card
        assert card is not None
        run_dialog(self.window(), TranslationDialog(
            self, self._typed_answer, len(card.translations), self.save_variant,
        ))

    def save_variant(self, text: str) -> str | None:
        """Return a form error; accept only after persistence succeeds."""
        if self._state is not State.TYPED_BAD or self.current_card is None:
            return "Ответ уже изменился"
        request = {"card_id": self.current_card.card_id, "text": text,
                   "error": "Не удалось сохранить вариант перевода"}
        self.translationRequested.emit(request)
        if request["error"]:
            return request["error"]
        self.current_card.translations = list(request["translations"])
        self._translation.setText(translation_text(self.current_card.translations))
        self._overridden = True
        self._set_state(State.TYPED_OK)
        return None

    def next_after_wrong(self) -> None:
        if self._state in (State.TYPED_BAD, State.FORGOTTEN):
            self._advance(Grade.AGAIN)

    def grade(self, grade: Grade) -> None:
        if self._state in (State.REVEALED, State.TYPED_OK) and grade is not Grade.AGAIN:
            self._advance(grade)

    def use_hint(self) -> None:
        card = self.current_card
        if self._state is not State.QUESTION or card is None:
            return
        if self._hints_open >= len(card.hints):
            return
        text = card.hints[self._hints_open]
        self._hints_open += 1
        self._hint_col.add_hint(self._hints_open, text)
        self._update_hint_button()
        self._refresh_hint_view()

    # ------------------------------------------------- состояния и подсказки

    def _set_state(self, state: State) -> None:
        self._state = state
        card = self.current_card
        question = state is State.QUESTION
        if hasattr(self, "_hint_shortcut"):
            self._hint_shortcut.setEnabled(question)
            self._forget_shortcut.setEnabled(question)
            self._finish_shortcut.setEnabled(True)
        self._study_scroll.verticalScrollBar().setValue(0)
        typed = state in (State.TYPED_OK, State.TYPED_BAD)
        shown = state is not State.QUESTION

        self._input_wrap.setVisible(question or typed)
        self._input_lay.setContentsMargins(0, 40 if question else 24, 0, 0)
        self._input.setReadOnly(typed)
        self._input.setFocusPolicy(
            Qt.FocusPolicy.StrongFocus if question else Qt.FocusPolicy.NoFocus
        )
        self._primary_wrap.setVisible(question)
        self._result.setVisible(typed)
        if typed:
            ok = state is State.TYPED_OK
            _set_prop(self._input, "state", "ok" if ok else "bad")
            _set_prop(self._result, "state", "ok" if ok else "bad")
            if not ok:
                self._result.setText(S.RESULT_BAD)
            elif self._overridden:
                self._result.setText(S.RESULT_OVERRIDDEN)
            else:
                self._result.setText(S.RESULT_OK)
        self._answer_box.setVisible(shown)
        self._answer_lay.setContentsMargins(0, 24 if typed else 36, 0, 0)

        has_hints = bool(card and card.hints)
        self._front_row.hint_button.setVisible(question and has_hints)
        self._front_row.relayout()

        self._grade_row.setVisible(state in (State.REVEALED, State.TYPED_OK))
        self._wrong_row.setVisible(state in (State.TYPED_BAD, State.FORGOTTEN))
        self._override_btn.setVisible(state is State.TYPED_BAD)

        if question:
            self._footer.setText(S.FOOTER_QUESTION if has_hints else S.FOOTER_QUESTION_NO_HINTS)
            self._update_primary_text()
            self._refresh_hint_view()
            self._input.setFocus()
        else:
            self._footer.setText(S.FOOTER_TYPED_WRONG if state in (State.TYPED_BAD, State.FORGOTTEN) else S.FOOTER_EMPTY)
            # После показа ответа подсказки больше не показываются (docs/specs/repetition.md, FR-S3).
            self._set_hint_view(column=False, inline=False, animate=True)
            self.setFocus()

    def _update_primary_text(self) -> None:
        has_text = bool(self._input.text().strip())
        self._primary.setText(S.BTN_CHECK if has_text else S.BTN_SHOW_ANSWER)

    def _update_hint_button(self) -> None:
        card = self.current_card
        total = len(card.hints) if card else 0
        button = self._front_row.hint_button
        button.setText(S.HINT_BUTTON.format(used=self._hints_open, total=total))
        button.setEnabled(self._hints_open < total)
        _set_prop(button, "active", "true" if self._hints_open else "false")
        self._front_row.relayout()

    def _column_fits(self) -> bool:
        free = self.width() - 2 * SESSION_MARGIN_X - HintColumn.FULL_WIDTH
        return free >= MIN_MAIN_BLOCK_WIDTH

    def _refresh_hint_view(self) -> None:
        if self._state is not State.QUESTION or self._hints_open == 0:
            self._set_hint_view(column=False, inline=False, animate=True)
            return
        fits = self._column_fits()
        self._set_hint_view(column=fits, inline=not fits, animate=True)

    def _set_hint_view(self, column: bool, inline: bool, animate: bool) -> None:
        if inline:
            card = self.current_card
            hints = card.hints[: self._hints_open] if card else []
            self._inline_hints.setText("\n".join(f"{i}. {t}" for i, t in enumerate(hints, 1)))
        self._inline_hints.setVisible(inline)
        self._inline_hints_wrap.setVisible(inline)
        self._column_target = column
        target = HintColumn.FULL_WIDTH if column else 0
        self._hint_anim.stop()
        if animate and self._hint_col.reveal != target and self.isVisible():
            self._hint_anim.setStartValue(self._hint_col.reveal)
            self._hint_anim.setEndValue(target)
            self._hint_anim.start()
        else:
            self._hint_col.reveal = target

    def finish_animations(self) -> None:
        """Мгновенно доводит анимацию сдвига до конца (для тестов и скриншотов)."""
        self._hint_anim.stop()
        self._hint_col.reveal = HintColumn.FULL_WIDTH if self._column_target else 0
        self._end_art.anim.stop()
        self._end_art._update_amount(0.0 if self._end_art.complete else 1.0)
        self.entrance.anim.stop()
        self.entrance.hide()

    # -------------------------------------------------------------- события

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        if self._state is State.QUESTION and self._hints_open:
            self._refresh_hint_view()

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        if event is None:
            return
        if event.isAutoRepeat():
            event.accept()
            return
        key = event.key()
        enter = key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        grades = {
            Qt.Key.Key_2: Grade.HARD,
            Qt.Key.Key_3: Grade.GOOD,
            Qt.Key.Key_4: Grade.EASY,
        }
        handled = True
        if self._state in (State.REVEALED, State.TYPED_OK):
            if enter:
                self.grade(Grade.GOOD)
            elif key in grades:
                self.grade(grades[key])
            else:
                handled = False
        elif self._state in (State.TYPED_BAD, State.FORGOTTEN):
            if enter:
                self.next_after_wrong()
            else:
                handled = False
        elif self._state is State.END:
            if enter:
                if self._allow_restart:
                    self.restart()
                else:
                    self.exitRequested.emit()
            else:
                handled = False
        else:
            handled = False
        if handled:
            event.accept()
        else:
            super().keyPressEvent(event)
