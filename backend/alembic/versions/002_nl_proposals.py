"""phase2 nl_proposals

Revision ID: 002_nl_proposals
Revises: 001_phase1
Create Date: 2026-10-28

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_nl_proposals"
down_revision: Union[str, None] = "001_phase1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN CREATE TYPE nl_proposal_status AS ENUM "
            "('pending', 'accepted', 'rejected'); "
            "EXCEPTION WHEN duplicate_object THEN null; END $$;"
        )
    )
    status_enum = postgresql.ENUM(
        "pending",
        "accepted",
        "rejected",
        name="nl_proposal_status",
        create_type=False,
    )

    op.create_table(
        "nl_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("proposed_draft", sa.JSON(), nullable=False),
        sa.Column("accepted_draft", sa.JSON(), nullable=True),
        sa.Column("status", status_enum, nullable=False),
        sa.Column("llm_provider", sa.String(64), nullable=False, server_default="stub"),
        sa.Column("created_task_ids", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_nl_proposals_user_status",
        "nl_proposals",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_nl_proposals_user_status", table_name="nl_proposals")
    op.drop_table("nl_proposals")
    op.execute(sa.text("DROP TYPE IF EXISTS nl_proposal_status"))
