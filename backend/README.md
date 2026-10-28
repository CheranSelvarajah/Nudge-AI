# Nudge AI — Backend

FastAPI modular monolith for Phase 1.

```bash
pip install -e ".[dev]"
alembic upgrade head
uvicorn nudge.main:app --reload
celery -A nudge.workers.celery_app.celery_app worker -B --loglevel=INFO
pytest
```
