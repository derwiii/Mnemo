"""Flat card notation shared by validation, display and answer matching."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from mnemo.settings import MARKUP_MAX_COMBINATIONS


class MarkupError(ValueError):
    pass


@dataclass(frozen=True)
class Text:
    value: str
    target: bool = False


@dataclass(frozen=True)
class Alternatives:
    values: tuple[str, ...]


def parse_markup(text: str, *, front: bool = False) -> tuple[Text | Alternatives, ...]:
    """Parse reserved [[target]] and {a|b}; single square brackets stay literal."""
    parts: list[Text | Alternatives] = []
    cursor = start = targets = groups = 0
    combinations = 1
    while cursor < len(text):
        marker = next((m for m in ("[[", "]]", "{", "}") if text.startswith(m, cursor)), None)
        if marker is None:
            cursor += 1
            continue
        if start < cursor:
            parts.append(Text(text[start:cursor]))
        if marker == "[[":
            if not front:
                raise MarkupError("Выделение [[…]] допустимо только в исходнике")
            end = text.find("]]", cursor + 2)
            if end < 0:
                raise MarkupError("Не закрыто выделение [[…]]")
            value = text[cursor + 2:end]
            if not value.strip() or any(m in value for m in ("[[", "{", "}")):
                raise MarkupError("Цель [[…]] должна быть непустой, без вложенной разметки")
            targets += 1
            if targets > 1:
                raise MarkupError("В исходнике допустима только одна цель [[…]]")
            parts.append(Text(value, target=True))
            cursor = end + 2
        elif marker == "{":
            end = text.find("}", cursor + 1)
            if end < 0:
                raise MarkupError("Не закрыта группа вариантов {…|…}")
            value = text[cursor + 1:end]
            if any(m in value for m in ("{", "[[", "]]")):
                raise MarkupError("Вложенная разметка в вариантах недопустима")
            values = tuple(value.split("|"))
            if len(values) < 2 or any(not v.strip() for v in values):
                raise MarkupError("Нужны хотя бы два непустых варианта {…|…}")
            combinations *= len(values)
            if combinations > MARKUP_MAX_COMBINATIONS:
                raise MarkupError(f"Не больше {MARKUP_MAX_COMBINATIONS} сочетаний вариантов в одной строке")
            groups += 1
            parts.append(Alternatives(values))
            cursor = end + 1
        else:
            raise MarkupError(f"Лишняя закрывающая скобка {marker}")
        start = cursor
    if start < len(text):
        parts.append(Text(text[start:]))
    if front and groups and not targets:
        raise MarkupError("Контексты {…|…} требуют выделенной цели [[…]]")
    return tuple(parts)


def expand_answers(text: str) -> tuple[str, ...]:
    """Expand independent answer groups, bounded by the parser's combination limit."""
    parts = parse_markup(text)
    choices = [part.values if isinstance(part, Alternatives) else (part.value,) for part in parts]
    return tuple("".join(values) for values in product(*choices))


def display_text(text: str, *, front: bool = False) -> str:
    """Context groups keep bounds; answer groups show only slash-separated parts."""
    try:
        parts = parse_markup(text, front=front)
    except MarkupError:
        return text
    chunks = []
    for part in parts:
        if isinstance(part, Alternatives):
            variants = " / ".join(v.strip() for v in part.values)
            chunks.append(f"[{variants}]" if front else variants)
        else:
            chunks.append(part.value)
    return "".join(chunks)


def translation_text(translations) -> str:
    return " · ".join(display_text(t) for t in translations)


def target_text(front: str) -> str | None:
    try:
        return next((p.value for p in parse_markup(front, front=True)
                     if isinstance(p, Text) and p.target), None)
    except MarkupError:
        return None
