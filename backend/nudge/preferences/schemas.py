from datetime import datetime, time
from uuid import UUID

from pydantic import BaseModel, Field


class PreferencesUpdate(BaseModel):
    quiet_start: time | None = None
    quiet_end: time | None = None
    channels: list[str] | None = Field(default=None, min_length=1)
    digest_enabled: bool | None = None
    digest_time: time | None = None
    min_score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    timezone: str | None = None


class PreferencesOut(BaseModel):
    id: UUID
    user_id: UUID
    quiet_start: time
    quiet_end: time
    channels: list[str]
    digest_enabled: bool
    digest_time: time
    min_score_threshold: float
    timezone: str
    updated_at: datetime

    model_config = {"from_attributes": True}
