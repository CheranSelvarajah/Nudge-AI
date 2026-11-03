from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from nudge.core.models import Task, TaskSource, TaskStatus, User
from nudge.tasks.schemas import TaskCreate


def create_task_for_user(
    db: Session,
    user: User,
    body: TaskCreate,
    *,
    source: TaskSource = TaskSource.manual,
) -> Task:
    data = body.model_dump()
    task = Task(user_id=user.id, source=source, **data)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_user_task(db: Session, user_id: UUID, task_id: UUID) -> Task | None:
    return db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()


def apply_task_update(task: Task, data: dict) -> None:
    if data.get("status") == TaskStatus.done and task.completed_at is None:
        data["completed_at"] = datetime.now(timezone.utc)
    if data.get("status") is not None and data["status"] != TaskStatus.done:
        data["completed_at"] = None
    for key, value in data.items():
        setattr(task, key, value)
