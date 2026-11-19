import random
from datetime import datetime, timedelta, timezone

import pytest

from mnemo import settings as cfg
from mnemo.domain.models import Card, CardState, CardStatus, Grade
from mnemo.domain.queue import build_queue
from mnemo.domain.scheduler import Sm2Scheduler, difficulty, effective_grade

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
S = Sm2Scheduler()


def fresh():
    return CardState("c")


def run(grades, state=None, hints=(0, 0)):
    state = state or fresh()
    now = NOW
    for g in grades:
        out = S.review(state, g, now, *hints)
        state = out.state
        now = max(now, state.due_at)
    return state


def test_new_good_graduates_to_one_day():
    out = S.review(fresh(), Grade.GOOD, NOW)
    assert out.state.status is CardStatus.REVIEW
    assert out.state.interval_days == 1.0 and out.state.due_at == NOW + timedelta(days=1)
    assert out.state.reps == 1 and out.interval_before == 0 and out.interval_after == 1.0


def test_new_again_stays_learning_short_delay():
    out = S.review(fresh(), Grade.AGAIN, NOW)
    assert out.state.status is CardStatus.LEARNING and out.state.lapses == 0
    assert out.state.due_at == NOW + timedelta(minutes=cfg.AGAIN_DELAY_MINUTES)


def test_new_easy_longer_and_higher_ease():
    out = S.review(fresh(), Grade.EASY, NOW)
    assert out.state.interval_days == cfg.FIRST_EASY_DAYS
    assert out.state.ease == pytest.approx(2.65)


def test_good_growth_multiplies_by_ease():
    s = run([Grade.GOOD] * 4)
    assert s.interval_days > 10
    assert s.ease == 2.5


def test_three_again_worse_than_three_good():
    again = run([Grade.GOOD, Grade.AGAIN, Grade.AGAIN, Grade.AGAIN])
    good = run([Grade.GOOD, Grade.GOOD, Grade.GOOD, Grade.GOOD])
    assert again.interval_days < good.interval_days
    assert again.ease < good.ease
    assert again.lapses >= 1


def test_ease_clamped():
    s = run([Grade.GOOD] * 2 + [Grade.AGAIN] * 20)
    assert s.ease == cfg.EASE_MIN
    s = run([Grade.EASY] * 30)
    assert s.ease == cfg.EASE_MAX
    assert s.interval_days <= cfg.MAX_INTERVAL_DAYS


def test_lapse_reduces_interval_and_counts():
    review = CardState("c", CardStatus.REVIEW, NOW, interval_days=20, ease=2.5, reps=5)
    out = S.review(review, Grade.AGAIN, NOW)
    assert out.state.lapses == 1 and out.state.status is CardStatus.LEARNING
    assert out.state.interval_days == 10 and out.state.ease == pytest.approx(2.3)
    # возвращение после провала не обнуляет накопленный интервал
    back = S.review(out.state, Grade.GOOD, NOW + timedelta(minutes=10))
    assert back.state.status is CardStatus.REVIEW and back.state.interval_days == 10


def test_hard_grows_slowly():
    review = CardState("c", CardStatus.REVIEW, NOW, interval_days=10, ease=2.5)
    out = S.review(review, Grade.HARD, NOW)
    assert out.state.interval_days == pytest.approx(12)
    assert out.state.ease == pytest.approx(2.35)


@pytest.mark.parametrize("grade, expected", [
    (Grade.AGAIN, Grade.AGAIN), (Grade.HARD, Grade.HARD),
    (Grade.GOOD, Grade.HARD), (Grade.EASY, Grade.GOOD),
])
@pytest.mark.parametrize("used,total", [(0, 0), (0, 5), (1, 1), (1, 5), (5, 5)])
def test_hints_lower_effective_grade(grade, expected, used, total):
    assert effective_grade(grade, used, total) is (expected if used else grade)


def test_easy_with_hint_processed_as_good():
    a = S.review(fresh(), Grade.EASY, NOW, hints_used=1, hints_total=2)
    b = S.review(fresh(), Grade.GOOD, NOW)
    assert a.effective_grade is Grade.GOOD
    assert a.state == b.state


def test_deterministic():
    assert S.review(fresh(), Grade.GOOD, NOW).state == S.review(fresh(), Grade.GOOD, NOW).state


