"""Главный экран: выбранная колода, очередь на сегодня и горизонтальная лента."""

import sqlite3

from PyQt6.QtCore import QEasingCurve, QEvent, QPointF, QPropertyAnimation, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QPainter, QTextLayout, QTextOption
from PyQt6.QtWidgets import QStyle, QStyleOptionButton
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QSpacerItem, QVBoxLayout, QWidget

from mnemo.domain.models import utcnow
from mnemo.ui import strings as S
from mnemo.ui.identity import CoverTile, FocusCover, StackArt, motion_enabled
from mnemo.ui.text import cards_count, plural
from mnemo.ui.widgets import RoundedMenu, button, clear_layout, icon_button, label, scroll_area, set_prop


def _two_lines(text, font, metrics, width):
    layout = QTextLayout(" ".join(text.split()), font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    layout.beginLayout()
    line = layout.createLine()
    if line.isValid():
        line.setLineWidth(max(1, width))
        end = line.textLength()
    else:
        end = 0
    layout.endLayout()
    text = layout.text()
    return (text[:end].rstrip(), metrics.elidedText(text[end:].strip(), Qt.TextElideMode.ElideRight, max(1, width)))


class FocusTitle(QPushButton):
    def minimumSizeHint(self):
        return QSize(100, self.fontMetrics().lineSpacing() * 2 + 4)

    def sizeHint(self):
        return self.minimumSizeHint()

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        painter = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self)
        painter.setPen(option.palette.buttonText().color())
        metrics = self.fontMetrics()
        lines = _two_lines(self.text(), self.font(), metrics, self.width() - 28)
        baseline = self.height() - metrics.descent() - 3
        if lines[1]:
            painter.drawText(QPointF(2, baseline - metrics.lineSpacing()), lines[0])
            painter.drawText(QPointF(2, baseline), lines[1])
        else:
            painter.drawText(QPointF(2, baseline), lines[0])
        x = self.width() - 16
        y = baseline - metrics.ascent() / 2
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawLine(QPointF(x - 3, y - 4), QPointF(x + 1, y))
        painter.drawLine(QPointF(x + 1, y), QPointF(x - 3, y + 4))


