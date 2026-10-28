import logging

from nudge.core.db import SessionLocal
from nudge.core.logging import setup_logging
from nudge.reminders.engine import ReminderEngine
from nudge.workers.celery_app import celery_app

setup_logging()
logger = logging.getLogger(__name__)


@celery_app.task(name="nudge.workers.tasks.evaluate_reminders")
def evaluate_reminders() -> dict[str, int]:
    db = SessionLocal()
    try:
        engine = ReminderEngine()
        count = engine.evaluate_all(db)
        logger.info("evaluate_reminders_complete decisions=%s", count)
        return {"decisions": count}
    finally:
        db.close()
