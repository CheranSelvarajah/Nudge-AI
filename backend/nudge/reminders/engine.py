from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from nudge.core.config import Settings, get_settings
from nudge.core.models import (
    DailyNotifyCount,
    DecisionAction,
    NotificationChannel,
    ReminderDecision,
    ReminderPreferences,
    Task,
    TaskPriority,
    TaskStatus,
    User,
)
from nudge.notifications.provider import NotificationPayload, record_and_send

PRIORITY_NORM: dict[TaskPriority, float] = {
    TaskPriority.p0: 1.0,
    TaskPriority.p1: 0.75,
    TaskPriority.p2: 0.5,
    TaskPriority.p3: 0.25,
}


@dataclass
class ScoreComponents:
    due_urgency: float
    priority_norm: float
    staleness: float
    user_boost: float
    schedule_fit: float
    hours_to_due: float | None
    overdue: bool
    guaranteed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "due_urgency": round(self.due_urgency, 4),
            "priority_norm": round(self.priority_norm, 4),
            "staleness": round(self.staleness, 4),
            "user_boost": round(self.user_boost, 4),
            "schedule_fit": round(self.schedule_fit, 4),
            "hours_to_due": self.hours_to_due,
            "overdue": self.overdue,
            "guaranteed": self.guaranteed,
        }


@dataclass
class EngineDecision:
    action: DecisionAction
    score: float
    components: ScoreComponents
    reason_text: str
    guaranteed: bool
    idempotency_key: str
    channel: NotificationChannel | None = None


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def due_urgency(hours_to_due: float | None, overdue: bool) -> float:
    if hours_to_due is None:
        return 0.15
    if overdue:
        # Rises with overdue age, capped
        return _clamp(0.85 + min(abs(hours_to_due), 72) / 240.0)
    if hours_to_due <= 0:
        return 1.0
    if hours_to_due <= 4:
        return 0.95
    if hours_to_due <= 24:
        return 0.75
    if hours_to_due <= 72:
        return 0.45
    return _clamp(0.25 * (72 / hours_to_due))


def staleness_score(last_notified_at: datetime | None, now: datetime) -> float:
    if last_notified_at is None:
        return 1.0
    hours = (now - last_notified_at).total_seconds() / 3600.0
    if hours < 6:
        return 0.05
    if hours < 24:
        return 0.35
    if hours < 72:
        return 0.7
    return 1.0


def in_quiet_hours(local_now: datetime, quiet_start: time, quiet_end: time) -> bool:
    t = local_now.time()
    if quiet_start == quiet_end:
        return False
    if quiet_start < quiet_end:
        return quiet_start <= t < quiet_end
    # wraps midnight
    return t >= quiet_start or t < quiet_end


def window_bucket(now: datetime, action: DecisionAction) -> str:
    if action == DecisionAction.digest:
        return now.strftime("%Y-%m-%d-digest")
    return now.strftime("%Y-%m-%d-%H")


def make_idempotency_key(
    user_id: UUID,
    task_id: UUID,
    bucket: str,
    channel: str,
    action: str,
) -> str:
    raw = f"{user_id}:{task_id}:{bucket}:{channel}:{action}"
    return hashlib.sha256(raw.encode()).hexdigest()


