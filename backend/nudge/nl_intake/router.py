from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from nudge.auth.deps import get_current_user
from nudge.core.db import get_db
from nudge.core.models import User
from nudge.nl_intake.schemas import (
    ConfirmRequest,
    ConfirmResponse,
    ExtractRequest,
    ExtractResponse,
    ProposalOut,
)
from nudge.nl_intake.service import (
    confirm_proposal,
    extract_and_store,
    get_proposal,
    reject_proposal,
)

router = APIRouter(prefix="/nl", tags=["nl-intake"])


@router.post("/extract", response_model=ExtractResponse)
def extract_tasks(
    body: ExtractRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExtractResponse:
    """LLM returns Pydantic-validated drafts only — nothing persisted to tasks yet."""
    try:
        return extract_and_store(
            db,
            user,
            body.text,
            timezone_override=body.timezone,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid extraction schema: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001 — surface provider failures cleanly
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM extraction failed: {exc}",
        ) from exc


@router.get("/proposals/{proposal_id}", response_model=ProposalOut)
def read_proposal(
    proposal_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProposalOut:
    proposal = get_proposal(db, user, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


@router.post("/proposals/{proposal_id}/confirm", response_model=ConfirmResponse)
def confirm(
    proposal_id: UUID,
    body: ConfirmRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConfirmResponse:
    """Explicit user confirm — creates tasks via task service with source=nl."""
    proposal = get_proposal(db, user, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    try:
        proposal, tasks = confirm_proposal(db, user, proposal, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ConfirmResponse(
        proposal=ProposalOut.model_validate(proposal),
        tasks=[t.model_dump(mode="json") for t in tasks],
    )


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalOut)
def reject(
    proposal_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProposalOut:
    proposal = get_proposal(db, user, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    try:
        proposal = reject_proposal(db, user, proposal)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return proposal
