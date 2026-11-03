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


def test_stub_splits_two_lab_parts_into_two_drafts():
    """Fixture: distinct deliverables must each become a draft (not one + note)."""
    provider = StubLLMProvider()
    now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    text = (
        "Finish lab part 1 tomorrow high priority and lab part 2 next week"
    )
    raw = provider.extract_tasks(text, timezone="America/Toronto", now=now)
    payload = normalize_raw_extraction(raw, "America/Toronto")
    assert len(payload.tasks) == 2
    titles = " ".join(t.title.lower() for t in payload.tasks)
    assert "part 1" in titles
    assert "part 2" in titles
    assert all(not t.needs_clarification for t in payload.tasks)
    # Per-segment dues when present in each chunk
    assert payload.tasks[0].due_at is not None
    assert payload.tasks[1].due_at is not None
    assert payload.tasks[0].due_at.date() != payload.tasks[1].due_at.date()


def test_stub_splits_numbered_list_into_two_drafts():
    provider = StubLLMProvider()
    now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    raw = provider.extract_tasks(
        "1. Submit proposal tomorrow\n2. Prepare slides next week",
        timezone="UTC",
        now=now,
    )
    payload = normalize_raw_extraction(raw, "UTC")
    assert len(payload.tasks) == 2
    assert "proposal" in payload.tasks[0].title.lower()
    assert "slides" in payload.tasks[1].title.lower()


def test_extraction_prompt_requires_multi_task_split():
    from nudge.llm.provider import EXTRACTION_SYSTEM_PROMPT

    assert "Hard triggers" in EXTRACTION_SYSTEM_PROMPT
    assert "and then" in EXTRACTION_SYSTEM_PROMPT
    assert "controls lab" in EXTRACTION_SYSTEM_PROMPT


def test_stub_splits_controls_lab_and_french_test():
    """User repro: part a + and then + two deadlines → 2 drafts."""
    from nudge.llm.provider import StubLLMProvider, expand_collapsed_extraction

    provider = StubLLMProvider()
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)  # Thursday
    text = (
        "Finish part a of the controls lab by sunday 2pm and then "
        "submit the French test by 11:59 same day"
    )
    raw = provider.extract_tasks(text, timezone="America/Toronto", now=now)
    payload = normalize_raw_extraction(raw, "America/Toronto")
    assert len(payload.tasks) == 2
    assert "part a" in payload.tasks[0].title.lower() or "controls" in payload.tasks[0].title.lower()
    assert "french" in payload.tasks[1].title.lower()
    assert payload.tasks[0].due_at is not None
    assert payload.tasks[1].due_at is not None
    assert payload.tasks[0].due_at.astimezone(ZoneInfo("America/Toronto")).hour == 14
    assert payload.tasks[1].due_at.astimezone(ZoneInfo("America/Toronto")).hour == 23
    assert payload.tasks[1].due_at.astimezone(ZoneInfo("America/Toronto")).minute == 59
    # Nov 1 2026 is DST fall-back Sunday → afternoon is EST (UTC-5)
    assert payload.tasks[0].due_at.utcoffset() == payload.tasks[0].due_at.astimezone(
        ZoneInfo("America/Toronto")
    ).utcoffset()
    assert payload.tasks[0].due_at.utcoffset().total_seconds() == -5 * 3600
    # Same calendar day
    d0 = payload.tasks[0].due_at.astimezone(ZoneInfo("America/Toronto")).date()
    d1 = payload.tasks[1].due_at.astimezone(ZoneInfo("America/Toronto")).date()
    assert d0 == d1

    # Post-process also repairs a collapsed OpenAI-style single draft
    collapsed = {
        "tasks": [
            {
                "title": "Finish lab and French test",
                "description": text,
                "priority": "p2",
                "due_at": "2026-11-01T14:00:00-04:00",
                "explicit_remind_at": None,
                "needs_clarification": False,
                "clarification_question": None,
            }
        ],
        "notes": "You mentioned two things.",
    }
    fixed = expand_collapsed_extraction(
        text, collapsed, timezone="America/Toronto", now=now
    )
    assert len(fixed["tasks"]) == 2
    assert "Split collapsed" in (fixed.get("notes") or "")


def test_normalize_fixes_stale_edt_offset_on_nov_dst_sunday():
    """14:00-04:00 on 2026-11-01 must become 14:00 EST (-05), not display as 1pm."""
    raw = {
        "tasks": [
            {
                "title": "Controls lab part a",
                "priority": "p2",
                "due_at": "2026-11-01T14:00:00-04:00",
                "explicit_remind_at": None,
            },
            {
                "title": "French test",
                "priority": "p2",
                "due_at": "2026-11-01T23:59:00-04:00",
                "explicit_remind_at": None,
            },
        ],
        "notes": None,
    }
    payload = normalize_raw_extraction(raw, "America/Toronto")
    d0 = payload.tasks[0].due_at
    d1 = payload.tasks[1].due_at
    assert d0 is not None and d1 is not None
    assert d0.hour == 14 and d0.utcoffset().total_seconds() == -5 * 3600
    assert d1.hour == 23 and d1.minute == 59
    assert d1.utcoffset().total_seconds() == -5 * 3600
    # Must not be the 1pm/10:59 skew from trusting -04 on a post-fall-back day
    assert d0.astimezone(ZoneInfo("America/Toronto")).hour == 14
    assert d1.astimezone(ZoneInfo("America/Toronto")).hour == 23


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
