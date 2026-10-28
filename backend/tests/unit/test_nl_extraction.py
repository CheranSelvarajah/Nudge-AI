from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from nudge.llm.provider import StubLLMProvider, get_llm_provider
from nudge.nl_intake.schemas import ExtractionPayload, TaskDraft
from nudge.nl_intake.service import normalize_raw_extraction


def test_task_draft_rejects_blank_title():
    with pytest.raises(ValidationError):
        TaskDraft(title="   ")


def test_extraction_payload_requires_task():
    with pytest.raises(ValidationError):
        ExtractionPayload(tasks=[])


def test_stub_provider_resolves_tomorrow_in_user_tz():
    provider = StubLLMProvider()
    now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    raw = provider.extract_tasks(
        "Finish taxes tomorrow high priority",
        timezone="America/Toronto",
        now=now,
    )
    payload = normalize_raw_extraction(raw, "America/Toronto")
    assert len(payload.tasks) == 1
    draft = payload.tasks[0]
    assert "taxes" in draft.title.lower()
    assert draft.priority.value == "p1"
    assert draft.due_at is not None
    local = draft.due_at.astimezone(ZoneInfo("America/Toronto"))
    assert local.date().isoformat() == "2026-10-29"
    assert local.hour == 17


def test_stub_provider_in_n_days_and_remind():
    provider = StubLLMProvider()
    now = datetime(2026, 10, 28, 9, 0, tzinfo=ZoneInfo("UTC"))
    raw = provider.extract_tasks(
        "Ship docs in 3 days, remind me in 1 day",
        timezone="UTC",
        now=now,
    )
    payload = normalize_raw_extraction(raw, "UTC")
    draft = payload.tasks[0]
    assert draft.due_at is not None
    assert (draft.due_at - now).days == 3
    assert draft.explicit_remind_at is not None
    assert (draft.explicit_remind_at - now).days == 1


def test_stub_empty_asks_clarification():
    provider = StubLLMProvider()
    raw = provider.extract_tasks("  ", timezone="UTC", now=datetime.now(timezone.utc))
    assert raw["tasks"][0]["needs_clarification"] is True


def test_normalize_salvages_missing_title():
    raw = {
        "tasks": [
            {
                "title": "",
                "priority": "p2",
                "due_at": None,
                "explicit_remind_at": None,
            }
        ],
        "notes": None,
    }
    payload = normalize_raw_extraction(raw, "UTC")
    assert payload.tasks[0].title == "Untitled task"
    assert payload.tasks[0].needs_clarification is True


def test_get_llm_provider_defaults_to_stub_without_key(monkeypatch):
    from nudge.core.config import Settings

    settings = Settings(openai_api_key="", llm_provider="openai")
    provider = get_llm_provider(settings)
    assert provider.name == "stub"


def test_get_llm_provider_openai_when_key_set():
    from nudge.core.config import Settings
    from nudge.llm.provider import OpenAILLMProvider

    settings = Settings(openai_api_key="sk-test-not-real", llm_provider="openai")
    provider = get_llm_provider(settings)
    assert isinstance(provider, OpenAILLMProvider)
    assert provider.name == "openai"
