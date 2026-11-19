"""Планировщик повторений: интерфейс и упрощённый SM-2 (docs/specs/repetition.md, раздел 3). Без Qt и sqlite3."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol

from mnemo.domain.models import CardState, CardStatus, Grade
from mnemo import settings as cfg


@dataclass
class ReviewOutcome:
    state: CardState  # новое состояние карточки
    effective_grade: Grade  # оценка после учёта подсказок
    interval_before: float
    interval_after: float


class Scheduler(Protocol):
    def review(
        self,
        state: CardState,
        grade: Grade,
        now: datetime,
        hints_used: int = 0,
        hints_total: int = 0,
    ) -> ReviewOutcome: ...


def effective_grade(grade: Grade, hints_used: int, hints_total: int) -> Grade:
    """Любая подсказка понижает успешную оценку на одну ступень (FR-A2).

    hints_total сохранён для совместимости интерфейса; количество не влияет.
    """
    if hints_used > 0:
        return {Grade.EASY: Grade.GOOD, Grade.GOOD: Grade.HARD}.get(grade, grade)
    return grade


def difficulty(state: CardState) -> float:
    """Мера трудности карточки: чем больше провалов и ниже ease, тем выше (FR-A3)."""
    return (
        state.lapses * cfg.DIFFICULTY_LAPSE_WEIGHT
        + max(0.0, cfg.EASE_START - state.ease) * cfg.DIFFICULTY_EASE_WEIGHT
    )


def _clamp_ease(value: float) -> float:
    return max(cfg.EASE_MIN, min(cfg.EASE_MAX, value))


class Sm2Scheduler:
    """Упрощённая модификация SM-2: интервал растёт умножением на ease."""

    def review(
        self,
        state: CardState,
        grade: Grade,
        now: datetime,
        hints_used: int = 0,
        hints_total: int = 0,
    ) -> ReviewOutcome:
        grade = effective_grade(grade, hints_used, hints_total)
        before = state.interval_days
        new = replace(state, reps=state.reps + 1)

        if state.status is CardStatus.REVIEW:
            self._review_card(new, state, grade, now)
        else:
            self._learning_card(new, state, grade, now)

        new.interval_days = min(new.interval_days, cfg.MAX_INTERVAL_DAYS)
        return ReviewOutcome(new, grade, before, new.interval_days)

    # --- новая или учимая карточка ---

    @staticmethod
    def _learning_card(new: CardState, old: CardState, grade: Grade, now: datetime) -> None:
        if grade is Grade.AGAIN:
            new.status = CardStatus.LEARNING
            new.ease = _clamp_ease(old.ease + cfg.EASE_AGAIN_DELTA)
            new.due_at = now + timedelta(minutes=cfg.AGAIN_DELAY_MINUTES)
        elif grade is Grade.HARD:
            new.status = CardStatus.LEARNING
            new.interval_days = max(old.interval_days, cfg.FIRST_HARD_DAYS)
            new.due_at = now + timedelta(days=cfg.FIRST_HARD_DAYS)
        else:
            # Окончание обучения. Если карточка уже была выучена и забыта, интервал сохраняется.
            base = cfg.FIRST_EASY_DAYS if grade is Grade.EASY else cfg.FIRST_GOOD_DAYS
            new.status = CardStatus.REVIEW
            new.interval_days = max(old.interval_days, base)
            if grade is Grade.EASY:
                new.ease = _clamp_ease(old.ease + cfg.EASE_EASY_DELTA)
            new.due_at = now + timedelta(days=new.interval_days)

    # --- выученная карточка ---

    @staticmethod
    def _review_card(new: CardState, old: CardState, grade: Grade, now: datetime) -> None:
        interval = max(old.interval_days, cfg.MIN_REVIEW_INTERVAL_DAYS)
        if grade is Grade.AGAIN:
            new.status = CardStatus.LEARNING
            new.lapses = old.lapses + 1
            new.ease = _clamp_ease(old.ease + cfg.EASE_AGAIN_DELTA)
            new.interval_days = max(cfg.MIN_REVIEW_INTERVAL_DAYS, interval * cfg.LAPSE_INTERVAL_FACTOR)
            new.due_at = now + timedelta(minutes=cfg.AGAIN_DELAY_MINUTES)
            return
        if grade is Grade.HARD:
            new.ease = _clamp_ease(old.ease + cfg.EASE_HARD_DELTA)
            new.interval_days = max(cfg.MIN_REVIEW_INTERVAL_DAYS, interval * cfg.HARD_INTERVAL_FACTOR)
        elif grade is Grade.GOOD:
            new.interval_days = max(interval + 1, interval * old.ease)
        else:
            new.ease = _clamp_ease(old.ease + cfg.EASE_EASY_DELTA)
            new.interval_days = max(interval + 1, interval * new.ease * cfg.EASY_INTERVAL_BONUS)
        new.status = CardStatus.REVIEW
        new.due_at = now + timedelta(days=min(new.interval_days, cfg.MAX_INTERVAL_DAYS))
