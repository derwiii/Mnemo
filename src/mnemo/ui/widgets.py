"""Общие элементы интерфейса: кнопки, поля, прокрутка, диалоги."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, QSize, QByteArray, QRectF, QObject, QEvent
from PyQt6.QtGui import QPainter, QPixmap, QIcon, QPainterPath, QRegion
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QDialog,
    QMenu,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QStyle, QStyleOptionButton, QSizePolicy,
)

from mnemo.ui import strings as S


class RoundedMenu(QMenu):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 10, 10)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))


class TooltipCorners(QObject):
    def eventFilter(self, obj, event):
        if isinstance(obj, QWidget) and obj.windowType() == Qt.WindowType.ToolTip and event.type() in (QEvent.Type.Show, QEvent.Type.Resize):
            path = QPainterPath()
            path.addRoundedRect(QRectF(obj.rect()), 6, 6)
            obj.setMask(QRegion(path.toFillPolygon().toPolygon()))
        return False


def icon_button(kind: str, title: str) -> QPushButton:
    """Vector icons remain legible without depending on installed symbol fonts."""
    paths = {
        "left": '<path d="m15 5-7 7 7 7"/>',
        "right": '<path d="m9 5 7 7-7 7"/>',
        "minimize": '<path d="M5 12h14"/>',
        "maximize": '<rect x="5" y="5" width="14" height="14" rx="1"/>',
        "restore": '<path d="M8 5V3h13v13h-2"/><rect x="3" y="8" width="13" height="13" rx="1"/>',
        "close": '<path d="m6 6 12 12 M18 6 6 18"/>',
        "edit": '<path d="m4 16 11-11 4 4-11 11-5 1z M13 7l4 4"/>',
        "delete": '<path d="M4 6h16 M9 6V3h6v3 M6 6l1 15h10l1-15 M10 10v7 M14 10v7"/>',
        "more": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
        "settings": '<path d="m9 3 1-2h4l1 2 2 1 2 0 2 3-1 2v2l1 2-2 3-2 0-2 1-1 2h-4l-1-2-2-1-2 0-2-3 1-2V9L3 7l2-3h2z" transform="translate(0 2)"/><circle cx="12" cy="12" r="3"/>',
    }
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><g fill="none" stroke="#D4D9D3" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{paths[kind]}</g></svg>'
    pix = QPixmap(48, 48)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pix.setDevicePixelRatio(2)
    btn = button("", "icon", focus=True)
    btn.setIcon(QIcon(pix))
    btn.setIconSize(QSize(20, 20))
    btn.setFixedSize(36, 36)
    btn.setToolTip(title)
    btn.setAccessibleName(title)
    btn.setProperty("kind", kind)
    return btn


class ElidedButton(QPushButton):
    """Keep full accessible text, elide only its painting on narrow rows."""
    def minimumSizeHint(self):
        return QSize(60, super().minimumSizeHint().height())

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width())
        painter = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self)


def repolish(widget: QWidget) -> None:
    """Заставляет Qt заново применить QSS после смены динамического свойства."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_prop(widget: QWidget, name: str, value: str) -> None:
    widget.setProperty(name, value)
    repolish(widget)


def button(text: str, role: str, *, size: str | None = None, focus: bool = False) -> QPushButton:
    btn = ElidedButton(text) if role == "rowtitle" else QPushButton(text)
    if role == "rowtitle":
        btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        btn.setToolTip(text)
    btn.setProperty("role", role)
    if size:
        btn.setProperty("size", size)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if not focus:
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return btn


def label(text: str = "", name: str | None = None, *, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def field(placeholder: str = "", size: str | None = None, name: str | None = None) -> QLineEdit:
    """Подчёркнутое поле ввода (docs/specs/design.md, раздел 6.2)."""
    edit = QLineEdit()
    edit.setProperty("role", "field")
    if size:
        edit.setProperty("size", size)
    if name:
        edit.setObjectName(name)
    edit.setPlaceholderText(placeholder)
    return edit


def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            continue
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        child = item.layout()
        if child is not None:
            clear_layout(child)


def scroll_area(content: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(content)
    area.viewport().setAutoFillBackground(False)
    content.setAutoFillBackground(False)
    return area


class Dialog(QDialog):
    """Диалог в стиле макета: панель по центру, остальное окно затемняется (docs/specs/design.md, раздел 6.6)."""

    def __init__(self, parent: QWidget | None, title: str, width: int = 460) -> None:
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.panel = QFrame()
        self.panel.setObjectName("DialogPanel")
        self.panel.setFixedWidth(width)
        outer.addWidget(self.panel)
        self.body = QVBoxLayout(self.panel)
        self.body.setContentsMargins(28, 26, 28, 22)
        self.body.setSpacing(14)
        self.body.addWidget(label(title, "DialogTitle"))
        self.primary: QPushButton | None = None

    def add_buttons(
        self,
        primary_text: str,
        cancel_text: str = S.BTN_CANCEL,
        role: str = "primary",
        show_cancel: bool = True,
    ) -> QPushButton:
        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 0)
        row.setSpacing(14)
        row.addStretch(1)
        cancel = button(cancel_text, "text")
        cancel.clicked.connect(self.reject)
        self.primary = button(primary_text, role, focus=True)
        self.primary.setDefault(True)
        self.primary.clicked.connect(self._on_primary)
        if show_cancel:
            row.addWidget(cancel)
        else:
            cancel.deleteLater()
        row.addWidget(self.primary)
        self.body.addLayout(row)
        return self.primary

    def _on_primary(self) -> None:
        self.accept()


class ConfirmDialog(Dialog):
    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        text: str,
        confirm_text: str,
        *,
        danger: bool = False,
        cancel_text: str = S.BTN_CANCEL,
        show_cancel: bool = True,
    ) -> None:
        super().__init__(parent, title)
        self.body.addWidget(label(text, "DialogText", wrap=True))
        self.add_buttons(confirm_text, cancel_text, "danger" if danger else "primary", show_cancel)


def run_dialog(window: QWidget, dialog: QDialog) -> bool:
    """Показывает диалог по центру окна поверх затемнения. True, если нажато главное действие."""
    overlay = QWidget(window)
    overlay.setObjectName("Dim")
    overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    overlay.setGeometry(window.rect())
    overlay.show()
    overlay.raise_()
    dialog.adjustSize()
    center = window.mapToGlobal(window.rect().center())
    dialog.move(center - QPoint(dialog.width() // 2, dialog.height() // 2))
    try:
        result = dialog.exec()
    finally:
        overlay.hide()
        overlay.deleteLater()
    return result == QDialog.DialogCode.Accepted


def confirm(
    window: QWidget,
    title: str,
    text: str,
    confirm_text: str,
    *,
    danger: bool = False,
    cancel_text: str = S.BTN_CANCEL,
) -> bool:
    dialog = ConfirmDialog(window, title, text, confirm_text, danger=danger, cancel_text=cancel_text)
    return run_dialog(window, dialog)


def info(window: QWidget, title: str, text: str) -> None:
    """Сообщение с одной кнопкой «Понятно»."""
    dialog = ConfirmDialog(window, title, text, S.BTN_OK, show_cancel=False)
    run_dialog(window, dialog)
