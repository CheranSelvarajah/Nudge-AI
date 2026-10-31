from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from nudge.auth.deps import ensure_preferences
from nudge.core.config import get_settings
from nudge.core.models import NlProposal, NlProposalStatus, TaskSource, User
from nudge.llm.provider import LLMProvider, expand_collapsed_extraction, get_llm_provider
from nudge.nl_intake.schemas import (
    ConfirmRequest,
    ExtractionPayload,
    ExtractResponse,
    TaskDraft,
)
from nudge.tasks.schemas import TaskCreate, TaskOut
from nudge.tasks.service import create_task_for_user

logger = logging.getLogger("nudge.nl_intake")


def resolve_timezone(user: User, db: Session, override: str | None) -> str:
    if override and override.strip():
        return override.strip()
    prefs = ensure_preferences(db, user)
    return prefs.timezone or user.timezone or "UTC"


def _parse_datetime(value: Any, tz_name: str) -> datetime | None:
    """Parse extraction datetimes as user wall-clock times (DST-safe).

    OpenAI often emits the right clock face with a stale Eastern offset
    (e.g. 14:00-04:00 on the Nov DST fall-back Sunday → shows as 1pm EST).
    Non-UTC values are reinterpreted as Y-M-D H:M in the user's IANA zone.
    UTC/Z instants are converted with astimezone (preserve absolute time).
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")

    if dt.tzinfo is None:
        return datetime(
            dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, tzinfo=tz
        )

    offset = dt.utcoffset()
    if offset is not None and offset.total_seconds() == 0:
        return dt.astimezone(tz)

    # Trust the wall-clock fields; attach ZoneInfo so DST offset is correct.
    return datetime(
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, tzinfo=tz
    )


def normalize_raw_extraction(raw: dict[str, Any], tz_name: str) -> ExtractionPayload:
    """Coerce LLM/stub JSON into validated TaskDrafts; soft-fix salvage when possible."""
    tasks_raw = raw.get("tasks") if isinstance(raw, dict) else None
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise ValueError("Extraction missing tasks array")

    drafts: list[TaskDraft] = []
    for item in tasks_raw:
        if not isinstance(item, dict):
            continue
        data = dict(item)
        data["due_at"] = _parse_datetime(data.get("due_at"), tz_name)
        data["explicit_remind_at"] = _parse_datetime(data.get("explicit_remind_at"), tz_name)
        title = str(data.get("title") or "").strip()
        if not title:
            data["title"] = "Untitled task"
            data["needs_clarification"] = True
            data["clarification_question"] = data.get("clarification_question") or (
                "What should the task title be?"
            )
        drafts.append(TaskDraft.model_validate(data))

    if not drafts:
        raise ValueError("No valid task drafts in extraction")

    notes = raw.get("notes") if isinstance(raw, dict) else None
    return ExtractionPayload(tasks=drafts, notes=notes if isinstance(notes, str) else None)


def extract_and_store(
    db: Session,
    user: User,
    text: str,
    *,
    timezone_override: str | None = None,
    provider: LLMProvider | None = None,
    now: datetime | None = None,
) -> ExtractResponse:
    settings = get_settings()
    tz_name = resolve_timezone(user, db, timezone_override)
    llm = provider or get_llm_provider(settings)
    clock = now or datetime.now(timezone.utc)

    raw = llm.extract_tasks(text, timezone=tz_name, now=clock)
    # OpenAI sometimes collapses 2 deliverables into 1 — split from source heuristics
    raw = expand_collapsed_extraction(
        text.strip(),
        raw,
        timezone=tz_name,
        now=clock,
    )
    payload = normalize_raw_extraction(raw, tz_name)

    proposal = NlProposal(
        user_id=user.id,
        source_text=text.strip(),
        proposed_draft=payload.model_dump(mode="json"),
        status=NlProposalStatus.pending,
        llm_provider=llm.name,
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)

    questions = [
        d.clarification_question
        for d in payload.tasks
        if d.needs_clarification and d.clarification_question
    ]
    return ExtractResponse(
        proposal_id=proposal.id,
        status=proposal.status,
        source_text=proposal.source_text,
        drafts=payload.tasks,
        notes=payload.notes,
        llm_provider=proposal.llm_provider,
        needs_clarification=any(d.needs_clarification for d in payload.tasks),
        clarification_questions=questions,
    )


def get_proposal(db: Session, user: User, proposal_id: UUID) -> NlProposal | None:
    return (
        db.query(NlProposal)
        .filter(NlProposal.id == proposal_id, NlProposal.user_id == user.id)
        .first()
    )


def confirm_proposal(
    db: Session,
    user: User,
    proposal: NlProposal,
    body: ConfirmRequest,
) -> tuple[NlProposal, list[TaskOut]]:
    if proposal.status != NlProposalStatus.pending:
        raise ValueError("Proposal is no longer pending")

    accepted = ExtractionPayload(
        tasks=[
            TaskDraft(
                title=d.title,
                description=d.description,
                priority=d.priority,
                due_at=d.due_at,
                explicit_remind_at=d.explicit_remind_at,
                needs_clarification=False,
                clarification_question=None,
            )
            for d in body.drafts
        ],
        notes=None,
    )

    created: list[TaskOut] = []
    task_ids: list[str] = []
    for draft in accepted.tasks:
        task = create_task_for_user(
            db,
            user,
            TaskCreate(
                title=draft.title,
                description=draft.description,
                priority=draft.priority,
                due_at=draft.due_at,
                explicit_remind_at=draft.explicit_remind_at,
            ),
            source=TaskSource.nl,
        )
        created.append(TaskOut.model_validate(task))
        task_ids.append(str(task.id))

    proposal.accepted_draft = {
        "tasks": [d.model_dump(mode="json") for d in body.drafts],
    }
    proposal.status = NlProposalStatus.accepted
    proposal.created_task_ids = task_ids
    proposal.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(proposal)
    return proposal, created


def reject_proposal(db: Session, user: User, proposal: NlProposal) -> NlProposal:
    if proposal.status != NlProposalStatus.pending:
        raise ValueError("Proposal is no longer pending")
    proposal.status = NlProposalStatus.rejected
    proposal.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(proposal)
    return proposal
