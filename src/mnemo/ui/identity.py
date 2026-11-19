"""Native, resolution-independent Mnemo identity and short decorative motion."""
from __future__ import annotations

import os
from functools import lru_cache
from PyQt6.QtCore import QByteArray, QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QWidget

from mnemo.paths import resource_path
from mnemo.ui.theme import active_palette

COVER_NAMES = {
    "cards": "Карточки", "dialogue": "Диалог", "route": "Маршрут",
    "book": "Книга", "spark": "Искра", "links": "Связи",
}


def motion_enabled() -> bool:
    return os.environ.get("MNEMO_REDUCED_MOTION", "0") != "1"


class StackArt(QWidget):
    """Card fan that can quietly gather into a completed stack."""
    def __init__(self, parent=None, *, logo=False):
        super().__init__(parent)
        self.logo = logo
        self.amount = 1.0
        self.complete = False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAccessibleName("Знак Mnemo" if logo else "Стопка карточек")
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(420)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._update_amount)
        if logo:
            self.setFixedSize(32, 32)

    def _update_amount(self, value):
        self.amount = float(value)
        self.update()

    def gather(self):
        self.complete = True
        self.anim.stop()
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        if motion_enabled() and self.isVisible():
            self.anim.start()
        else:
            self._update_amount(0.0)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.logo:
            p.setPen(QPen(QColor(active_palette()["accent"]), 1.7))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(2, 9, 19, 21), 5, 5)
            p.drawRoundedRect(QRectF(11, 2, 19, 21), 5, 5)
            # The overlapping strokes suggest the two stems of M.
            p.drawLine(QPointF(11, 9), QPointF(16, 16))
            p.drawLine(QPointF(16, 16), QPointF(21, 9))
            return
        p.translate(self.width() / 2, self.height() / 2)
        scale = min(self.width() / 280, self.height() / 190)
        p.scale(scale, scale)
        for i, angle in enumerate((-19, -5, 13)):
            p.save()
            p.translate((i - 1) * (28 * self.amount + 4), (2 - i) * 5)
            p.rotate(angle * self.amount)
            p.setBrush(QColor(active_palette()["surface"]).lighter(100 + i * 8))
            p.setPen(QPen(QColor(active_palette()["accent"]), 1.2))
            p.drawRoundedRect(QRectF(-61, -69, 122, 148), 15, 15)
            p.restore()
        if self.complete:
            p.setPen(QPen(QColor(active_palette()["accent"]), 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(-15, 0), QPointF(-3, 12))
            p.drawLine(QPointF(-3, 12), QPointF(22, -14))


@lru_cache(maxsize=24)
def _cover_renderer(cover_id, text, accent, bottom):
    svg = resource_path("covers", f"{cover_id}.svg").read_text(encoding="utf-8")
    svg = svg.replace("@text@", text).replace("@accent@", accent).replace("@art_bottom@", bottom)
    return QSvgRenderer(QByteArray(svg.encode("utf-8")))


def paint_cover(painter, rect, cover_id, *, focus=False):
    colors = active_palette()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    radius = 17 if focus else 8
    clip.addRoundedRect(rect, radius, radius)
    painter.setClipPath(clip)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0, QColor(colors["art_start"]))
    gradient.setColorAt(.55, QColor(colors["art_end"]))
    gradient.setColorAt(1, QColor(colors["art_bottom"]))
    painter.fillRect(rect, gradient)
    if focus:
        width = min(rect.width(), rect.height() * 1.08)
        art = QRectF(rect.right() - width - 8, rect.top() + 10, width, width * .75)
    else:
        art = rect.adjusted(3, 3, -3, -3)
    _cover_renderer(cover_id, colors["text"], colors["accent"], colors["art_bottom"]).render(painter, art)
    shade = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    bottom = QColor(colors["art_bottom"])
    clear = QColor(bottom)
    clear.setAlpha(0)
    halfway = QColor(bottom)
    halfway.setAlphaF(.64)
    shade.setColorAt(.29, clear)
    shade.setColorAt(.56, halfway)
    shade.setColorAt(.88, bottom)
    painter.fillRect(rect, shade)


class CoverTile(QWidget):
    def __init__(self, cover_id="cards", parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.configure(cover_id)

    def configure(self, cover_id):
        self.cover_id = cover_id
        self.setAccessibleName("Обложка: " + COVER_NAMES[cover_id])
        self.update()

    def paintEvent(self, event):
        paint_cover(QPainter(self), QRectF(self.rect()), self.cover_id)


class FocusCover(QWidget):
    def paintEvent(self, event):
        paint_cover(QPainter(self), QRectF(self.rect()), "cards", focus=True)


class SessionEntrance(QWidget):
    """A decorative card moves forward and flips away to reveal the live session.

    Never delays state changes, steals focus, or intercepts keyboard/mouse input.
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.progress = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(380)
        self.anim.setStartValue(0.0); self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.anim.valueChanged.connect(self._step)
        self.anim.finished.connect(self.hide)
        self.hide()

    def start(self):
        if not motion_enabled():
            return
        self.setGeometry(self.parentWidget().rect())
        self.progress = 0.0
        self.show(); self.raise_(); self.anim.start()

    def _step(self, value):
        self.progress = float(value); self.update()

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.progress
        p.setOpacity(1 - t)
        p.translate(self.width() * (.68 - .18 * t), self.height() * (.38 + .07 * t))
        p.rotate(12 * (1 - t))
        p.scale(max(.02, abs(1 - 2 * t)), 1 + .45 * t)
        p.setBrush(QColor(active_palette()["surface"])); p.setPen(QPen(QColor(active_palette()["accent"]), 1))
        p.drawRoundedRect(QRectF(-110, -130, 220, 260), 22, 22)
