from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from nudge.core.config import get_settings
from nudge.core.models import (
    InAppNotification,
    Notification,
    NotificationChannel,
    NotificationStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class NotificationPayload:
    user_id: UUID
    title: str
    body: str
    email: str | None = None
    related_decision_id: UUID | None = None
    extra: dict[str, Any] | None = None


@dataclass
class DeliveryResult:
    status: NotificationStatus
    provider_message_id: str | None = None
    detail: str | None = None


class NotificationProvider(ABC):
    channel: NotificationChannel

    @abstractmethod
    def send(self, db: Session, payload: NotificationPayload) -> DeliveryResult:
        raise NotImplementedError


class InAppProvider(NotificationProvider):
    channel = NotificationChannel.in_app

    def send(self, db: Session, payload: NotificationPayload) -> DeliveryResult:
        row = InAppNotification(
            user_id=payload.user_id,
            title=payload.title,
            body=payload.body,
            related_decision_id=payload.related_decision_id,
        )
        db.add(row)
        db.flush()
        return DeliveryResult(
            status=NotificationStatus.sent,
            provider_message_id=str(row.id),
        )


class EmailProvider(NotificationProvider):
    """Console/log email by default; SMTP when EMAIL_PROVIDER=smtp."""

    channel = NotificationChannel.email

    def send(self, db: Session, payload: NotificationPayload) -> DeliveryResult:
        _ = db
        settings = get_settings()
        message_id = f"email-{uuid4().hex}"
        to = payload.email or "(unknown)"
        if settings.email_provider == "smtp" and settings.smtp_host:
            # Minimal SMTP stub — full MIME deferred; still records attempt.
            try:
                import smtplib
                from email.message import EmailMessage

                msg = EmailMessage()
                msg["Subject"] = payload.title
                msg["From"] = settings.smtp_from
                msg["To"] = to
                msg.set_content(payload.body)
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                    if settings.smtp_user:
                        smtp.starttls()
                        smtp.login(settings.smtp_user, settings.smtp_password)
                    smtp.send_message(msg)
                return DeliveryResult(
                    status=NotificationStatus.sent,
                    provider_message_id=message_id,
                )
            except Exception as exc:  # noqa: BLE001 — provider boundary
                logger.exception("smtp_send_failed")
                return DeliveryResult(
                    status=NotificationStatus.failed,
                    provider_message_id=message_id,
                    detail=str(exc),
                )

        # Default: console / structured log (no secrets / full body at info)
        logger.info(
            "email_console_stub to=%s subject=%s decision=%s",
            to,
            payload.title,
            payload.related_decision_id,
        )
        print(f"[Nudge Email] To: {to}\nSubject: {payload.title}\n\n{payload.body}\n")
        return DeliveryResult(status=NotificationStatus.sent, provider_message_id=message_id)


def get_providers() -> dict[NotificationChannel, NotificationProvider]:
    return {
        NotificationChannel.in_app: InAppProvider(),
        NotificationChannel.email: EmailProvider(),
    }


def record_and_send(
    db: Session,
    channel: NotificationChannel,
    payload: NotificationPayload,
) -> Notification:
    providers = get_providers()
    provider = providers[channel]
    result = provider.send(db, payload)
    notification = Notification(
        user_id=payload.user_id,
        channel=channel,
        payload={
            "title": payload.title,
            "body": payload.body,
            **(payload.extra or {}),
        },
        status=result.status,
        provider_message_id=result.provider_message_id,
        related_decision_id=payload.related_decision_id,
    )
    db.add(notification)
    db.flush()
    return notification
