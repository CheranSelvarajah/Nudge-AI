FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY nudge ./nudge
COPY alembic ./alembic
COPY alembic.ini ./
COPY entrypoint.sh ./

RUN pip install --no-cache-dir -e ".[dev]" \
    && chmod +x /app/entrypoint.sh

ENV PYTHONUNBUFFERED=1

CMD ["/bin/sh", "/app/entrypoint.sh"]