def score_task(
    task: Task,
    prefs: ReminderPreferences,
    now: datetime,
    settings: Settings | None = None,
) -> tuple[float, ScoreComponents]:
    settings = settings or get_settings()
    hours_to_due: float | None = None
    overdue = False
    if task.due_at is not None:
        due = task.due_at if task.due_at.tzinfo else task.due_at.replace(tzinfo=timezone.utc)
        hours_to_due = (due - now).total_seconds() / 3600.0
        overdue = hours_to_due < 0

    remind_at = task.explicit_remind_at
    if remind_at is not None and remind_at.tzinfo is None:
        remind_at = remind_at.replace(tzinfo=timezone.utc)
    guaranteed = bool(remind_at is not None and remind_at <= now)

    try:
        tz = ZoneInfo(prefs.timezone or "UTC")
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    local_now = now.astimezone(tz)
    quiet = in_quiet_hours(local_now, prefs.quiet_start, prefs.quiet_end)
    schedule_fit = 0.2 if quiet else 1.0

    comps = ScoreComponents(
        due_urgency=due_urgency(hours_to_due, overdue),
        priority_norm=PRIORITY_NORM.get(task.priority, 0.5),
        staleness=staleness_score(task.last_notified_at, now),
        user_boost=0.5 if task.explicit_remind_at else 0.0,
        schedule_fit=schedule_fit,
        hours_to_due=round(hours_to_due, 3) if hours_to_due is not None else None,
        overdue=overdue,
        guaranteed=guaranteed,
    )
    score = (
        0.35 * comps.due_urgency
        + 0.25 * comps.priority_norm
        + 0.20 * comps.staleness
        + 0.10 * comps.user_boost
        + 0.10 * comps.schedule_fit
    )
    return _clamp(score), comps


def reason_from_components(comps: ScoreComponents, action: DecisionAction, score: float) -> str:
    parts: list[str] = []
    if comps.guaranteed:
        parts.append("explicit reminder time reached")
    if comps.overdue:
        parts.append("task is overdue")
    elif comps.hours_to_due is not None:
        if comps.hours_to_due <= 4:
            parts.append(f"due in {comps.hours_to_due:.1f}h")
        else:
            parts.append(f"due in ~{comps.hours_to_due:.0f}h")
    parts.append(f"priority weight {comps.priority_norm:.2f}")
    if comps.staleness >= 0.7:
        parts.append("no recent nudge")
    if comps.schedule_fit < 0.5:
        parts.append("inside quiet hours")
    why = ", ".join(parts) if parts else "baseline score"
    return f"Action={action.value} score={score:.2f}. Why: {why}."


def decide(
    task: Task,
    prefs: ReminderPreferences,
    now: datetime,
    daily_count: int,
    settings: Settings | None = None,
    preferred_channel: NotificationChannel | None = None,
) -> EngineDecision:
    settings = settings or get_settings()
    score, comps = score_task(task, prefs, now, settings)

    channels = prefs.channels or ["in_app"]
    channel_name = preferred_channel.value if preferred_channel else (
        "in_app" if "in_app" in channels else channels[0]
    )
    channel = NotificationChannel(channel_name)

    # Guaranteed path
    if comps.guaranteed:
        try:
            tz = ZoneInfo(prefs.timezone or "UTC")
        except Exception:  # noqa: BLE001
            tz = ZoneInfo("UTC")
        local_now = now.astimezone(tz)
        quiet = in_quiet_hours(local_now, prefs.quiet_start, prefs.quiet_end)
        if quiet and not task.force_within_quiet:
            action = DecisionAction.defer
            reason = reason_from_components(comps, action, score) + " Deferred to quiet_end."
            key = make_idempotency_key(
                task.user_id, task.id, window_bucket(now, action), channel.value, action.value
            )
            return EngineDecision(
                action=action,
                score=score,
                components=comps,
                reason_text=reason,
                guaranteed=True,
                idempotency_key=key,
                channel=channel,
            )
        action = DecisionAction.send
        reason = reason_from_components(comps, action, max(score, 1.0))
        key = make_idempotency_key(
            task.user_id, task.id, window_bucket(now, action), channel.value, action.value
        )
        return EngineDecision(
            action=action,
            score=max(score, 1.0),
            components=comps,
            reason_text=reason,
            guaranteed=True,
            idempotency_key=key,
            channel=channel,
        )

    threshold = max(prefs.min_score_threshold, settings.reminder_digest_threshold)
    send_threshold = settings.reminder_send_threshold

    if daily_count >= settings.reminder_daily_cap:
        action = DecisionAction.digest if prefs.digest_enabled else DecisionAction.defer
    elif score >= send_threshold and comps.schedule_fit >= 0.5:
        action = DecisionAction.send
    elif score >= threshold and prefs.digest_enabled:
        action = DecisionAction.digest
    elif comps.schedule_fit < 0.5 and score >= send_threshold:
        action = DecisionAction.defer
    else:
        action = DecisionAction.skip

    reason = reason_from_components(comps, action, score)
    key = make_idempotency_key(
        task.user_id, task.id, window_bucket(now, action), channel.value, action.value
    )
    return EngineDecision(
        action=action,
        score=score,
        components=comps,
        reason_text=reason,
        guaranteed=False,
        idempotency_key=key,
        channel=channel,
    )


