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
- ALWAYS emit one tasks[] entry per distinct deliverable / action when the text has 2+
  separate work items. Hard triggers (each MUST become its own tasks[] row):
  • "part a" / "part b" / "part 1" / "part 2" (or more)
  • "and then …" / "and also …" introducing another verb/deliverable
  • Two or more distinct deadlines ("by Sunday 2pm" … "by 11:59 same day")
  • Numbered/bulleted lists (1) 2) or 1. 2.)
- Example — input:
  "Finish part a of the controls lab by sunday 2pm and then submit the French test by 11:59 same day"
  → tasks MUST have length 2, e.g.:
  [{"title":"Finish controls lab part a","due_at":"<Sunday 14:00>"},
   {"title":"Submit French test","due_at":"<same Sunday 23:59>"}]
- Do NOT collapse into one task with notes/clarification like "you mentioned two things".
  notes must NEVER substitute for a second tasks[] entry.
- Use one task only when the user describes a single work item (even if long).
- Resolve relative dates (tomorrow, Sunday, next Friday, in 3 days, 2pm, 11:59, same day)
  using the given timezone and "now". Apply dates per task; "same day" = calendar day of
  the other deadline in the sentence.
- Use priority p0=critical/urgent, p1=high, p2=medium (default), p3=low.
- If a single item's title/intent is critically ambiguous, set needs_clarification=true,
  ask one short question, and still provide a best-effort draft title.
  Never use needs_clarification merely because there are multiple clear tasks.
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

        segments = _stub_task_segments(cleaned)
        shared_priority = _stub_priority(cleaned)
        tasks: list[dict[str, Any]] = []
        anchor_due: datetime | None = None
        for seg in segments:
            priority = _stub_priority(seg) if _stub_priority(seg) != "p2" else shared_priority
            due_at = _stub_due(seg, local_now, anchor_day=anchor_due) or (
                _stub_due(cleaned, local_now) if len(segments) == 1 else None
            )
            if due_at is not None and anchor_due is None:
                anchor_due = due_at
            remind_at = _stub_remind(seg, local_now) or (
                _stub_remind(cleaned, local_now) if len(segments) == 1 else None
            )
            title = _stub_title(seg)
            needs = len(title) < 3
            tasks.append(
                {
                    "title": title or "Untitled task",
                    "description": cleaned if len(segments) > 1 else (
                        cleaned if cleaned.lower() != title.lower() else None
                    ),
                    "priority": priority,
                    "due_at": due_at.isoformat() if due_at else None,
                    "explicit_remind_at": remind_at.isoformat() if remind_at else None,
                    "needs_clarification": needs,
                    "clarification_question": (
                        "What should the task title be?" if needs else None
                    ),
                }
            )
        note = "Parsed with stub provider (no live LLM key)."
        if len(tasks) > 1:
            note = f"{note} Split into {len(tasks)} drafts."
        return {"tasks": tasks, "notes": note}


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


_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _parse_clock(text: str) -> tuple[int, int] | None:
    lower = text.lower()
    m = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b", lower)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        ampm = m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        elif ampm is None and hour == 11 and minute == 59:
            # Academic "by 11:59" almost always means end-of-day 23:59
            hour = 23
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    m = re.search(r"\b(\d{1,2})\s*(am|pm)\b", lower)
    if m:
        hour = int(m.group(1))
        ampm = m.group(2)
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23:
            return hour, 0
    return None


