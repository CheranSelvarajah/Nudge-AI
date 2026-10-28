from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from nudge.auth.deps import ensure_preferences, get_current_user
from nudge.core.db import get_db
from nudge.core.models import User
from nudge.preferences.schemas import PreferencesOut, PreferencesUpdate

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("", response_model=PreferencesOut)
def get_preferences(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PreferencesOut:
    prefs = ensure_preferences(db, user)
    return prefs


@router.patch("", response_model=PreferencesOut)
def update_preferences(
    body: PreferencesUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PreferencesOut:
    prefs = ensure_preferences(db, user)
    data = body.model_dump(exclude_unset=True)
    if "channels" in data:
        allowed = {"email", "in_app"}
        channels = [c for c in data["channels"] if c in allowed]
        if not channels:
            channels = ["in_app"]
        data["channels"] = channels
    for key, value in data.items():
        setattr(prefs, key, value)
    if "timezone" in data and data["timezone"]:
        user.timezone = data["timezone"]
    db.commit()
    db.refresh(prefs)
    return prefs
