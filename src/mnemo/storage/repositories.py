"""Репозитории: колоды, карточки, состояния планировщика, журнал ответов.

Репозитории не знают о Qt. Каждая операция идёт в транзакции; при вложенном вызове
(например, импорт пачкой) фиксирует только внешняя транзакция.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime, timezone

from mnemo.domain.models import (
    AnswerMode,
    Card,
    CardState,
    CardStatus,
    Deck,
    Example,
    Grade,
    ReviewLog,
    utcnow,
)
from mnemo.domain.validation import front_key
from mnemo.storage.db import Database, DuplicateDeckNameError, NotFoundError


def _dt(value: datetime) -> str:
    """Единый формат (UTC, микросекунды): строки сравниваются так же, как моменты времени."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="microseconds")


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _name_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class DeckRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, deck: Deck) -> Deck:
        try:
            with self.db.transaction() as c:
                c.execute(
                    "INSERT INTO decks VALUES (?,?,?,?,?,?,?,?)",
                    (
                        deck.id,
                        deck.name,
                        _name_key(deck.name),
                        deck.description,
                        deck.source_language,
                        deck.target_language,
                        _dt(deck.created_at),
                        _dt(deck.updated_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateDeckNameError(deck.name) from exc
        return deck

    def update(self, deck: Deck) -> Deck:
        deck = replace(deck, updated_at=utcnow())
        try:
            with self.db.transaction() as c:
                cur = c.execute(
                    "UPDATE decks SET name=?, name_key=?, description=?, source_language=?,"
                    " target_language=?, updated_at=? WHERE id=?",
                    (
                        deck.name,
                        _name_key(deck.name),
                        deck.description,
                        deck.source_language,
                        deck.target_language,
                        _dt(deck.updated_at),
                        deck.id,
                    ),
                )
                if cur.rowcount == 0:
                    raise NotFoundError(deck.id)
        except sqlite3.IntegrityError as exc:
            raise DuplicateDeckNameError(deck.name) from exc
        return deck

    def delete(self, deck_id: str) -> None:
        """Удаляет колоду; карточки, состояния и журнал уходят каскадом."""
        with self.db.transaction() as c:
            c.execute("DELETE FROM decks WHERE id=?", (deck_id,))

    def get(self, deck_id: str) -> Deck | None:
        row = self.db.conn.execute("SELECT * FROM decks WHERE id=?", (deck_id,)).fetchone()
        return self._row(row) if row else None

    def get_by_name(self, name: str) -> Deck | None:
        row = self.db.conn.execute(
            "SELECT * FROM decks WHERE name_key=?", (_name_key(name),)
        ).fetchone()
        return self._row(row) if row else None

    def list(self) -> list[Deck]:
        rows = self.db.conn.execute("SELECT * FROM decks ORDER BY name_key").fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> Deck:
        return Deck(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            source_language=row["source_language"],
            target_language=row["target_language"],
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
        )


class CardRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _search_text(card: Card) -> str:
        return "\n".join([card.front, *card.translations]).casefold().replace("ё", "е")

    def add(self, card: Card) -> Card:
        """Добавляет карточку и её CardState со статусом `new`."""
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    card.id,
                    card.deck_id,
                    card.front,
                    front_key(card.front),
                    self._search_text(card),
                    json.dumps(card.translations, ensure_ascii=False),
                    json.dumps(
                        [{"text": e.text, "translation": e.translation} for e in card.examples],
                        ensure_ascii=False,
                    ),
                    json.dumps(card.hints, ensure_ascii=False),
                    json.dumps(card.tags, ensure_ascii=False),
                    _dt(card.created_at),
                    _dt(card.updated_at),
                ),
            )
            state = CardState(card_id=card.id)
            c.execute(
                "INSERT INTO card_states VALUES (?,?,?,?,?,?,?)",
                (
                    state.card_id,
                    state.status.value,
                    _dt(state.due_at),
                    state.interval_days,
                    state.ease,
                    state.lapses,
                    state.reps,
                ),
            )
        return card

    def add_many(self, cards: Iterable[Card]) -> int:
        """Пачка в одной транзакции: при ошибке откатывается всё (импорт)."""
        count = 0
        with self.db.transaction():
            for card in cards:
                self.add(card)
                count += 1
        return count

    def update(self, card: Card) -> Card:
        """Меняет содержимое карточки. CardState и журнал не затрагиваются."""
        card = replace(card, updated_at=utcnow())
        with self.db.transaction() as c:
            cur = c.execute(
                "UPDATE cards SET deck_id=?, front=?, front_key=?, search_text=?, translations=?,"
                " examples=?, hints=?, tags=?, updated_at=? WHERE id=?",
                (
                    card.deck_id,
                    card.front,
                    front_key(card.front),
                    self._search_text(card),
                    json.dumps(card.translations, ensure_ascii=False),
                    json.dumps(
                        [{"text": e.text, "translation": e.translation} for e in card.examples],
                        ensure_ascii=False,
                    ),
                    json.dumps(card.hints, ensure_ascii=False),
                    json.dumps(card.tags, ensure_ascii=False),
                    _dt(card.updated_at),
                    card.id,
                ),
            )
            if cur.rowcount == 0:
                raise NotFoundError(card.id)
        return card

    def delete(self, card_id: str) -> None:
        with self.db.transaction() as c:
            c.execute("DELETE FROM cards WHERE id=?", (card_id,))

    def get(self, card_id: str) -> Card | None:
        row = self.db.conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        return self._row(row) if row else None

    def list_by_deck(self, deck_id: str, search: str = "") -> list[Card]:
        """Карточки колоды; `search` — подстрока в слове или переводах (без учёта регистра, ё=е)."""
        sql = "SELECT * FROM cards WHERE deck_id=?"
        params: list[object] = [deck_id]
        needle = search.strip().casefold().replace("ё", "е")
        if needle:
            sql += " AND search_text LIKE ? ESCAPE '\\'"
            params.append(f"%{_like_escape(needle)}%")
        sql += " ORDER BY created_at, rowid"
        return [self._row(r) for r in self.db.conn.execute(sql, params).fetchall()]

    def find_by_front(self, deck_id: str, front: str) -> list[Card]:
        rows = self.db.conn.execute(
            "SELECT * FROM cards WHERE deck_id=? AND front_key=?", (deck_id, front_key(front))
        ).fetchall()
        return [self._row(r) for r in rows]

    def counts_by_deck(self) -> dict[str, int]:
        rows = self.db.conn.execute("SELECT deck_id, COUNT(*) AS n FROM cards GROUP BY deck_id").fetchall()
        return {r["deck_id"]: int(r["n"]) for r in rows}

    def list_due(self, now: datetime, deck_id: str | None = None) -> list[Card]:
        """Карточки, срок которых наступил (по всем колодам или по одной)."""
        sql = (
            "SELECT c.* FROM cards c JOIN card_states s ON s.card_id = c.id WHERE s.due_at <= ?"
        )
        params: list[object] = [_dt(now)]
        if deck_id is not None:
            sql += " AND c.deck_id = ?"
            params.append(deck_id)
        sql += " ORDER BY s.due_at, c.rowid"
        return [self._row(r) for r in self.db.conn.execute(sql, params).fetchall()]

    def count_by_deck(self, deck_id: str) -> int:
        return int(
            self.db.conn.execute("SELECT COUNT(*) FROM cards WHERE deck_id=?", (deck_id,)).fetchone()[0]
        )

    @staticmethod
    def _row(row: sqlite3.Row) -> Card:
        return Card(
            id=row["id"],
            deck_id=row["deck_id"],
            front=row["front"],
            translations=json.loads(row["translations"]),
            examples=[Example(e["text"], e["translation"]) for e in json.loads(row["examples"])],
            hints=json.loads(row["hints"]),
            tags=json.loads(row["tags"]),
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
        )


class StateRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, card_id: str) -> CardState | None:
        row = self.db.conn.execute("SELECT * FROM card_states WHERE card_id=?", (card_id,)).fetchone()
        return self._row(row) if row else None

    def save(self, state: CardState) -> None:
        with self.db.transaction() as c:
            cur = c.execute(
                "UPDATE card_states SET status=?, due_at=?, interval_days=?, ease=?, lapses=?, reps=?"
                " WHERE card_id=?",
                (
                    state.status.value,
                    _dt(state.due_at),
                    state.interval_days,
                    state.ease,
                    state.lapses,
                    state.reps,
                    state.card_id,
                ),
            )
            if cur.rowcount == 0:
                raise NotFoundError(state.card_id)

    def status_counts(self) -> dict[str, int]:
        rows = self.db.conn.execute(
            "SELECT status, COUNT(*) AS n FROM card_states GROUP BY status"
        ).fetchall()
        return {r["status"]: int(r["n"]) for r in rows}

    def hardest(self, limit: int) -> list[CardState]:
        """Самые трудные: по провалам и низкому ease (spec FR-T2). Показываются только изучавшиеся карточки."""
        from mnemo import settings as cfg

        score = f"(lapses * {cfg.DIFFICULTY_LAPSE_WEIGHT} + MAX(0, {cfg.EASE_START} - ease) * {cfg.DIFFICULTY_EASE_WEIGHT})"
        rows = self.db.conn.execute(
            f"SELECT * FROM card_states WHERE reps > 0 AND {score} > 0"
            f" ORDER BY {score} DESC, lapses DESC, card_id LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row(r) for r in rows]

    def due_counts_by_deck(self, now: datetime) -> dict[str, int]:
        rows = self.db.conn.execute(
            "SELECT c.deck_id AS deck_id, COUNT(*) AS n FROM card_states s"
            " JOIN cards c ON c.id = s.card_id WHERE s.due_at <= ? GROUP BY c.deck_id",
            (_dt(now),),
        ).fetchall()
        return {r["deck_id"]: int(r["n"]) for r in rows}

    def available_counts_by_deck(self, now: datetime) -> dict[str, tuple[int, int]]:
        """По колодам: (повторений, срок которых наступил; новых карточек)."""
        rows = self.db.conn.execute(
            "SELECT c.deck_id AS deck_id,"
            " SUM(CASE WHEN s.status != 'new' AND s.due_at <= ? THEN 1 ELSE 0 END) AS due,"
            " SUM(CASE WHEN s.status = 'new' THEN 1 ELSE 0 END) AS fresh"
            " FROM card_states s JOIN cards c ON c.id = s.card_id GROUP BY c.deck_id",
            (_dt(now),),
        ).fetchall()
        return {r["deck_id"]: (int(r["due"] or 0), int(r["fresh"] or 0)) for r in rows}

    def list_by_deck(self, deck_id: str) -> list[CardState]:
        rows = self.db.conn.execute(
            "SELECT s.* FROM card_states s JOIN cards c ON c.id = s.card_id WHERE c.deck_id=?",
            (deck_id,),
        ).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> CardState:
        return CardState(
            card_id=row["card_id"],
            status=CardStatus(row["status"]),
            due_at=_parse_dt(row["due_at"]),
            interval_days=row["interval_days"],
            ease=row["ease"],
            lapses=row["lapses"],
            reps=row["reps"],
        )


class ReviewRepository:
    """Журнал ответов: только добавление и чтение."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, log: ReviewLog) -> ReviewLog:
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO review_logs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    log.id,
                    log.card_id,
                    _dt(log.reviewed_at),
                    log.grade.value,
                    log.hints_used,
                    log.response_time_ms,
                    log.answer_mode.value,
                    log.typed_answer,
                    int(log.overridden),
                    log.interval_before,
                    log.interval_after,
                ),
            )
        return log

    def list_by_card(self, card_id: str) -> list[ReviewLog]:
        rows = self.db.conn.execute(
            "SELECT * FROM review_logs WHERE card_id=? ORDER BY reviewed_at, rowid", (card_id,)
        ).fetchall()
        return [self._row(r) for r in rows]

    def count(self) -> int:
        return int(self.db.conn.execute("SELECT COUNT(*) FROM review_logs").fetchone()[0])

    def count_since(self, start: datetime) -> tuple[int, int]:
        """(всего попыток, успешных: hard, good, easy) с момента `start`."""
        row = self.db.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(CASE WHEN grade IN ('hard', 'good', 'easy') THEN 1 ELSE 0 END), 0)"
            " FROM review_logs WHERE reviewed_at >= ?",
            (_dt(start),),
        ).fetchone()
        return int(row[0]), int(row[1])

    def unique_cards_since(self, start: datetime) -> int:
        row = self.db.conn.execute(
            "SELECT COUNT(DISTINCT card_id) FROM review_logs WHERE reviewed_at >= ?",
            (_dt(start),),
        ).fetchone()
        return int(row[0])

    def daily_counts(self, day_start: datetime) -> tuple[int, int]:
        """(новых карточек, начатых сегодня; повторений ранее виденных карточек сегодня)."""
        start = _dt(day_start)
        new_cards = self.db.conn.execute(
            "SELECT COUNT(*) FROM (SELECT card_id FROM review_logs GROUP BY card_id"
            " HAVING MIN(reviewed_at) >= ?)",
            (start,),
        ).fetchone()[0]
        reviews = self.db.conn.execute(
            "SELECT COUNT(*) FROM review_logs l WHERE l.reviewed_at >= ? AND EXISTS ("
            " SELECT 1 FROM review_logs p WHERE p.card_id = l.card_id AND p.reviewed_at < ?)",
            (start, start),
        ).fetchone()[0]
        return int(new_cards), int(reviews)

    @staticmethod
    def _row(row: sqlite3.Row) -> ReviewLog:
        return ReviewLog(
            id=row["id"],
            card_id=row["card_id"],
            reviewed_at=_parse_dt(row["reviewed_at"]),
            grade=Grade(row["grade"]),
            hints_used=row["hints_used"],
            response_time_ms=row["response_time_ms"],
            answer_mode=AnswerMode(row["answer_mode"]),
            typed_answer=row["typed_answer"],
            overridden=bool(row["overridden"]),
            interval_before=row["interval_before"],
            interval_after=row["interval_after"],
        )
