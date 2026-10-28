from celery import Celery
from celery.schedules import schedule

from nudge.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "nudge",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["nudge.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "evaluate-reminders": {
            "task": "nudge.workers.tasks.evaluate_reminders",
            "schedule": schedule(run_every=settings.reminder_eval_interval_seconds),
        },
    },
)
