from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from nudge.auth.deps import get_current_user
from nudge.core.db import get_db
from nudge.core.models import Task, TaskSource, TaskStatus, User
from nudge.tasks.schemas import TaskCreate, TaskOut, TaskUpdate
from nudge.tasks.service import apply_task_update, create_task_for_user, get_user_task

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
def list_tasks(
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    priority: str | None = None,
    due_before: datetime | None = None,
    due_after: datetime | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Task]:
    q = db.query(Task).filter(Task.user_id == user.id)
    if status_filter is not None:
        q = q.filter(Task.status == status_filter)
    if priority is not None:
        q = q.filter(Task.priority == priority)
    if due_before is not None:
        q = q.filter(Task.due_at <= due_before)
    if due_after is not None:
        q = q.filter(Task.due_at >= due_after)
    return q.order_by(Task.due_at.asc().nullslast(), Task.created_at.desc()).all()


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(
    body: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Task:
    return create_task_for_user(db, user, body, source=TaskSource.manual)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(
    task_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Task:
    task = get_user_task(db, user.id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: UUID,
    body: TaskUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Task:
    task = get_user_task(db, user.id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    data = body.model_dump(exclude_unset=True)
    apply_task_update(task, data)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    task = get_user_task(db, user.id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
