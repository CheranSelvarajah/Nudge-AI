from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nudge.auth.deps import get_current_user
from nudge.core.db import get_db
from nudge.core.models import InAppNotification, User

router = APIRouter(prefix="/notifications", tags=["notifications"])


class InAppNotificationOut(BaseModel):
    id: UUID
    title: str
    body: str
    read_at: datetime | None
    related_decision_id: UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/in-app", response_model=list[InAppNotificationOut])
def list_in_app(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[InAppNotification]:
    q = db.query(InAppNotification).filter(InAppNotification.user_id == user.id)
    if unread_only:
        q = q.filter(InAppNotification.read_at.is_(None))
    return q.order_by(InAppNotification.created_at.desc()).limit(100).all()


@router.post("/in-app/{notification_id}/read", response_model=InAppNotificationOut)
def mark_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InAppNotification:
    row = (
        db.query(InAppNotification)
        .filter(InAppNotification.id == notification_id, InAppNotification.user_id == user.id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if row.read_at is None:
        row.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
    return row


@router.post("/in-app/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    updated = (
        db.query(InAppNotification)
        .filter(InAppNotification.user_id == user.id, InAppNotification.read_at.is_(None))
        .update({"read_at": now})
    )
    db.commit()
    return {"updated": updated}
