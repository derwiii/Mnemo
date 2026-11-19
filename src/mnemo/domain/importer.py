"""Разбор и проверка JSON для массового импорта (docs/specs/import-export.md). Без Qt и sqlite3."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from mnemo.domain.models import Example
from mnemo.domain.validation import CleanCard, ValidationError, clean_card_fields, front_key
from mnemo.settings import IMPORT_MAX_BYTES, IMPORT_MAX_CARDS, IMPORT_SCHEMA_VERSION

KNOWN_CARD_FIELDS = {"front", "translations", "examples", "hints", "tags"}


class DuplicatePolicy(str, Enum):
    SKIP = "skip"
    ADD = "add"
    UPDATE = "update"


@dataclass
class ImportIssue:
    number: int | None  # номер записи в файле (с 1); None для проблем всего файла
    message: str

    def __str__(self) -> str:
        return f"Запись {self.number}: {self.message}" if self.number else self.message


@dataclass
class DeckInfo:
    name: str = ""
    description: str = ""
    source_language: str = ""
    target_language: str = ""


@dataclass
class ParsedCard:
    number: int
    card: CleanCard


@dataclass
class ParseResult:
    cards: list[ParsedCard] = field(default_factory=list)
    errors: list[ImportIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    deck: DeckInfo | None = None
    fatal: str | None = None
    total_records: int = 0

    @property
    def ok(self) -> bool:
        return self.fatal is None


@dataclass
class ImportPlan:
    to_add: list[CleanCard] = field(default_factory=list)
    to_update: list[tuple[str, CleanCard]] = field(default_factory=list)  # (id карточки, новые данные)
    skipped: int = 0
    duplicates: int = 0


def parse_import(
    text: str, *, max_bytes: int = IMPORT_MAX_BYTES, max_cards: int = IMPORT_MAX_CARDS
) -> ParseResult:
    """Разбирает JSON. Ошибки файла целиком попадают в `fatal`, ошибки записей в `errors`."""
    result = ParseResult()
    if len(text.encode("utf-8")) > max_bytes:
        result.fatal = f"Файл слишком большой: максимум {max_bytes // (1024 * 1024)} МБ"
        return result
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        result.fatal = f"Некорректный JSON (строка {exc.lineno}, столбец {exc.colno}): {exc.msg}"
        return result

    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        version = data.get("schema_version")
        if "schema_version" not in data:
            result.fatal = "Не указан schema_version. Ожидается schema_version: 1"
            return result
        if type(version) is not int or version != IMPORT_SCHEMA_VERSION:
            result.fatal = (
                f"Неизвестная версия формата: {version!r}. Поддерживается {IMPORT_SCHEMA_VERSION}"
            )
            return result
        records = data.get("cards")
        if not isinstance(records, list):
            result.fatal = "В файле нет списка cards"
            return result
        result.deck = _parse_deck(data.get("deck"), result)
    else:
        result.fatal = "Ожидался объект с полем cards или массив карточек"
        return result

    if len(records) > max_cards:
        result.fatal = f"Слишком много карточек: {len(records)} (максимум {max_cards})"
        return result

    result.total_records = len(records)
    unknown: set[str] = set()
    for number, raw in enumerate(records, start=1):
        try:
            clean = _parse_record(raw, unknown)
        except _RecordError as exc:
            result.errors.append(ImportIssue(number, str(exc)))
        except ValidationError as exc:
            result.errors.append(ImportIssue(number, "; ".join(exc.problems)))
        else:
            result.cards.append(ParsedCard(number, clean))
    if unknown:
        result.warnings.append("Неизвестные поля проигнорированы: " + ", ".join(sorted(unknown)))
    return result


class _RecordError(ValueError):
    pass


def _parse_deck(raw: Any, result: ParseResult) -> DeckInfo | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        result.warnings.append("Блок deck проигнорирован: ожидался объект")
        return None

    def text(key: str) -> str:
        value = raw.get(key, "")
        return value.strip() if isinstance(value, str) else ""

    return DeckInfo(text("name"), text("description"), text("source_language"), text("target_language"))


def _string_list(raw: Any, name: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if not isinstance(raw, list):
        raise _RecordError(f"поле {name} должно быть списком строк")
    for item in raw:
        if not isinstance(item, str):
            raise _RecordError(f"в поле {name} допустимы только строки")
    return list(raw)


def _parse_examples(raw: Any) -> list[Example]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise _RecordError("поле examples должно быть списком")
    examples: list[Example] = []
    for item in raw:
        if isinstance(item, str):
            examples.append(Example(item))
        elif isinstance(item, dict):
            text = item.get("text", "")
            translation = item.get("translation")
            if not isinstance(text, str) or not (translation is None or isinstance(translation, str)):
                raise _RecordError("в examples поля text и translation должны быть строками")
            examples.append(Example(text, translation))
        else:
            raise _RecordError("элемент examples должен быть объектом {text, translation}")
    return examples


def _parse_record(raw: Any, unknown: set[str]) -> CleanCard:
    if not isinstance(raw, dict):
        raise _RecordError("запись должна быть объектом")
    unknown.update(k for k in raw if k not in KNOWN_CARD_FIELDS)
    front = raw.get("front")
    if not isinstance(front, str):
        raise _RecordError("поле front обязательно и должно быть строкой")
    return clean_card_fields(
        front,
        _string_list(raw.get("translations"), "translations"),
        _parse_examples(raw.get("examples")),
        _string_list(raw.get("hints"), "hints"),
        _string_list(raw.get("tags"), "tags"),
    )


def count_duplicates(parse: ParseResult, existing: Mapping[str, str]) -> int:
    """Сколько записей совпадает с карточками колоды или с более ранними записями файла."""
    seen: set[str] = set()
    count = 0
    for item in parse.cards:
        key = front_key(item.card.front)
        if key in existing or key in seen:
            count += 1
        seen.add(key)
    return count


def plan_import(
    parse: ParseResult, existing: Mapping[str, str], policy: DuplicatePolicy
) -> ImportPlan:
    """Что записать при выбранной политике. `existing`: ключ слова -> id карточки колоды."""
    plan = ImportPlan()
    seen: set[str] = set()
    updated: set[str] = set()
    for item in parse.cards:
        key = front_key(item.card.front)
        existing_id = existing.get(key)
        if existing_id is None and key not in seen:
            plan.to_add.append(item.card)
        else:
            plan.duplicates += 1
            if policy is DuplicatePolicy.ADD:
                plan.to_add.append(item.card)
            elif policy is DuplicatePolicy.UPDATE and existing_id and key not in updated:
                plan.to_update.append((existing_id, item.card))
                updated.add(key)
            else:
                plan.skipped += 1
        seen.add(key)
    return plan
