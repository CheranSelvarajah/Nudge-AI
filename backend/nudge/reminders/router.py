from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from nudge.auth.deps import get_current_user
from nudge.core.db import get_db
from nudge.core.models import User
from nudge.reminders.engine import ReminderEngine

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.post("/evaluate")
def evaluate_now(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int]:
    """Dev/smoke helper: run reminder evaluation immediately (also done by Celery beat)."""
    _ = user
    count = ReminderEngine().evaluate_all(db)
    return {"decisions": count}