# ---------------- очередь ----------------


def entry(i, status=CardStatus.REVIEW, lapses=0, ease=2.5, due_days=-1.0):
    card = Card("d", f"w{i}", ["t"], id=f"c{i:03d}", created_at=NOW + timedelta(seconds=i))
    state = CardState(card.id, status, NOW + timedelta(days=due_days), 5.0, ease, lapses, 3)
    return card, state


def test_only_due_cards_and_new_in_queue():
    entries = [entry(1), entry(2, due_days=2), entry(3, status=CardStatus.NEW, due_days=0)]
    q = build_queue(entries, NOW, random.Random(1))
    assert sorted(c.id for c in q) == ["c001", "c003"]


def test_limits_respected():
    entries = [entry(i) for i in range(30)] + [entry(100 + i, CardStatus.NEW) for i in range(30)]
    q = build_queue(entries, NOW, random.Random(1), new_limit=5, review_limit=10)
    assert len(q) == 15
    assert sum(1 for c in q if int(c.id[1:]) >= 100) == 5
    q = build_queue(entries, NOW, random.Random(1), new_limit=5, review_limit=10,
                    new_done_today=3, reviews_done_today=8)
    assert len(q) == 4
    q = build_queue(entries, NOW, random.Random(1), new_limit=20, review_limit=200,
                    new_done_today=99, reviews_done_today=999)
    assert q == []
    # без лимитов показываются все
    assert len(build_queue(entries, NOW, random.Random(1), new_limit=None, review_limit=None)) == 60


def test_new_cards_are_mixed_not_blocked():
    entries = [entry(i) for i in range(40)] + [entry(100 + i, CardStatus.NEW) for i in range(10)]
    q = build_queue(entries, NOW, random.Random(7))
    positions = [i for i, c in enumerate(q) if int(c.id[1:]) >= 100]
    assert max(positions) > 20 and min(positions) < 40  # разбросаны по очереди


def test_hard_cards_come_first():
    entries = [entry(i) for i in range(20)] + [entry(50, lapses=5, ease=1.5), entry(51, lapses=3, ease=1.8)]
    q = build_queue(entries, NOW, random.Random(1))
    assert [c.id for c in q[:2]] == ["c050", "c051"]
    assert difficulty(entries[-2][1]) > difficulty(entries[0][1])


def test_queue_deterministic_with_seed():
    entries = [entry(i) for i in range(10)] + [entry(100 + i, CardStatus.NEW) for i in range(5)]
    a = [c.id for c in build_queue(entries, NOW, random.Random(42))]
    b = [c.id for c in build_queue(entries, NOW, random.Random(42))]
    assert a == b


def test_simulation_hard_cards_reviewed_more_often():
    """60 дней, 5 трудных карточек (p=0.45) и 15 лёгких (p=0.95)."""
    rng = random.Random(2026)
    cards, states, p = {}, {}, {}
    for i in range(20):
        card = Card("d", f"w{i}", ["t"], id=f"c{i:03d}", created_at=NOW + timedelta(seconds=i))
        cards[card.id] = card
        states[card.id] = CardState(card.id, due_at=NOW)
        p[card.id] = 0.45 if i < 5 else 0.95
    counts = {cid: 0 for cid in cards}
    hard_pos, easy_pos = [], []
    for day in range(60):
        now = NOW + timedelta(days=day)
        queue = build_queue([(cards[c], states[c]) for c in cards], now, rng,
                            new_limit=100, review_limit=200)
        if day >= 10 and len(queue) > 1:
            for pos, card in enumerate(queue):
                (hard_pos if int(card.id[1:]) < 5 else easy_pos).append(pos / (len(queue) - 1))
        for card in queue:
            grade = Grade.GOOD if rng.random() < p[card.id] else Grade.AGAIN
            states[card.id] = S.review(states[card.id], grade, now).state
            counts[card.id] += 1
    hard_avg = sum(counts[f"c{i:03d}"] for i in range(5)) / 5
    easy_avg = sum(counts[f"c{i:03d}"] for i in range(5, 20)) / 15
    assert hard_avg > easy_avg * 1.5
    # когда в очереди есть и трудные, и лёгкие, трудные стоят ближе к началу
    assert sum(hard_pos) / len(hard_pos) < sum(easy_pos) / len(easy_pos)
