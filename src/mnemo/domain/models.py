"""Модели предметной области (docs/specs/cards.md, разделы 1 и 2; docs/specs/product.md, раздел 3). Без Qt и sqlite3."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CardStatus(str, Enum):
    NEW = "new"
    LEARNING = "learning"
    REVIEW = "review"


class Grade(str, Enum):
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


class AnswerMode(str, Enum):
    TYPED = "typed"
    SELF = "self"


@dataclass
class Example:
    text: str
    translation: str | None = None


@dataclass
class Deck:
    name: str
    id: str = field(default_factory=new_id)
    description: str = ""
    source_language: str = ""
    target_language: str = ""
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class Card:
    deck_id: str
    front: str
    translations: list[str]
    id: str = field(default_factory=new_id)
    examples: list[Example] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class CardState:
    card_id: str
    status: CardStatus = CardStatus.NEW
    due_at: datetime = field(default_factory=utcnow)
    interval_days: float = 0.0
    ease: float = 2.5
    lapses: int = 0
    reps: int = 0


@dataclass
class ReviewLog:
    card_id: str
    grade: Grade
    answer_mode: AnswerMode
    id: str = field(default_factory=new_id)
    reviewed_at: datetime = field(default_factory=utcnow)
    hints_used: int = 0
    response_time_ms: int = 0
    typed_answer: str | None = None
    overridden: bool = False
    interval_before: float = 0.0
    interval_after: float = 0.0
