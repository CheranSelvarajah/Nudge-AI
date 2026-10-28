from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from nudge.core.models import NlProposalStatus, TaskPriority


class TaskDraft(BaseModel):
    """Structured task draft returned by the LLM — never written to tasks until confirm."""

    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    priority: TaskPriority = TaskPriority.p2
    due_at: datetime | None = None
    explicit_remind_at: datetime | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("title must not be blank")
        return cleaned


class ExtractionPayload(BaseModel):
    """Pydantic-validated LLM extraction output."""

    tasks: list[TaskDraft] = Field(min_length=1)
    notes: str | None = None


class ExtractRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    timezone: str | None = Field(
        default=None,
        description="IANA timezone for relative dates; defaults to user preference/account tz",
    )


class ExtractResponse(BaseModel):
    proposal_id: UUID
    status: NlProposalStatus
    source_text: str
    drafts: list[TaskDraft]
    notes: str | None
    llm_provider: str
    needs_clarification: bool
    clarification_questions: list[str]


class ConfirmDraft(BaseModel):
    """User-edited draft fields accepted on confirm (clarification flags ignored)."""

    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    priority: TaskPriority = TaskPriority.p2
    due_at: datetime | None = None
    explicit_remind_at: datetime | None = None


class ConfirmRequest(BaseModel):
    drafts: list[ConfirmDraft] = Field(min_length=1)


class ProposalOut(BaseModel):
    id: UUID
    status: NlProposalStatus
    source_text: str
    proposed_draft: dict[str, Any]
    accepted_draft: dict[str, Any] | None
    llm_provider: str
    created_task_ids: list[str] | None
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class ConfirmResponse(BaseModel):
    proposal: ProposalOut
    tasks: list[dict[str, Any]]
