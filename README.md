# Nudge AI

Intelligent personal productivity assistant — Phase 1 core + Phase 2 NL task intake.

Deterministic reminder engine (scoring, quiet hours, guaranteed `remind_at`, explainability + idempotency) with React UI, FastAPI, Postgres, Redis, and Celery. Natural-language task intake uses an OpenAI-backed LLM provider (stub without a key) and **confirm-before-save**.

## Stack

| Layer | Choices |
|-------|---------|
| Web | React, TypeScript, Vite, Tailwind, shadcn-style UI, TanStack Query, RHF + Zod |
| API | FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, Postgres, Redis, Celery |
| Notify | `NotificationProvider` — In-app + Email (console/log by default) |
| Auth | Email + password (JWT) |

## Repo layout

```
frontend/          # Vite React app
backend/           # FastAPI + Celery + Alembic
docker-compose.yml
.env.example
```

## Quick start (Docker Compose)

Prerequisites: Docker Desktop / Compose.

```bash
cp .env.example .env
# edit JWT_SECRET at minimum
docker compose up --build
```

Services:

| Service | URL / role |
|---------|------------|
| web | http://localhost:5173 |
| api | http://localhost:8000 (docs at `/docs`) |
| db | Postgres `nudge`/`nudge` on 5432 |
| redis | 6379 |
| worker + beat | Reminder evaluation every 5 minutes |

Migrations run automatically on API container start via `backend/entrypoint.sh`.

### First user flow (smoke)

1. Open http://localhost:5173 → **Create account**
2. **Tasks** → add a task with a near due date and/or **Guaranteed remind at**
3. Optional NL: paste text under **Natural language** → review editable draft → **Confirm & save** (nothing persists until confirm)
4. Trigger evaluation: `POST /api/reminders/evaluate` (authorized) from Swagger or wait for Celery beat
5. Check **Notifications** for in-app nudges; email prints to the `api`/`worker` logs when `EMAIL_PROVIDER=console`

### Phase 2 LLM env

| Variable | Purpose |
|----------|---------|
| `LLM_PROVIDER` | `openai` (default) or `stub` |
| `OPENAI_API_KEY` | Required for live OpenAI extraction; leave empty to use deterministic stub |
| `OPENAI_MODEL` | Default `gpt-4o-mini` |
| `LLM_TIMEOUT_SECONDS` | HTTP timeout for provider calls |

Set keys only in local `.env` (copied from `.env.example`). Never commit secrets.

## Local development (without full Compose)

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e ".[dev]"
# Point DATABASE_URL / REDIS_URL at local Postgres + Redis
alembic upgrade head
uvicorn nudge.main:app --reload --port 8000
celery -A nudge.workers.celery_app.celery_app worker -B --loglevel=INFO
```

### Frontend

```bash
cd frontend
npm install
cp ../.env.example ../.env   # ensure VITE_API_URL=http://localhost:8000/api
npm run dev
```

## Tests

```bash
cd backend
pytest -q
# Focused reminder engine suite:
pytest tests/unit/test_reminder_engine.py -q
```

```bash
cd frontend
npm run build   # typecheck via tsc
```

## Scope

**Phase 1:** auth, task CRUD, dashboard, preferences, ReminderEngine, NotificationProvider, Compose, Alembic, tests, GHA.

**Phase 2:** NL extract (`POST /api/nl/extract`) → editable draft → confirm (`POST /api/nl/proposals/{id}/confirm`) creates tasks via task service with `source=nl`; `nl_proposals` audit of proposed vs accepted; OpenAI provider + stub.

**Later:** LangGraph planning, RAG, Google Calendar, web push.
