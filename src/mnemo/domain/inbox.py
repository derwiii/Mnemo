"""Unscheduled vocabulary captures, separate from learning cards."""

from dataclasses import dataclass, field
from datetime import datetime
from collections.abc import Iterable

from mnemo.domain.models import new_id, utcnow
from mnemo.domain.validation import ValidationError, clean_strings
from mnemo.settings import FRONT_MAX, TRANSLATIONS_MAX


@dataclass
class InboxEntry:
    front: str
    translations: list[str] = field(default_factory=list)
    context: str = ""
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


def clean_entry(front: str, translations: Iterable[str | None], context: str = ""):
    front, translations = front.strip(), clean_strings(translations)
    if not front:
        raise ValidationError(["Введите слово или фразу"])
    if len(front) > FRONT_MAX:
        raise ValidationError([f"Слово или фраза: не больше {FRONT_MAX} символов"])
    if len(translations) > TRANSLATIONS_MAX:
        raise ValidationError([f"Переводов не больше {TRANSLATIONS_MAX}"])
    return front, translations, context.strip()
