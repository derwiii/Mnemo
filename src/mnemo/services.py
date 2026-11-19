"""Прикладной слой: операции над библиотекой колод и карточек.

Объединяет репозитории и правила предметной области. Не зависит от Qt,
поэтому тестируется без интерфейса; экраны (ui) обращаются только сюда.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from mnemo.domain.exporter import export_data, to_json
from mnemo.domain.inbox import InboxEntry, clean_entry
from mnemo.storage.inbox import InboxRepository, Preferences
from mnemo.domain.importer import (
    DeckInfo,
    DuplicatePolicy,
    ParseResult,
    count_duplicates,
    plan_import,
)
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
from mnemo.domain.validation import clean_card_fields, clean_deck_name, find_duplicates
from mnemo.domain.queue import build_queue
from mnemo.domain.validation import front_key
from mnemo.domain.scheduler import Scheduler, Sm2Scheduler
from mnemo.domain.deck_covers import COVER_IDS, DEFAULT_COVER
from mnemo.settings import (
    DAILY_NEW_LIMIT,
    DAILY_REVIEW_LIMIT,
    IMPORT_MAX_BYTES,
    LEARNED_INTERVAL_DAYS,
    STATS_HARDEST_LIMIT,
    STATS_PERIOD_DAYS,
)
from mnemo.storage import (
    CardRepository,
    Database,
    DeckRepository,
    NotFoundError,
    ReviewRepository,
    StateRepository,
)


class DisplayStatus(str, Enum):
    NEW = "new"
    LEARNING = "learning"
    LEARNED = "learned"


def display_status(state: CardState | None) -> DisplayStatus:
    """«новая» / «учится» / «выучена» по CardState (docs/specs/repetition.md, раздел 5.5)."""
    if state is None or state.status is CardStatus.NEW:
        return DisplayStatus.NEW
    if state.status is CardStatus.REVIEW and state.interval_days >= LEARNED_INTERVAL_DAYS:
        return DisplayStatus.LEARNED
    return DisplayStatus.LEARNING


@dataclass
class DeckSummary:
    deck: Deck
    card_count: int
    due_count: int


@dataclass
class CardRow:
    card: Card
    status: DisplayStatus


def local_day_start(now: datetime) -> datetime:
    """Начало текущих суток по местному времени, в UTC (для дневных лимитов)."""
    local = now.astimezone()
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc)


@dataclass
class HardCard:
    card: Card
    state: CardState


@dataclass
class Statistics:
    total_cards: int
    new_cards: int
    learning_cards: int
    review_cards: int
    reviews_today: int
    reviews_period: int
    correct_percent: int | None  # за период; None, если ответов не было
    hardest: list[HardCard]
    failures_period: int = 0
    unique_cards_period: int = 0


class ImportFileError(Exception):
    """Файл импорта нельзя прочитать; текст понятен пользователю."""


def read_import_file(path: str | Path) -> str:
    """Читает файл импорта целиком (UTF-8, допускается BOM) с проверкой размера."""
    path = Path(path)
    try:
        size = path.stat().st_size
        if size > IMPORT_MAX_BYTES:
            raise ImportFileError(f"Файл больше {IMPORT_MAX_BYTES // (1024 * 1024)} МБ")
        raw = path.read_bytes()
    except OSError as exc:
        raise ImportFileError(f"Не удалось прочитать файл: {exc.strerror or exc}") from exc
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportFileError("Файл не в кодировке UTF-8") from exc


@dataclass
class ImportPreview:
    parse: ParseResult
    duplicates: int


@dataclass
class ImportReport:
    deck_id: str
    added: int
    updated: int
    skipped: int
    errors: int


class Library:
    def deck_cover(self, deck_id: str) -> str:
        row = self.db.conn.execute(
            "SELECT cover_id FROM deck_appearance WHERE deck_id = ?", (deck_id,)
        ).fetchone()
        return row["cover_id"] if row and row["cover_id"] in COVER_IDS else DEFAULT_COVER

    def set_deck_cover(self, deck_id: str, cover_id: str) -> None:
        if cover_id not in COVER_IDS:
            raise ValueError("Неизвестная обложка")
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO deck_appearance(deck_id, cover_id) VALUES (?, ?) "
                "ON CONFLICT(deck_id) DO UPDATE SET cover_id=excluded.cover_id",
                (deck_id, cover_id),
            )

    def __init__(
        self,
        db: Database,
        scheduler: Scheduler | None = None,
        *,
        new_limit: int | None = DAILY_NEW_LIMIT,
        review_limit: int | None = DAILY_REVIEW_LIMIT,
    ) -> None:
        self.db = db
        self.inbox = InboxRepository(db)
        self.preferences = Preferences(db)
        self.new_limit = new_limit
        self.review_limit = review_limit
        self.scheduler: Scheduler = scheduler or Sm2Scheduler()
        self.decks = DeckRepository(db)
        self.cards = CardRepository(db)
        self.states = StateRepository(db)
        self.reviews = ReviewRepository(db)

    def close(self) -> None:
        self.db.close()

    # ---- колоды ----

    def _limits_left(self, now: datetime) -> tuple[int | None, int | None]:
        """Сколько новых карточек и повторений ещё можно показать сегодня (None: без лимита)."""
        if self.new_limit is None and self.review_limit is None:
            return None, None
        new_done, reviews_done = self.reviews.daily_counts(local_day_start(now))
        new_left = None if self.new_limit is None else max(0, self.new_limit - new_done)
        reviews_left = None if self.review_limit is None else max(0, self.review_limit - reviews_done)
        return new_left, reviews_left

    @staticmethod
    def _available(due: int, fresh: int, new_left: int | None, reviews_left: int | None) -> int:
        return (due if reviews_left is None else min(due, reviews_left)) + (
            fresh if new_left is None else min(fresh, new_left)
        )

    def deck_summaries(self, now: datetime | None = None) -> list[DeckSummary]:
        now = now or utcnow()
        counts = self.cards.counts_by_deck()
        avail = self.states.available_counts_by_deck(now)
        new_left, reviews_left = self._limits_left(now)
        return [
            DeckSummary(
                d, counts.get(d.id, 0), self._available(*avail.get(d.id, (0, 0)), new_left, reviews_left)
            )
            for d in self.decks.list()
        ]

    def deck_summary(self, deck_id: str, now: datetime | None = None) -> DeckSummary | None:
        deck = self.decks.get(deck_id)
        if deck is None:
            return None
        now = now or utcnow()
        due, fresh = self.states.available_counts_by_deck(now).get(deck_id, (0, 0))
        new_left, reviews_left = self._limits_left(now)
        return DeckSummary(
            deck, self.cards.count_by_deck(deck_id), self._available(due, fresh, new_left, reviews_left)
        )

    def due_totals(self, now: datetime | None = None) -> tuple[int, int]:
        """(карточек к повторению сегодня по всем колодам, в скольких колодах).

        Это размер очереди «Учить всё»: повторения, срок которых наступил, и новые
        карточки в пределах дневных лимитов.
        """
        now = now or utcnow()
        avail = self.states.available_counts_by_deck(now)
        new_left, reviews_left = self._limits_left(now)
        total = self._available(
            sum(v[0] for v in avail.values()), sum(v[1] for v in avail.values()), new_left, reviews_left
        )
        decks = sum(
            1 for v in avail.values() if self._available(v[0], v[1], new_left, reviews_left) > 0
        )
        return total, decks

    def create_deck(
        self, name: str, description: str = "", source_language: str = "", target_language: str = ""
    ) -> Deck:
        deck = Deck(
            clean_deck_name(name),
            description=description.strip(),
            source_language=source_language.strip(),
            target_language=target_language.strip(),
        )
        return self.decks.add(deck)

    def update_deck(
        self,
        deck_id: str,
        name: str,
        description: str = "",
        source_language: str | None = None,
        target_language: str | None = None,
    ) -> Deck:
        deck = self.decks.get(deck_id)
        if deck is None:
            raise NotFoundError(deck_id)
        deck.name = clean_deck_name(name)
        deck.description = description.strip()
        if source_language is not None:
            deck.source_language = source_language.strip()
        if target_language is not None:
            deck.target_language = target_language.strip()
        return self.decks.update(deck)

    def delete_deck(self, deck_id: str) -> None:
        self.decks.delete(deck_id)

    # ---- карточки ----

    def list_cards(self, deck_id: str, search: str = "") -> list[CardRow]:
        cards = self.cards.list_by_deck(deck_id, search)
        states = {s.card_id: s for s in self.states.list_by_deck(deck_id)}
        return [CardRow(c, display_status(states.get(c.id))) for c in cards]

    def save_card(
        self,
        deck_id: str,
        front: str,
        translations: Iterable[str | None],
        examples: Iterable[Example] = (),
        hints: Iterable[str | None] = (),
        tags: Iterable[str | None] = (),
        card_id: str | None = None,
    ) -> Card:
        """Создаёт или правит карточку. При правке CardState и журнал не меняются (FR-C3)."""
        clean = clean_card_fields(front, translations, examples, hints, tags)
        if card_id is None:
            card = Card(deck_id, clean.front, clean.translations)
        else:
            card = self.cards.get(card_id)
            if card is None:
                raise NotFoundError(card_id)
            card.front, card.translations = clean.front, clean.translations
        card.examples, card.hints, card.tags = clean.examples, clean.hints, clean.tags
        return self.cards.add(card) if card_id is None else self.cards.update(card)

    def add_translation(self, card_id: str, translation: str) -> Card:
        """Append a user-confirmed variant without changing progress or reviews."""
        from mnemo.domain.answers import normalize
        from mnemo.domain.validation import ValidationError

        card = self.cards.get(card_id)
        if card is None:
            raise NotFoundError(card_id)
        key = normalize(translation)
        if not key:
            raise ValidationError(["Введите перевод"])
        if any(normalize(t) == key for t in card.translations):
            raise ValidationError(["Такой вариант перевода уже есть"])
        return self.save_card(
            card.deck_id, card.front, [*card.translations, translation],
            card.examples, card.hints, card.tags, card.id,
        )

    def capture_word(self, front: str, translations=(), context: str = ""):
        front, translations, context = clean_entry(front, translations, context)
        return self.inbox.capture(InboxEntry(front, translations, context))

    def save_inbox(self, entry_id: str, front: str, translations, context: str):
        from dataclasses import replace
        entry = self.inbox.get(entry_id)
        if entry is None:
            raise NotFoundError("Заготовка больше не существует")
        front, translations, context = clean_entry(front, translations, context)
        return self.inbox.update(replace(entry, front=front, translations=translations, context=context))

    def promote_inbox(self, entry_id: str, deck_id: str, front: str, translations,
                      context: str = "", *, allow_duplicate: bool = False) -> Card:
        from mnemo.domain.models import Example
        from mnemo.domain.validation import ValidationError
        with self.db.transaction():
            if self.inbox.get(entry_id) is None:
                raise NotFoundError("Заготовка уже обработана или удалена")
            if self.decks.get(deck_id) is None:
                raise ValidationError(["Выберите существующую колоду"])
            if not allow_duplicate and self.find_duplicates(deck_id, front):
                raise ValidationError(["Такое слово уже есть в колоде. Подтвердите создание дубликата."])
            card = self.save_card(deck_id, front, translations,
                                  [Example(context.strip())] if context.strip() else [])
            self.inbox.delete(entry_id)
            return card

    def delete_card(self, card_id: str) -> None:
        self.cards.delete(card_id)

    def find_duplicates(self, deck_id: str, front: str, exclude_id: str | None = None) -> list[Card]:
        found = self.cards.find_by_front(deck_id, front)
        return find_duplicates(front, found, exclude_id)

    def due_cards(self, deck_id: str | None = None, now: datetime | None = None) -> list[Card]:
        return self.cards.list_due(now or utcnow(), deck_id)

    # ---- импорт и экспорт ----

    def _existing_keys(self, deck_id: str | None) -> dict[str, str]:
        if deck_id is None:
            return {}
        result: dict[str, str] = {}
        for card in self.cards.list_by_deck(deck_id):
            result.setdefault(front_key(card.front), card.id)
        return result

    def preview_import(self, parse: ParseResult, deck_id: str | None) -> ImportPreview:
        """Предпросмотр для выбранной колоды (None — новая колода, дубликатов с базой нет)."""
        return ImportPreview(parse, count_duplicates(parse, self._existing_keys(deck_id)))

    def apply_import(
        self,
        parse: ParseResult,
        policy: DuplicatePolicy,
        *,
        deck_id: str | None = None,
        new_deck: DeckInfo | None = None,
    ) -> ImportReport:
        """Записывает валидные карточки одной транзакцией; при ошибке не меняется ничего."""
        if parse.fatal:
            raise ValueError(parse.fatal)
        with self.db.transaction():
            if deck_id is None:
                if new_deck is None:
                    raise ValueError("Не указана колода")
                deck = self.create_deck(
                    new_deck.name,
                    new_deck.description,
                    new_deck.source_language,
                    new_deck.target_language,
                )
                deck_id = deck.id
            plan = plan_import(parse, self._existing_keys(deck_id), policy)
            for clean in plan.to_add:
                self.cards.add(
                    Card(deck_id, clean.front, clean.translations, examples=clean.examples,
                         hints=clean.hints, tags=clean.tags)
                )
            for card_id, clean in plan.to_update:
                card = self.cards.get(card_id)
                if card is None:
                    continue
                card.translations, card.examples = clean.translations, clean.examples
                card.hints, card.tags = clean.hints, clean.tags
                self.cards.update(card)
        return ImportReport(deck_id, len(plan.to_add), len(plan.to_update), plan.skipped, len(parse.errors))

    def export_deck(self, deck_id: str) -> str:
        deck = self.decks.get(deck_id)
        if deck is None:
            raise NotFoundError(deck_id)
        return to_json(export_data(deck, self.cards.list_by_deck(deck_id)))

    # ---- очередь сессии ----

    def session_queue(
        self,
        deck_id: str | None = None,
        now: datetime | None = None,
        rng: random.Random | None = None,
    ) -> list[Card]:
        """Очередь на сейчас: просроченные и трудные впереди, новые вперемешку, с дневными лимитами."""
        now = now or utcnow()
        deck_ids = [deck_id] if deck_id else [d.id for d in self.decks.list()]
        entries = []
        for did in deck_ids:
            states = {s.card_id: s for s in self.states.list_by_deck(did)}
            for card in self.cards.list_by_deck(did):
                state = states.get(card.id)
                if state is not None:
                    entries.append((card, state))
        new_done, reviews_done = (0, 0)
        if self.new_limit is not None or self.review_limit is not None:
            new_done, reviews_done = self.reviews.daily_counts(local_day_start(now))
        return build_queue(
            entries,
            now,
            rng,
            new_limit=self.new_limit,
            review_limit=self.review_limit,
            new_done_today=new_done,
            reviews_done_today=reviews_done,
        )

    # ---- запись ответа ----

    def free_session_queue(
        self, deck_id: str | None = None, rng: random.Random | None = None,
        *, count: int | None = None,
    ) -> list[Card]:
        """Свободная выборка без повторов, равновероятно среди карточек."""
        ids = [deck_id] if deck_id is not None else [d.id for d in self.decks.list()]
        cards = [c for did in ids for c in self.cards.list_by_deck(did)]
        if count is not None and (isinstance(count, bool) or not isinstance(count, int)
                                  or not 1 <= count <= len(cards)):
            raise ValueError(f"Количество карточек должно быть от 1 до {len(cards)}")
        return (rng or random.Random()).sample(cards, len(cards) if count is None else count)

    def record_review(
        self,
        card_id: str,
        grade: Grade,
        answer_mode: AnswerMode,
        *,
        typed_answer: str | None = None,
        overridden: bool = False,
        hints_used: int = 0,
        response_time_ms: int = 0,
        now: datetime | None = None,
    ) -> ReviewLog:
        """Планировщик обновляет CardState, а ответ дописывается в журнал: одной транзакцией (FR-S5).

        В журнал пишется исходная оценка пользователя, а не сниженная из-за подсказок.
        """
        now = now or utcnow()
        with self.db.transaction():
            state = self.states.get(card_id)
            card = self.cards.get(card_id)
            if state is None or card is None:
                raise NotFoundError(card_id)
            outcome = self.scheduler.review(state, grade, now, hints_used, len(card.hints))
            self.states.save(outcome.state)
            log = ReviewLog(
                card_id=card_id,
                grade=grade,
                answer_mode=answer_mode,
                reviewed_at=now,
                hints_used=hints_used,
                response_time_ms=response_time_ms,
                typed_answer=typed_answer if answer_mode is AnswerMode.TYPED else None,
                overridden=overridden and answer_mode is AnswerMode.TYPED,
                interval_before=outcome.interval_before,
                interval_after=outcome.interval_after,
            )
            return self.reviews.add(log)

    # ---- статистика ----

    def statistics(self, now: datetime | None = None) -> Statistics:
        """Считается заново из журнала и состояний при каждом вызове (FR-T3)."""
        now = now or utcnow()
        counts = self.states.status_counts()
        new_c = counts.get(CardStatus.NEW.value, 0)
        learning_c = counts.get(CardStatus.LEARNING.value, 0)
        review_c = counts.get(CardStatus.REVIEW.value, 0)
        today, _ = self.reviews.count_since(local_day_start(now))
        period, correct = self.reviews.count_since(now - timedelta(days=STATS_PERIOD_DAYS))
        hardest = []
        for state in self.states.hardest(STATS_HARDEST_LIMIT):
            card = self.cards.get(state.card_id)
            if card is not None:
                hardest.append(HardCard(card, state))
        return Statistics(
            total_cards=new_c + learning_c + review_c,
            new_cards=new_c,
            learning_cards=learning_c,
            review_cards=review_c,
            reviews_today=today,
            reviews_period=period,
            correct_percent=round(100 * correct / period) if period else None,
            hardest=hardest,
            failures_period=period - correct,
            unique_cards_period=self.reviews.unique_cards_since(
                now - timedelta(days=STATS_PERIOD_DAYS)
            ),
        )