def _stub_due(
    text: str,
    local_now: datetime,
    *,
    anchor_day: datetime | None = None,
) -> datetime | None:
    lower = text.lower()
    clock = _parse_clock(lower)
    hour = clock[0] if clock else 17
    minute = clock[1] if clock else 0

    if "same day" in lower and anchor_day is not None:
        return anchor_day.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if "day after tomorrow" in lower:
        return (local_now + timedelta(days=2)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
    if "tomorrow" in lower:
        return (local_now + timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
    if "next week" in lower:
        return (local_now + timedelta(days=7)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )

    for name, weekday in _WEEKDAYS.items():
        if re.search(rf"\b{name}\b", lower):
            days_ahead = (weekday - local_now.weekday()) % 7
            candidate = (local_now + timedelta(days=days_ahead)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            # If that weekday/time already passed today, jump a week
            if days_ahead == 0 and candidate <= local_now:
                candidate = candidate + timedelta(days=7)
            return candidate

    m = re.search(r"\bin\s+(\d+)\s+days?\b", lower)
    if m:
        return (local_now + timedelta(days=int(m.group(1)))).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
    m = re.search(r"\bin\s+(\d+)\s+hours?\b", lower)
    if m:
        return local_now + timedelta(hours=int(m.group(1)))

    # Bare clock with "by" and no weekday — use today/anchor if still upcoming
    if clock and re.search(r"\bby\b", lower):
        base = anchor_day or local_now
        candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate < local_now and anchor_day is None:
            candidate = candidate + timedelta(days=1)
        return candidate
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


def _stub_task_segments(text: str) -> list[str]:
    """Split clearly multi-deliverable text into one segment per task."""
    cleaned = text.strip()
    if not cleaned:
        return []

    # "and then" is a hard split (controls lab … and then French test)
    then_parts = [
        p.strip(" ,;")
        for p in re.split(r"\s+and then\s+", cleaned, flags=re.IGNORECASE)
        if p.strip(" ,;")
    ]
    if len(then_parts) >= 2:
        return then_parts

    # Newline / semicolon list with bullets or numbers
    pieces = [p.strip() for p in re.split(r"[\n;]+", cleaned) if p.strip()]
    numbered = [
        p for p in pieces if re.match(r"^(\d+[\.\)]|[-*•])\s+\S", p)
    ]
    if len(numbered) >= 2:
        return [re.sub(r"^(\d+[\.\)]|[-*•])\s+", "", p).strip() for p in numbered]

    # "part 1"/"part a" … "part 2"/"part b"
    part_hits = list(re.finditer(r"\bpart\s+([0-9]+|[a-z])\b", cleaned, flags=re.IGNORECASE))
    if len(part_hits) >= 2:
        prefix = cleaned[: part_hits[0].start()].strip()
        prefix = re.sub(r"\bpart\s+([0-9]+|[a-z])\b.*", "", prefix, flags=re.IGNORECASE).strip(
            " ,;-"
        )
        segments: list[str] = []
        for i, match in enumerate(part_hits):
            end = part_hits[i + 1].start() if i + 1 < len(part_hits) else len(cleaned)
            chunk = cleaned[match.start() : end].strip()
            if i + 1 < len(part_hits):
                chunk = re.sub(r"(,|\band)\s+\w+\s*$", "", chunk, flags=re.IGNORECASE).strip()
            chunk = re.sub(r"^(,|and)\s+", "", chunk, flags=re.IGNORECASE).strip(" ,;")
            if prefix and prefix.lower() not in chunk.lower()[: max(40, len(prefix) + 5)]:
                chunk = f"{prefix} {chunk}".strip()
            if chunk:
                segments.append(chunk)
        if len(segments) >= 2:
            return segments

    # Explicit "and also" / "then also"
    also_parts = [
        p.strip(" ,;")
        for p in re.split(r"\s+and also\s+|\s+then also\s+", cleaned, flags=re.IGNORECASE)
        if p.strip(" ,;")
    ]
    if len(also_parts) >= 2:
        return also_parts

    # Two+ "by <deadline>" clauses joined by "and"
    by_hits = list(re.finditer(r"\bby\b", cleaned, flags=re.IGNORECASE))
    if len(by_hits) >= 2:
        mid = cleaned[by_hits[0].end() : by_hits[1].start()]
        and_m = re.search(r"\band\b", mid, flags=re.IGNORECASE)
        if and_m:
            split_at = by_hits[0].end() + and_m.start()
            left = cleaned[:split_at].strip(" ,;")
            right = cleaned[split_at:]
            right = re.sub(r"^\s*and\s+", "", right, flags=re.IGNORECASE).strip(" ,;")
            if left and right:
                return [left, right]

    return [cleaned]


def expand_collapsed_extraction(
    source_text: str,
    raw: dict[str, Any],
    *,
    timezone: str,
    now: datetime,
) -> dict[str, Any]:
    """If the model returned one draft but the source has 2+ deliverables, split it."""
    tasks = raw.get("tasks") if isinstance(raw, dict) else None
    if not isinstance(tasks, list) or len(tasks) != 1:
        return raw

    segments = _stub_task_segments(source_text)
    if len(segments) < 2:
        return raw

    tz = _safe_zone(timezone)
    local_now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
    base = tasks[0] if isinstance(tasks[0], dict) else {}
    shared_priority = str(base.get("priority") or _stub_priority(source_text))
    rebuilt: list[dict[str, Any]] = []
    anchor: datetime | None = None
    for seg in segments:
        due = _stub_due(seg, local_now, anchor_day=anchor)
        if due is not None and anchor is None:
            anchor = due
        title = _stub_title(seg)
        rebuilt.append(
            {
                "title": title or "Untitled task",
                "description": source_text.strip(),
                "priority": (
                    _stub_priority(seg) if _stub_priority(seg) != "p2" else shared_priority
                ),
                "due_at": due.isoformat() if due else None,
                "explicit_remind_at": None,
                "needs_clarification": len(title) < 3,
                "clarification_question": (
                    "What should the task title be?" if len(title) < 3 else None
                ),
            }
        )

    notes = raw.get("notes") if isinstance(raw.get("notes"), str) else None
    split_note = f"Split collapsed extraction into {len(rebuilt)} drafts."
    notes = f"{notes} {split_note}".strip() if notes else split_note
    logger.info(
        "expand_collapsed_extraction source_tasks=1 segments=%s",
        len(rebuilt),
    )
    return {"tasks": rebuilt, "notes": notes}


def _stub_title(text: str) -> str:
    # Strip common relative-date / priority phrases for a cleaner title.
    title = text.strip()
    patterns = [
        r"\bday after tomorrow\b",
        r"\bsame day\b",
        r"\bnext week\b",
        r"\btomorrow\b",
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\bin\s+\d+\s+days?\b",
        r"\bin\s+\d+\s+hours?\b",
        r"\bby\s+\d{1,2}(:\d{2})?\s*(am|pm)?\b",
        r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b",
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
