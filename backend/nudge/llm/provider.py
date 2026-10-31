from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from nudge.core.config import Settings, get_settings

logger = logging.getLogger("nudge.llm")

EXTRACTION_SYSTEM_PROMPT = """You extract structured task drafts from natural language.
Return ONLY valid JSON matching this schema (no markdown):
{
  "tasks": [
    {
      "title": "string (required, concise)",
      "description": "string or null",
      "priority": "p0"|"p1"|"p2"|"p3",
      "due_at": "ISO-8601 datetime with offset, or null",
      "explicit_remind_at": "ISO-8601 datetime with offset, or null",
      "needs_clarification": false,
      "clarification_question": null
    }
  ],
  "notes": "optional short note for the user or null"
}
Rules:
- Prefer one task unless the user clearly lists multiple.
- Resolve relative dates (tomorrow, next Friday, in 3 days) using the given timezone and "now".
- Use priority p0=critical/urgent, p1=high, p2=medium (default), p3=low.
- If title/intent is critically ambiguous, set needs_clarification=true,
  ask one short question, and still provide a best-effort draft title.
- Never invent secrets or credentials. Do not write to any database.
"""


class LLMProvider(ABC):
    """Providers return raw JSON objects; callers validate with Pydantic."""

    name: str

    @abstractmethod
    def extract_tasks(
        self,
        text: str,
        *,
        timezone: str,
        now: datetime,
    ) -> dict[str, Any]:
        raise NotImplementedError


class StubLLMProvider(LLMProvider):
    """Deterministic extractor for tests and no-API-key local UX."""

    name = "stub"

    def extract_tasks(
        self,
        text: str,
        *,
        timezone: str,
        now: datetime,
    ) -> dict[str, Any]:
        cleaned = (text or "").strip()
        if not cleaned:
            return {
                "tasks": [
                    {
                        "title": "",
                        "description": None,
                        "priority": "p2",
                        "due_at": None,
                        "explicit_remind_at": None,
                        "needs_clarification": True,
                        "clarification_question": "What task should I create?",
                    }
                ],
                "notes": "Empty input",
            }

        tz = _safe_zone(timezone)
        local_now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)

        priority = _stub_priority(cleaned)
        due_at = _stub_due(cleaned, local_now)
        remind_at = _stub_remind(cleaned, local_now)
        title = _stub_title(cleaned)
        needs = len(title) < 3
        return {
            "tasks": [
                {
                    "title": title or "Untitled task",
                    "description": cleaned if cleaned.lower() != title.lower() else None,
                    "priority": priority,
                    "due_at": due_at.isoformat() if due_at else None,
                    "explicit_remind_at": remind_at.isoformat() if remind_at else None,
                    "needs_clarification": needs,
                    "clarification_question": (
                        "What should the task title be?" if needs else None
                    ),
                }
            ],
            "notes": "Parsed with stub provider (no live LLM key).",
        }


class OpenAILLMProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 45.0) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def extract_tasks(
        self,
        text: str,
        *,
        timezone: str,
        now: datetime,
    ) -> dict[str, Any]:
        import httpx

        tz = _safe_zone(timezone)
        local_now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
        user_prompt = (
            f"Timezone: {timezone}\n"
            f"Now (local): {local_now.isoformat()}\n"
            f"User text:\n{text.strip()}"
        )
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            res = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            res.raise_for_status()
            data = res.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    """Default OpenAI when key present; otherwise deterministic stub."""
    settings = settings or get_settings()
    provider = (settings.llm_provider or "openai").strip().lower()

    if provider == "stub":
        return StubLLMProvider()

    if provider in ("openai", "openai-compatible"):
        api_key = (settings.openai_api_key or "").strip()
        if api_key:
            return OpenAILLMProvider(
                api_key=api_key,
                model=settings.openai_model,
                timeout_seconds=settings.llm_timeout_seconds,
            )
        # Empty / whitespace key is expected for local Compose — stub, do not call OpenAI
        logger.warning("OPENAI_API_KEY unset; using stub LLM provider")
        return StubLLMProvider()

    if provider == "anthropic":
        # Phase 2 ships OpenAI as default; Anthropic reserved — fall back to stub.
        logger.warning("Anthropic provider not implemented in Phase 2; using stub")
        return StubLLMProvider()

    logger.warning("Unknown LLM_PROVIDER=%s; using stub", provider)
    return StubLLMProvider()


def _safe_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def _stub_priority(text: str) -> str:
    lower = text.lower()
    if re.search(r"\b(critical|urgent|asap|p0)\b", lower):
        return "p0"
    if re.search(r"\b(high priority|important|p1)\b", lower):
        return "p1"
    if re.search(r"\b(low priority|whenever|p3)\b", lower):
        return "p3"
    if re.search(r"\bp2\b", lower):
        return "p2"
    return "p2"


def _stub_due(text: str, local_now: datetime) -> datetime | None:
    lower = text.lower()
    if "day after tomorrow" in lower:
        return (local_now + timedelta(days=2)).replace(hour=17, minute=0, second=0, microsecond=0)
    if "tomorrow" in lower:
        return (local_now + timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)
    if "next week" in lower:
        return (local_now + timedelta(days=7)).replace(hour=17, minute=0, second=0, microsecond=0)
    m = re.search(r"\bin\s+(\d+)\s+days?\b", lower)
    if m:
        return (local_now + timedelta(days=int(m.group(1)))).replace(
            hour=17, minute=0, second=0, microsecond=0
        )
    m = re.search(r"\bin\s+(\d+)\s+hours?\b", lower)
    if m:
        return local_now + timedelta(hours=int(m.group(1)))
    return None


def _stub_remind(text: str, local_now: datetime) -> datetime | None:
    lower = text.lower()
    m = re.search(r"remind\s+me\s+in\s+(\d+)\s+hours?\b", lower)
    if m:
        return local_now + timedelta(hours=int(m.group(1)))
    m = re.search(r"remind\s+me\s+in\s+(\d+)\s+days?\b", lower)
    if m:
        return local_now + timedelta(days=int(m.group(1)))
    return None


def _stub_title(text: str) -> str:
    # Strip common relative-date / priority phrases for a cleaner title.
    title = text.strip()
    patterns = [
        r"\bday after tomorrow\b",
        r"\btomorrow\b",
        r"\bnext week\b",
        r"\bin\s+\d+\s+days?\b",
        r"\bin\s+\d+\s+hours?\b",
        r"\bremind\s+me\s+in\s+\d+\s+(hours?|days?)\b",
        r"\b(critical|urgent|asap|high priority|important|low priority|whenever)\b",
        r"\bp[0-3]\b",
        r"^(please\s+)?(add|create|make|schedule|remind me to|todo:?|task:?)\s+",
        r"^to\s+",
    ]
    for pat in patterns:
        title = re.sub(pat, " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" .,;:-")
    if not title:
        return text.strip()[:120]
    return title[:500]
