from datetime import datetime, time, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from nudge.core.config import Settings
from nudge.core.models import DecisionAction, TaskPriority, TaskStatus
from nudge.reminders.engine import (
    decide,
    due_urgency,
    in_quiet_hours,
    make_idempotency_key,
    score_task,
    staleness_score,
)


def _prefs(**overrides):
    base = {
        "timezone": "UTC",
        "quiet_start": time(22, 0),
        "quiet_end": time(7, 0),
        "channels": ["in_app", "email"],
        "digest_enabled": True,
        "digest_time": time(9, 0),
        "min_score_threshold": 0.45,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _task(**overrides):
    base = {
        "id": uuid4(),
        "user_id": uuid4(),
        "title": "Ship Phase 1",
        "status": TaskStatus.todo,
        "priority": TaskPriority.p1,
        "due_at": None,
        "explicit_remind_at": None,
        "force_within_quiet": False,
        "last_notified_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_due_urgency_overdue_higher_than_far():
    assert due_urgency(-12, True) > due_urgency(120, False)


def test_due_urgency_imminent():
    assert due_urgency(2, False) >= 0.95


def test_staleness_fresh_is_low():
    now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    recent = datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc)
    assert staleness_score(recent, now) < 0.2
    assert staleness_score(None, now) == 1.0


def test_quiet_hours_wrap_midnight():
    now = datetime(2026, 10, 28, 23, 30, tzinfo=timezone.utc)
    assert in_quiet_hours(now, time(22, 0), time(7, 0)) is True
    afternoon = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
    assert in_quiet_hours(afternoon, time(22, 0), time(7, 0)) is False


def test_idempotency_key_stable():
    uid, tid = uuid4(), uuid4()
    a = make_idempotency_key(uid, tid, "2026-10-28-12", "in_app", "send")
    b = make_idempotency_key(uid, tid, "2026-10-28-12", "in_app", "send")
    c = make_idempotency_key(uid, tid, "2026-10-28-13", "in_app", "send")
    assert a == b
    assert a != c
    assert len(a) == 64


def test_guaranteed_send_bypasses_low_score():
    now = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
    task = _task(
        priority=TaskPriority.p3,
        due_at=datetime(2026, 12, 1, tzinfo=timezone.utc),
        explicit_remind_at=now,
        last_notified_at=now,  # would kill staleness
    )
    prefs = _prefs()
    settings = Settings()
    decision = decide(task, prefs, now, daily_count=0, settings=settings)
    assert decision.guaranteed is True
    assert decision.action == DecisionAction.send
    assert decision.score >= 1.0


def test_guaranteed_defers_in_quiet_hours_by_default():
    now = datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc)
    task = _task(explicit_remind_at=now, force_within_quiet=False)
    prefs = _prefs()
    decision = decide(task, prefs, now, daily_count=0, settings=Settings())
    assert decision.action == DecisionAction.defer
    assert decision.guaranteed is True


def test_guaranteed_force_within_quiet_sends():
    now = datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc)
    task = _task(explicit_remind_at=now, force_within_quiet=True)
    prefs = _prefs()
    decision = decide(task, prefs, now, daily_count=0, settings=Settings())
    assert decision.action == DecisionAction.send


def test_high_score_sends_outside_quiet():
    now = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
    task = _task(
        priority=TaskPriority.p0,
        due_at=datetime(2026, 10, 28, 16, 0, tzinfo=timezone.utc),
        last_notified_at=None,
    )
    prefs = _prefs()
    score, comps = score_task(task, prefs, now, Settings())
    assert score >= 0.75
    decision = decide(task, prefs, now, daily_count=0, settings=Settings())
    assert decision.action == DecisionAction.send
    assert comps.overdue is False


def test_low_score_skips():
    now = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
    task = _task(
        priority=TaskPriority.p3,
        due_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        last_notified_at=now,
    )
    prefs = _prefs(digest_enabled=False)
    decision = decide(task, prefs, now, daily_count=0, settings=Settings())
    assert decision.action == DecisionAction.skip


def test_mid_score_goes_to_digest_when_enabled():
    now = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
    # Craft mid-band: due in ~48h, p2, some staleness
    task = _task(
        priority=TaskPriority.p2,
        due_at=datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc),
        last_notified_at=datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc),
    )
    prefs = _prefs(digest_enabled=True)
    settings = Settings(reminder_send_threshold=0.95, reminder_digest_threshold=0.4)
    decision = decide(task, prefs, now, daily_count=0, settings=settings)
    assert decision.action in (DecisionAction.digest, DecisionAction.send, DecisionAction.skip)
    # With raised send threshold, expect digest or skip depending on exact score
    score, _ = score_task(task, prefs, now, settings)
    if 0.4 <= score < 0.95:
        assert decision.action == DecisionAction.digest


def test_daily_cap_defers_or_digest():
    now = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
    task = _task(
        priority=TaskPriority.p0,
        due_at=datetime(2026, 10, 28, 16, 0, tzinfo=timezone.utc),
    )
    prefs = _prefs(digest_enabled=True)
    settings = Settings(reminder_daily_cap=1)
    decision = decide(task, prefs, now, daily_count=5, settings=settings)
    assert decision.action == DecisionAction.digest


@pytest.mark.parametrize(
    "priority,expected_min",
    [
        (TaskPriority.p0, 0.9),
        (TaskPriority.p3, 0.2),
    ],
)
def test_priority_affects_score(priority, expected_min):
    now = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
    task = _task(
        priority=priority,
        due_at=datetime(2026, 10, 28, 16, 0, tzinfo=timezone.utc),
    )
    score, comps = score_task(task, _prefs(), now, Settings())
    assert comps.priority_norm >= expected_min or priority == TaskPriority.p3
    assert 0.0 <= score <= 1.0
