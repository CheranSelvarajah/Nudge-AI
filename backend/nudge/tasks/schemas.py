from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from nudge.core.models import TaskPriority, TaskSource, TaskStatus


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    status: TaskStatus = TaskStatus.todo
    priority: TaskPriority = TaskPriority.p2
    due_at: datetime | None = None
    explicit_remind_at: datetime | None = None
    force_within_quiet: bool = False


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_at: datetime | None = None
    explicit_remind_at: datetime | None = None
    force_within_quiet: bool | None = None


class TaskOut(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    due_at: datetime | None
    completed_at: datetime | None
    source: TaskSource
    explicit_remind_at: datetime | None
    force_within_quiet: bool
    last_notified_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
