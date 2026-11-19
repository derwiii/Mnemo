"""Валидация и очистка данных карточек и колод (spec FR-C5, FR-C6, 3.1, 3.2)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from mnemo.domain.models import Card, Example
from mnemo.domain.markup import MarkupError, parse_markup
from mnemo.settings import (
    DECK_NAME_MAX,
    EXAMPLES_MAX,
    FRONT_MAX,
    HINTS_MAX,
    TRANSLATIONS_MAX,
)


class ValidationError(ValueError):
    """Ошибка проверки данных; `problems` содержит понятные пользователю сообщения."""

    def __init__(self, problems: list[str], fields: dict[str, str] | None = None) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems
        # Сообщения по полям формы: front, translations, examples, hints
        self.fields = fields or {}


def clean_strings(items: Iterable[str | None]) -> list[str]:
    """Обрезает пробелы и отбрасывает пустые строки (FR-C5)."""
    return [s.strip() for s in items if s is not None and s.strip()]


def clean_deck_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValidationError(["Название колоды не может быть пустым"])
    if len(name) > DECK_NAME_MAX:
        raise ValidationError([f"Название колоды длиннее {DECK_NAME_MAX} символов"])
    return name


@dataclass
class CleanCard:
    front: str
    translations: list[str]
    examples: list[Example]
    hints: list[str]
    tags: list[str]


def clean_card_fields(
    front: str,
    translations: Iterable[str | None],
    examples: Iterable[Example] = (),
    hints: Iterable[str | None] = (),
    tags: Iterable[str | None] = (),
) -> CleanCard:
    """Приводит поля карточки к допустимому виду или бросает ValidationError со всеми проблемами."""
    problems: list[str] = []
    fields: dict[str, str] = {}

    def fail(field: str, message: str) -> None:
        problems.append(message)
        fields[field] = message

    front = (front or "").strip()
    trs = clean_strings(translations)
    hs = clean_strings(hints)
    tg = clean_strings(tags)
    exs: list[Example] = []
    for ex in examples:
        text = (ex.text or "").strip()
        if text:
            tr = (ex.translation or "").strip() or None
            exs.append(Example(text, tr))

    if not front:
        fail("front", "Введите слово или фразу")
    elif len(front) > FRONT_MAX:
        fail("front", f"Слишком длинно: не больше {FRONT_MAX} символов")
    if not trs:
        fail("translations", "Добавьте хотя бы один перевод")
    elif len(trs) > TRANSLATIONS_MAX:
        fail("translations", f"Переводов не больше {TRANSLATIONS_MAX}")
    if len(exs) > EXAMPLES_MAX:
        fail("examples", f"Примеров не больше {EXAMPLES_MAX}")
    if len(hs) > HINTS_MAX:
        fail("hints", f"Подсказок не больше {HINTS_MAX}")
    for field, values, is_front in (("front", [front], True), ("translations", trs, False)):
        for value in values:
            try:
                parse_markup(value, front=is_front)
            except MarkupError as exc:
                fail(field, str(exc))
                break
    if problems:
        raise ValidationError(problems, fields)
    return CleanCard(front, trs, exs, hs, tg)


def front_key(front: str) -> str:
    """Ключ для поиска дубликатов: без учёта регистра и лишних пробелов (FR-C6)."""
    return " ".join(front.split()).casefold()


def find_duplicates(front: str, cards: Iterable[Card], exclude_id: str | None = None) -> list[Card]:
    """Карточки той же колоды с тем же `front`; `cards` должны быть из одной колоды."""
    key = front_key(front)
    return [c for c in cards if c.id != exclude_id and front_key(c.front) == key]
