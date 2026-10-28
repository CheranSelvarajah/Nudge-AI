from datetime import time
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from nudge.auth.security import decode_access_token
from nudge.core.db import get_db
from nudge.core.models import ReminderPreferences, User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(creds.credentials)
        user_id = UUID(payload["sub"])
    except (ValueError, KeyError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def ensure_preferences(db: Session, user: User) -> ReminderPreferences:
    if user.preferences is not None:
        return user.preferences
    prefs = ReminderPreferences(
        user_id=user.id,
        quiet_start=time(22, 0),
        quiet_end=time(7, 0),
        channels=["in_app", "email"],
        digest_enabled=True,
        digest_time=time(9, 0),
        timezone=user.timezone or "UTC",
    )
    db.add(prefs)
    db.commit()
    db.refresh(prefs)
    return prefs