class DeckRow(QPushButton):
    activated = pyqtSignal(str, bool)
    openRequested = pyqtSignal(str)

    WIDTH = 234

    def __init__(self, summary, cover_id, height):
        super().__init__()
        self.deck_id = summary.deck.id
        self.setObjectName("DeckRow")
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFixedSize(self.WIDTH, height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mouse_release = False
        self.clicked.connect(lambda: self.activated.emit(self.deck_id, self._mouse_release))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addWidget(CoverTile(cover_id))
        details = QVBoxLayout()
        details.setSpacing(2)
        details.addStretch()
        self.title = label("", "StripTitle", wrap=True)
        self.title.setMaximumHeight(42)
        self.count = label("", "StripMeta")
        self.due = label("", "StripMeta")
        for item in (self.title, self.count, self.due):
            item.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            item.setTextFormat(Qt.TextFormat.PlainText)
            details.addWidget(item)
        details.addStretch()
        layout.addLayout(details, 1)
        self.update_summary(summary)

    def nextCheckState(self):
        # The screen owns selection, including while a click is pending.
        pass

    def mouseReleaseEvent(self, event):
        self._mouse_release = True
        try:
            super().mouseReleaseEvent(event)
        finally:
            self._mouse_release = False

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setDown(False)
            event.accept()
            self.openRequested.emit(self.deck_id)
            return
        super().mouseDoubleClickEvent(event)

    def update_summary(self, summary):
        name = summary.deck.name
        count = cards_count(summary.card_count)
        due = f"{summary.due_count} к повторению" if summary.due_count else (
            "Всё повторено" if summary.card_count else "Пустая колода"
        )
        self.title.ensurePolished()
        lines = _two_lines(name, self.title.font(), self.title.fontMetrics(), 134)
        self.title.setText("\n".join(filter(None, lines)))
        self.count.setText(count)
        self.due.setText(due)
        self.setToolTip(name)
        self.setAccessibleName(f"{name}, {count}, {due}")


class DecksScreen(QWidget):
    inboxRequested = pyqtSignal()
    openDeck = pyqtSignal(str)
    openDeckFromRail = pyqtSignal(str)
    repeatAll = pyqtSignal(str)
    study = pyqtSignal(object)
    createRequested = pyqtSignal()
    renameRequested = pyqtSignal(str)
    deleteRequested = pyqtSignal(str)
    exportRequested = pyqtSignal(str)
    importRequested = pyqtSignal()
    statsRequested = pyqtSignal()
    poolRequested = pyqtSignal()
    coverRequested = pyqtSignal(str)
    themeRequested = pyqtSignal()
    saveFailed = pyqtSignal(str)

    def __init__(self, library):
        super().__init__()
        self._library = library
        self._summaries = {}
        self._tiles = {}
        self._tile_height = 100
        self._display_scale = None
        self.selected_id = library.preferences.get("focused_deck")
        self._pending_click: tuple[str, str | None] | None = None
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._click_timer.timeout.connect(self._commit_rail_click)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(24)
        self.header = QHBoxLayout()
        self.header.setSpacing(12)
        self.header.addWidget(StackArt(logo=True))
        self.brand = label("Mnemo", "Brand")
        self.header.addWidget(self.brand)
        self.header.addStretch(1)
        self.inbox_btn = self._nav("Входящие", self.inboxRequested, "nav")
        self.stats_btn = self._nav("Статистика", self.statsRequested, "nav")
        self.import_btn = self._nav("Импорт", self.importRequested, "nav")
        self.create_btn = self._nav("+ Колода", self.createRequested, "secondary")
        self.appearance_btn = icon_button("settings", "Настройки оформления")
        self.appearance_btn.clicked.connect(self.themeRequested.emit)
        self.header.addWidget(self.appearance_btn)
        root.addLayout(self.header)

        self._content = QWidget()
        self._content.setMaximumWidth(1380)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(16)
        self.columns = QHBoxLayout()
        self.columns.setSpacing(30)
        self.hero = FocusCover()
        self.hero.setMaximumWidth(760)
        self.hero.setFixedHeight(410)
        focus = QVBoxLayout(self.hero)
        focus.setContentsMargins(23, 16, 23, 22)
        focus_head = QHBoxLayout()
        focus_head.addWidget(label("В ФОКУСЕ", "Caption"))
        focus_head.addStretch()
        self.more_btn = icon_button("more", "Меню выбранной колоды")
        self.more_btn.clicked.connect(self._show_menu)
        focus_head.addWidget(self.more_btn)
        focus.addLayout(focus_head)
        focus.addStretch(1)
        self.open_btn = FocusTitle()
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.open_btn.setObjectName("FocusTitle")
        self.open_btn.clicked.connect(lambda: self.openDeck.emit(self.selected_id))
        focus.addWidget(self.open_btn)
        self._meta = label("", "DeckMeta", wrap=True)
        self._meta.setTextFormat(Qt.TextFormat.PlainText)
        focus.addWidget(self._meta)
        focus.addSpacing(8)
        actions = QHBoxLayout()
        self.study_btn = button("Учить колоду", "secondary", focus=True)
        self.study_btn.clicked.connect(self._study_selected)
        self.repeat_btn = button("Повторить", "text", focus=True)
        self.repeat_btn.clicked.connect(lambda: self.repeatAll.emit(self.selected_id))
        actions.addWidget(self.study_btn)
        actions.addWidget(self.repeat_btn)
        actions.addStretch()
        focus.addLayout(actions)
        self.columns.addWidget(self.hero, 3)

        self.today = QWidget()
        self._today_layout = today = QVBoxLayout(self.today)
        today.setContentsMargins(0, 8, 0, 0)
        self.today_caption = label("СЕГОДНЯ", "Caption")
        self._big = label("", "BigNumber")
        self._big_caption = label("", "BigNumberCaption", wrap=True)
        self._decks_due = label("", "DeckMeta")
        for item in (self.today_caption, self._big, self._big_caption, self._decks_due):
            today.addWidget(item)
        self._today_action_gap = QSpacerItem(0, 16)
        today.addItem(self._today_action_gap)
        self.study_all_btn = button("Начать повторение", "primary", focus=True)
        self.study_all_btn.clicked.connect(lambda: self.study.emit(None))
        self.pool_btn = button("Свободное повторение", "text", focus=True)
        self.pool_btn.clicked.connect(self.poolRequested.emit)
        today.addWidget(self.study_all_btn)
        today.addWidget(self.pool_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        today.addStretch()
        rule = QFrame()
        rule.setObjectName("TodayDivider")
        rule.setFixedHeight(1)
        today.addWidget(rule)
        selected_caption = label("В выбранной колоде", "DeckMeta")
        today.addWidget(selected_caption)
        self._selected_due = label("", "SectionTitle")
        today.addWidget(self._selected_due)
        self._scaled_text_widgets = (
            self.open_btn,
            self.today_caption, self._big, self._big_caption, self._decks_due,
            self.study_all_btn, self.pool_btn, selected_caption, self._selected_due,
        )
        self.columns.addWidget(self.today, 2)
        self._content_layout.addLayout(self.columns)

        self._strip_title = label("", "SectionTitle")
        self._content_layout.addWidget(self._strip_title)
        strip = QHBoxLayout()
        self._host = QWidget()
        self._strip = QHBoxLayout(self._host)
        self._strip.setContentsMargins(0, 0, 0, 0)
        self._strip.setSpacing(12)
        self._rail = scroll_area(self._host)
        self._rail.setFixedHeight(self._tile_height + 5)
        self._rail.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rail.viewport().installEventFilter(self)
        strip.addWidget(self._rail, 1)
        self.previous = icon_button("left", "Предыдущие колоды")
        self.next = icon_button("right", "Следующие колоды")
        strip.insertWidget(0, self.previous)
        strip.addWidget(self.next)
        self._content_layout.addLayout(strip)
        self._content_layout.addStretch()
        bar = self._rail.horizontalScrollBar()
        self._rail_scroll = QPropertyAnimation(bar, b"value", self)
        self._rail_scroll.setDuration(260)
        self._rail_scroll.setEasingCurve(QEasingCurve.Type.OutCubic)
        step = DeckRow.WIDTH + self._strip.spacing()
        self.previous.clicked.connect(lambda: self._scroll_rail(-step))
        self.next.clicked.connect(lambda: self._scroll_rail(step))
        bar.valueChanged.connect(self._update_arrows)
        bar.rangeChanged.connect(self._update_arrows)

        self._empty = QWidget()
        empty = QVBoxLayout(self._empty)
        empty.addStretch()
        for title, name in ((S.EMPTY_DECKS_TITLE, "EmptyTitle"), (S.EMPTY_DECKS_HINT, "EmptyHint")):
            line = label(title, name, wrap=True)
            line.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.addWidget(line)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.empty_create_btn = button(S.BTN_CREATE_DECK, "primary", focus=True)
        self.empty_import_btn = button(S.BTN_IMPORT_EMPTY, "secondary", focus=True)
        self.empty_create_btn.clicked.connect(self.createRequested.emit)
        self.empty_import_btn.clicked.connect(self.importRequested.emit)
        buttons.addWidget(self.empty_create_btn)
        buttons.addWidget(self.empty_import_btn)
        buttons.addStretch()
        empty.addLayout(buttons)
        empty.addStretch()

        body = QWidget()
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._content, 1)
        layout.addWidget(self._empty, 1)
        root.addWidget(scroll_area(body), 1)
        self._clock = QTimer(self)
        self._clock.setInterval(60_000)
        self._clock.timeout.connect(self.refresh)
        self.refresh()

    def _nav(self, title, signal, role):
        action = button(title, role, focus=True)
        if role == "nav":
            action.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        action.clicked.connect(signal.emit)
        self.header.addWidget(action)
        return action

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 900 or self.height() < 680
        self.brand.setVisible(self.width() >= 840)
        scale = "compact" if compact else "roomy" if self.width() >= 1160 else "normal"
        if scale != self._display_scale:
            self._display_scale = scale
            self.layout().setSpacing(16 if compact else 24)
            self._content_layout.setSpacing(12 if compact else 16)
            self.columns.setSpacing(20 if compact else 30)
            self.hero.setFixedHeight(310 if compact else 410)
            self._today_layout.setSpacing(4 if compact else -1)
            self._today_action_gap.changeSize(0, 8 if compact else 16)
            self._today_layout.invalidate()
            for item in self._scaled_text_widgets:
                set_prop(item, "displayScale", scale)
                item.updateGeometry()
        self._content_layout.setContentsMargins(0, max(0, self.height() - 780) // 3, 0, 0)

        tile_height = min(140, 100 + max(0, self.height() - 720) // 6)
        if tile_height != self._tile_height:
            self._tile_height = tile_height
            self._rail.setFixedHeight(tile_height + 5)
            for tile in self._tiles.values():
                tile.setFixedHeight(tile_height)

    def showEvent(self, event):
        super().showEvent(event)
        self._clock.start()
        self._reveal_selection()

    def hideEvent(self, event):
        self._commit_rail_click()
        self._clock.stop()
        self._rail_scroll.stop()
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel:
            pixels = event.pixelDelta()
            delta = event.angleDelta()
            step = DeckRow.WIDTH + self._strip.spacing()
            offset = pixels.x() or pixels.y() or round((delta.x() or delta.y()) * step / 120)
            if offset and self._scroll_rail(-offset, animate=pixels.isNull()):
                return True
        return super().eventFilter(watched, event)

    def _scroll_rail(self, offset, *, animate=True):
        bar = self._rail.horizontalScrollBar()
        animation = self._rail_scroll
        current = bar.value()
        target = animation.endValue() if animation.state() == QPropertyAnimation.State.Running else current
        end = max(bar.minimum(), min(bar.maximum(), target + offset))
        if end == target:
            return current != end
        animation.stop()
        if animate and motion_enabled():
            animation.setStartValue(current)
            animation.setEndValue(end)
            animation.start()
        else:
            bar.setValue(end)
        return True

    def _update_arrows(self, *_args):
        bar = self._rail.horizontalScrollBar()
        self.previous.setEnabled(bar.value() > bar.minimum())
        self.next.setEnabled(bar.value() < bar.maximum())

    def _reveal_selection(self):
        self._rail_scroll.stop()
        tile = self._tiles.get(self.selected_id)
        if tile is not None:
            self._rail.ensureWidgetVisible(tile, 0, 0)

    def _select_from_rail(self, deck_id, from_mouse):
        if not from_mouse:
            self.select(deck_id)
            self._reveal_selection()
            return
        self._commit_rail_click()
        self._pending_click = (deck_id, self.selected_id)
        self.selected_id = deck_id
        self._show_selected()
        # Keep the tile under the pointer while Qt can still deliver a double click.
        self._click_timer.start(QGuiApplication.styleHints().mouseDoubleClickInterval())

    def _commit_rail_click(self):
        if self._pending_click is not None:
            deck_id, previous_id = self._pending_click
            self._pending_click = None
            self._click_timer.stop()
            if deck_id != previous_id and deck_id in self._summaries:
                self._save_selection()

    def _open_from_rail(self, deck_id):
        if self._pending_click is not None and self._pending_click[0] == deck_id:
            _, previous_id = self._pending_click
            if previous_id in self._summaries:
                self._pending_click = None
                self._click_timer.stop()
                self.select(previous_id, save=False)
        self._commit_rail_click()
        self.openDeckFromRail.emit(deck_id)

    def select(self, deck_id, *, save=True):
        self._commit_rail_click()
        if deck_id == self.selected_id and deck_id in self._summaries:
            self._show_selected()
            return
        self.selected_id = deck_id
        if save:
            self._save_selection()
        self._show_selected()

    def _save_selection(self):
        try:
            self._library.preferences.set("focused_deck", self.selected_id or "")
        except sqlite3.Error as exc:
            self.saveFailed.emit(str(exc))

    def _study_selected(self):
        summary = self._summaries[self.selected_id]
        (self.study if summary.card_count else self.openDeck).emit(self.selected_id)

    def _show_selected(self):
        for deck_id, tile in self._tiles.items():
            tile.setChecked(deck_id == self.selected_id)
        summary = self._summaries.get(self.selected_id)
        if summary is None:
            return
        deck = summary.deck
        self.open_btn.setText(deck.name.upper())
        self.open_btn.setToolTip(f"Открыть колоду «{deck.name}»")
        self.open_btn.setAccessibleName(self.open_btn.toolTip())
        langs = " → ".join(filter(None, (deck.source_language, deck.target_language)))
        self._meta.setText(" · ".join(filter(None, (cards_count(summary.card_count), langs))))
        self.study_btn.setText("Учить колоду" if summary.card_count else "Добавить карточки")
        self.study_btn.setEnabled(not summary.card_count or summary.due_count > 0)
        self.repeat_btn.setEnabled(summary.card_count > 0)
        self._selected_due.setText(f"{summary.due_count} к повторению")

    def _show_menu(self):
        deck_id = self.selected_id
        menu = RoundedMenu(self.more_btn)
        for title, signal in (
            ("Открыть", self.openDeck), ("Переименовать", self.renameRequested),
            ("Обложка колоды", self.coverRequested), ("Экспорт", self.exportRequested),
            ("Удалить", self.deleteRequested),
        ):
            menu.addAction(title, lambda _checked=False, action=signal: action.emit(deck_id))
        menu.exec(self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()))
        menu.deleteLater()

    def refresh(self):
        now = utcnow()
        self.inbox_btn.setText(f"Входящие · {self._library.inbox.count()}")
        summaries = sorted(self._library.deck_summaries(now), key=lambda s: (s.deck.created_at, s.deck.id))
        fresh = {summary.deck.id: summary for summary in summaries}
        old_ids = list(self._summaries)
        is_new_order = list(fresh) != old_ids
        self._summaries = fresh
        self._content.setVisible(bool(fresh))
        self._empty.setVisible(not fresh)
        total, decks_due = self._library.due_totals(now)
        self._big.setText(str(total))
        self.today_caption.setText("СЕГОДНЯ")
        self._big_caption.setText(
            f'{plural(total, "карточка", "карточки", "карточек")} к повторению' if total else "Сегодня повторять нечего"
        )
        self._decks_due.setText(f'В {decks_due} {plural(decks_due, "колоде", "колодах", "колодах")}')
        self._decks_due.setVisible(total > 0)
        self.study_all_btn.setEnabled(total > 0)
        self.pool_btn.setEnabled(any(summary.card_count for summary in summaries))
        self._strip_title.setText(f"Мои колоды · {len(fresh)}")
        if is_new_order:
            clear_layout(self._strip)
            self._tiles.clear()
            for summary in summaries:
                deck_id = summary.deck.id
                tile = DeckRow(summary, self._library.deck_cover(deck_id), self._tile_height)
                tile.activated.connect(self._select_from_rail)
                tile.openRequested.connect(self._open_from_rail)
                self._strip.addWidget(tile)
                self._tiles[deck_id] = tile
            self._strip.addStretch()
        else:
            for deck_id, tile in self._tiles.items():
                tile.update_summary(fresh[deck_id])
        if self.selected_id not in fresh and fresh:
            start = old_ids.index(self.selected_id) if self.selected_id in old_ids else 0
            self.select(list(fresh)[min(start, len(fresh) - 1)], save=bool(self.selected_id))
            self._reveal_selection()
        elif not fresh and self.selected_id:
            self.select(None)
        else:
            self._show_selected()
        self._update_arrows()

    def update_cover(self, deck_id):
        tile = self._tiles.get(deck_id)
        if tile is not None:
            tile.findChild(CoverTile).configure(self._library.deck_cover(deck_id))

    @property
    def row_count(self):
        return len(self._tiles)

    def rows(self):
        return list(self._tiles.values())
