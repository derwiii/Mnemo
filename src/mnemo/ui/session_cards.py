"""Переход от карточек из хранилища к карточкам экрана сессии.

Идентификатор карточки нужен, чтобы каждая оценка записывалась в журнал и состояние.
"""

from __future__ import annotations

from mnemo.domain.models import Card
from mnemo.ui.demo_data import DemoCard


def to_session_card(card: Card) -> DemoCard:
    return DemoCard(
        front=card.front,
        translations=list(card.translations),
        examples=[(e.text, e.translation or "") for e in card.examples],
        hints=list(card.hints),
        card_id=card.id,
    )
