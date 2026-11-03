import logging
import time
from collections.abc import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from nudge.auth.router import router as auth_router
from nudge.core.config import get_settings
from nudge.core.logging import new_request_id, setup_logging
from nudge.nl_intake.router import router as nl_intake_router
from nudge.notifications.router import router as notifications_router
from nudge.preferences.router import router as preferences_router
from nudge.reminders.router import router as reminders_router
from nudge.tasks.router import router as tasks_router

setup_logging()
logger = logging.getLogger("nudge.api")
settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging(request: Request, call_next: Callable) -> Response:
    request_id = request.headers.get("x-request-id") or new_request_id()
    start = time.perf_counter()
    response: Response | None = None
    try:
        response = await call_next(request)
        return response
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        status_code = response.status_code if response is not None else 500
        logger.info(
            "request method=%s path=%s status=%s duration_ms=%s request_id=%s",
            request.method,
            request.url.path,
            status_code,
            duration_ms,
            request_id,
        )
        if response is not None:
            response.headers["X-Request-Id"] = request_id


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


prefix = settings.api_prefix
app.include_router(auth_router, prefix=prefix)
app.include_router(tasks_router, prefix=prefix)
app.include_router(preferences_router, prefix=prefix)
app.include_router(notifications_router, prefix=prefix)
app.include_router(reminders_router, prefix=prefix)
app.include_router(nl_intake_router, prefix=prefix)
