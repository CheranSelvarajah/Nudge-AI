from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

from nudge.auth.deps import get_current_user
from nudge.core.db import get_db
from nudge.core.models import NlProposalStatus, TaskPriority, User
from nudge.main import app
from nudge.nl_intake.schemas import ExtractResponse, TaskDraft

client = TestClient(app)


def _fake_user() -> User:
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.email = "tester@example.com"
    user.timezone = "America/Toronto"
    user.preferences = None
    return user


def test_extract_requires_auth():
    res = client.post("/api/nl/extract", json={"text": "Buy milk tomorrow"})
    assert res.status_code == 401


def test_extract_endpoint_returns_drafts_without_creating_tasks(monkeypatch):
    user = _fake_user()
    proposal_id = uuid4()

    def fake_extract(db, u, text, timezone_override=None, provider=None, now=None):
        assert u is user
        assert "milk" in text
        return ExtractResponse(
            proposal_id=proposal_id,
            status=NlProposalStatus.pending,
            source_text=text,
            drafts=[
                TaskDraft(
                    title="Buy milk",
                    description=None,
                    priority=TaskPriority.p2,
                    due_at=datetime(2026, 10, 29, 17, 0, tzinfo=timezone.utc),
                )
            ],
            notes="ok",
            llm_provider="stub",
            needs_clarification=False,
            clarification_questions=[],
        )

    monkeypatch.setattr("nudge.nl_intake.router.extract_and_store", fake_extract)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        res = client.post("/api/nl/extract", json={"text": "Buy milk tomorrow"})
        assert res.status_code == 200
        body = res.json()
        assert body["proposal_id"] == str(proposal_id)
        assert body["drafts"][0]["title"] == "Buy milk"
        assert body["llm_provider"] == "stub"
        assert body["status"] == "pending"
    finally:
        app.dependency_overrides.clear()


def test_confirm_conflict_when_not_pending(monkeypatch):
    user = _fake_user()
    proposal = MagicMock()
    proposal.status = NlProposalStatus.accepted
    proposal.id = uuid4()

    monkeypatch.setattr(
        "nudge.nl_intake.router.get_proposal",
        lambda db, u, pid: proposal,
    )

    def boom(*_a, **_k):
        raise ValueError("Proposal is no longer pending")

    monkeypatch.setattr("nudge.nl_intake.router.confirm_proposal", boom)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        res = client.post(
            f"/api/nl/proposals/{proposal.id}/confirm",
            json={"drafts": [{"title": "X", "priority": "p2"}]},
        )
        assert res.status_code == 409
    finally:
        app.dependency_overrides.clear()