class ReminderEngine:
    """Deterministic reminder evaluator with explainability + idempotency."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def get_daily_count(self, db: Session, user_id: UUID, day: date) -> int:
        row = (
            db.query(DailyNotifyCount)
            .filter(DailyNotifyCount.user_id == user_id, DailyNotifyCount.day == day)
            .first()
        )
        return row.count if row else 0

    def bump_daily_count(self, db: Session, user_id: UUID, day: date) -> None:
        row = (
            db.query(DailyNotifyCount)
            .filter(DailyNotifyCount.user_id == user_id, DailyNotifyCount.day == day)
            .first()
        )
        if row is None:
            row = DailyNotifyCount(user_id=user_id, day=day, count=1)
            db.add(row)
        else:
            row.count += 1

    def evaluate_task(
        self,
        db: Session,
        task: Task,
        user: User,
        prefs: ReminderPreferences,
        now: datetime | None = None,
    ) -> ReminderDecision | None:
        now = now or datetime.now(timezone.utc)
        if task.status in (TaskStatus.done, TaskStatus.cancelled):
            return None

        day = now.astimezone(timezone.utc).date()
        daily = self.get_daily_count(db, user.id, day)
        decision = decide(task, prefs, now, daily, self.settings)

        existing = (
            db.query(ReminderDecision)
            .filter(ReminderDecision.idempotency_key == decision.idempotency_key)
            .first()
        )
        if existing is not None:
            return existing

        row = ReminderDecision(
            user_id=user.id,
            task_id=task.id,
            scored_at=now,
            score=decision.score,
            components=decision.components.as_dict(),
            action=decision.action,
            reason_text=decision.reason_text,
            idempotency_key=decision.idempotency_key,
            weights_version=self.settings.reminder_weights_version,
            guaranteed=decision.guaranteed,
        )
        db.add(row)
        db.flush()

        if decision.action == DecisionAction.send and decision.channel is not None:
            channels = prefs.channels or ["in_app"]
            for ch_name in channels:
                try:
                    channel = NotificationChannel(ch_name)
                except ValueError:
                    continue
                payload = NotificationPayload(
                    user_id=user.id,
                    title=f"Reminder: {task.title}",
                    body=f"{task.title}\n\n{decision.reason_text}",
                    email=user.email,
                    related_decision_id=row.id,
                    extra={"task_id": str(task.id)},
                )
                record_and_send(db, channel, payload)
            task.last_notified_at = now
            self.bump_daily_count(db, user.id, day)
            # Clear explicit remind once fired
            if decision.guaranteed:
                task.explicit_remind_at = None

        db.commit()
        db.refresh(row)
        return row

    def evaluate_all(self, db: Session, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        tasks = (
            db.query(Task)
            .filter(Task.status.in_([TaskStatus.todo, TaskStatus.in_progress]))
            .all()
        )
        count = 0
        for task in tasks:
            user = db.get(User, task.user_id)
            if user is None:
                continue
            prefs = (
                db.query(ReminderPreferences)
                .filter(ReminderPreferences.user_id == user.id)
                .first()
            )
            if prefs is None:
                continue
            result = self.evaluate_task(db, task, user, prefs, now)
            if result is not None:
                count += 1
        return count
