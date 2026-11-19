import random
from datetime import timedelta

import pytest

from mnemo.domain.models import AnswerMode, Grade, utcnow
from mnemo.services import Library
from mnemo.storage import Database


def test_free_selection_ignores_dates_and_limits_and_samples_unique_cards():
    lib = Library(Database(":memory:"), new_limit=0, review_limit=0)
    try:
        decks = [lib.create_deck(name) for name in ("A", "B")]
        cards = [lib.save_card(d.id, str(i), ["т"]) for d in decks for i in range(5)]
        for c in cards:
            lib.record_review(c.id, Grade.GOOD, AnswerMode.SELF)
        assert lib.session_queue() == []
        assert {c.id for c in lib.free_session_queue(decks[0].id)} == {c.id for c in cards[:5]}
        selected = lib.free_session_queue(rng=random.Random(42), count=7)
        assert len({c.id for c in selected}) == 7
        assert selected == lib.free_session_queue(rng=random.Random(42), count=7)
        assert len(lib.free_session_queue()) == 10
        for count in (0, -1, 11, True, 1.5):
            with pytest.raises(ValueError):
                lib.free_session_queue(count=count)
    finally:
        lib.close()


def test_failure_success_hints_and_override_are_separate_attempts():
    lib = Library(Database(":memory:"))
    try:
        d = lib.create_deck("A")
        c = lib.save_card(d.id, "w", ["т"], hints=["h"])
        now = utcnow()
        lib.record_review(c.id, Grade.AGAIN, AnswerMode.SELF, now=now)
        lib.record_review(c.id, Grade.EASY, AnswerMode.SELF, hints_used=1, now=now)
        lib.record_review(c.id, Grade.HARD, AnswerMode.TYPED, typed_answer="синоним",
                          overridden=True, now=now)
        stats = lib.statistics(now)
        assert (stats.reviews_period, stats.failures_period, stats.unique_cards_period) == (3, 1, 1)
        assert stats.correct_percent == 67
        assert lib.states.get(c.id).due_at > now
        assert lib.statistics(now + timedelta(days=31)).unique_cards_period == 0
    finally:
        lib.close()
