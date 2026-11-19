"""Встроенные кнопки окна и зоны изменения размера."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QPushButton, QWidget

from mnemo.ui import strings as S
from mnemo.ui.widgets import icon_button
from mnemo.ui.windows_frame import enable_system_frame

BAR_HEIGHT = 38
DRAG_HEIGHT = 24
EDGE = 6
CORNER = 12


class DragStrip(QWidget):
    def __init__(self, window: QMainWindow):
        super().__init__(window)
        self._window = window
        self._press_position = None
        self._dragging = False
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_position = event.globalPosition().toPoint()
            self._window_position = self._window.pos()
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_position is None or not event.buttons() & Qt.MouseButton.LeftButton:
            super().mouseMoveEvent(event)
            return
        event.accept()
        delta = event.globalPosition().toPoint() - self._press_position
        if not self._dragging:
            if delta.manhattanLength() < QApplication.startDragDistance():
                return
            if self._window.isMaximized():
                anchor = self._press_position - self._window.mapToGlobal(QPoint())
                fraction = anchor.x() / self._window.width()
                restore_width = self._window.normalGeometry().width()
                self._window.showNormal()
                self._window_position = self._press_position - QPoint(
                    round((restore_width if restore_width > 0 else self._window.width()) * fraction),
                    anchor.y(),
                )
            self._dragging = True
        self._window.move(self._window_position + delta)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._press_position is not None:
            self._press_position = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_position = None
            if self._window.isMaximized():
                self._window.showNormal()
            else:
                self._window.showMaximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class WindowBar(QWidget):
    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self._window = window
        self.setObjectName("WindowBar")
        self.setFixedSize(124, BAR_HEIGHT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.minimize_btn = self._make("minimize", S.WINDOW_MINIMIZE, window.showMinimized)
        self.maximize_btn = self._make("maximize", S.WINDOW_MAXIMIZE, self.toggle_maximized)
        self.close_btn = self._make("close", S.WINDOW_CLOSE, window.close)
        self.close_btn.setProperty("kind", "close")
        for btn in (self.minimize_btn, self.maximize_btn, self.close_btn):
            lay.addWidget(btn)

    def _make(self, glyph: str, tip: str, slot) -> QPushButton:  # noqa: ANN001
        btn = icon_button(glyph, tip)
        btn.setProperty("role", "winctl")
        btn.setToolTip(tip)
        btn.setAccessibleName(tip)
        btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        btn.setCursor(Qt.CursorShape.ArrowCursor)
        btn.setFixedSize(36, 36)
        btn.clicked.connect(lambda _checked=False: slot())
        return btn

    def toggle_maximized(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

class ResizeEdge(QWidget):
    """Невидимая зона у края окна: меняет курсор и запускает изменение размера."""

    def __init__(self, window: QMainWindow, edges: Qt.Edge, cursor: Qt.CursorShape) -> None:
        super().__init__(window)
        self._window = window
        self._edges = edges
        self.setCursor(cursor)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemResize(self._edges)
                event.accept()
                return
        super().mousePressEvent(event)


class WindowChrome:
    """Встраивает управление в шапку текущего экрана."""

    def __init__(self, window: QMainWindow, content: QWidget) -> None:
        self._window = window
        self._content = content
        native_windows = QApplication.platformName() == "windows"
        window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        if not native_windows:
            window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.bar = WindowBar(window)
        self.drag_strip = DragStrip(window)
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        h, v = Qt.CursorShape.SizeHorCursor, Qt.CursorShape.SizeVerCursor
        fd, bd = Qt.CursorShape.SizeFDiagCursor, Qt.CursorShape.SizeBDiagCursor
        self.edges = {
            "left": ResizeEdge(window, L, h),
            "right": ResizeEdge(window, R, h),
            "bottom": ResizeEdge(window, B, v),
            "top_left": ResizeEdge(window, T | L, fd),
            "top_right": ResizeEdge(window, T | R, bd),
            "bottom_left": ResizeEdge(window, B | L, bd),
            "bottom_right": ResizeEdge(window, B | R, fd),
        }
        self.attach()
        self.relayout()
        if native_windows:
            enable_system_frame(int(window.winId()))

    def attach(self):
        page = self._content.currentWidget()
        if page is not None and page.header.indexOf(self.bar) < 0:
            header = page.header
            header.setSpacing(12)
            for index in range(header.count()):
                widget = header.itemAt(index).widget()
                if widget is not None:
                    header.setAlignment(widget, Qt.AlignmentFlag.AlignVCenter)
                    if widget.property("role") == "back":
                        header.setContentsMargins(0, 4, 0, 0)
            header.addWidget(self.bar, alignment=Qt.AlignmentFlag.AlignVCenter)
            self.bar.show()
        self.relayout()

    def relayout(self) -> None:
        w, h = self._window.width(), self._window.height()
        self.drag_strip.setGeometry(CORNER, 0, w - 2 * CORNER, DRAG_HEIGHT)
        self.drag_strip.raise_()
        g = {
            "left": (0, CORNER, EDGE, h - 2 * CORNER),
            "right": (w - EDGE, CORNER, EDGE, h - 2 * CORNER),
            "bottom": (CORNER, h - EDGE, w - 2 * CORNER, EDGE),
            "top_left": (0, 0, CORNER, CORNER),
            "top_right": (w - CORNER, 0, CORNER, CORNER),
            "bottom_left": (0, h - CORNER, CORNER, CORNER),
            "bottom_right": (w - CORNER, h - CORNER, CORNER, CORNER),
        }
        expanded = self._window.isMaximized() or self._window.isFullScreen()
        for name, edge in self.edges.items():
            edge.setGeometry(*g[name])
            edge.setVisible(not expanded)
            if not expanded:
                edge.raise_()
        if self._content.property("expanded") != expanded:
            self.sync_maximize_glyph(expanded)

    def sync_maximize_glyph(self, expanded: bool) -> None:
        icon = icon_button("restore" if expanded else "maximize", "")
        self.bar.maximize_btn.setIcon(icon.icon())
        icon.deleteLater()
        self.bar.maximize_btn.setToolTip("Восстановить" if expanded else S.WINDOW_MAXIMIZE)
        self.bar.maximize_btn.setAccessibleName(self.bar.maximize_btn.toolTip())
        content = self._content
        content.setProperty("expanded", expanded)
        content.style().unpolish(content)
        content.style().polish(content)
        content.update()
