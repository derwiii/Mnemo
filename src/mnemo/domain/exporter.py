"""Экспорт колоды в формат JSON (docs/specs/import-export.md, раздел 3). Прогресс изучения не экспортируется."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from mnemo.domain.models import Card, Deck
from mnemo.settings import IMPORT_SCHEMA_VERSION


def export_data(deck: Deck, cards: Iterable[Card]) -> dict[str, Any]:
    out_cards = []
    for card in cards:
        examples = []
        for ex in card.examples:
            item: dict[str, str] = {"text": ex.text}
            if ex.translation:
                item["translation"] = ex.translation
            examples.append(item)
        out_cards.append(
            {
                "front": card.front,
                "translations": list(card.translations),
                "examples": examples,
                "hints": list(card.hints),
                "tags": list(card.tags),
            }
        )
    return {
        "schema_version": IMPORT_SCHEMA_VERSION,
        "deck": {
            "name": deck.name,
            "description": deck.description,
            "source_language": deck.source_language,
            "target_language": deck.target_language,
        },
        "cards": out_cards,
    }


def to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
