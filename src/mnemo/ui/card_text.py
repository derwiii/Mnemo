"""Qt rendering of the domain notation; card content is always escaped."""

from html import escape

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from mnemo.domain.markup import Alternatives, Text, display_text, parse_markup, target_text


def set_front_text(label: QLabel, front: str) -> None:
    plain = display_text(front, front=True)
    label.setAccessibleName(plain)
    label.setToolTip(plain)
    if target_text(front) is None:
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setText(plain)
        return
    chunks = []
    for part in parse_markup(front, front=True):
        if isinstance(part, Alternatives):
            chunks.append(escape("[" + " / ".join(v.strip() for v in part.values) + "]"))
        elif isinstance(part, Text):
            text = escape(part.value).replace("\n", "<br>")
            chunks.append(f'<span style="font-weight:700">{text}</span>' if part.target else text)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setText('<span style="font-weight:400">' + "".join(chunks) + '</span>')
