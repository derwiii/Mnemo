"""Построение очереди сессии (spec FR-S2, FR-A3, FR-A4). Без Qt и sqlite3."""

from __future__ import annotations

import random
from collections.abc import Iterable
from datetime import datetime

from mnemo import settings as cfg
from mnemo.domain.models import Card, CardState, CardStatus
from mnemo.domain.scheduler import difficulty


def _priority(state: CardState, now: datetime) -> float:
    """Чем больше, тем раньше карточка: трудные и просроченные впереди."""
    overdue_days = max(0.0, (now - state.due_at).total_seconds() / 86400)
    overdue_days = min(overdue_days, cfg.QUEUE_OVERDUE_CAP_DAYS)
    return difficulty(state) * cfg.QUEUE_DIFFICULTY_WEIGHT + overdue_days


def build_queue(
    entries: Iterable[tuple[Card, CardState]],
    now: datetime,
    rng: random.Random | None = None,
    *,
    new_limit: int | None = cfg.DAILY_NEW_LIMIT,
    review_limit: int | None = cfg.DAILY_REVIEW_LIMIT,
    new_done_today: int = 0,
    reviews_done_today: int = 0,
) -> list[Card]:
    """Очередь: повторения по приоритету, новые карточки вперемешку с ними.

    Лимиты `new_limit` и `review_limit` необязательны (None: без ограничений);
    `new_done_today` и `reviews_done_today` уменьшают их. С одинаковым
    `rng` (seed) результат одинаков (FR-A5).
    """
    rng = rng or random.Random()
    reviews: list[tuple[Card, CardState]] = []
    fresh: list[tuple[Card, CardState]] = []
    for card, state in entries:
        if state.status is CardStatus.NEW:
            fresh.append((card, state))
        elif state.due_at <= now:
            reviews.append((card, state))

    reviews.sort(key=lambda cs: (-_priority(cs[1], now), cs[1].due_at, cs[0].id))
    if review_limit is not None:
        reviews = reviews[: max(0, review_limit - reviews_done_today)]

    fresh.sort(key=lambda cs: (cs[0].created_at, cs[0].id))
    if new_limit is not None:
        fresh = fresh[: max(0, new_limit - new_done_today)]

    queue = [card for card, _ in reviews]
    for card, _ in fresh:
        queue.insert(rng.randint(0, len(queue)), card)
    return queue
