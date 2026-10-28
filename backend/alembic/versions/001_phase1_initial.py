"""phase1 initial schema

Revision ID: 001_phase1
Revises:
Create Date: 2026-10-28

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_phase1"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENUMS = {
    "task_status": ("todo", "in_progress", "done", "cancelled"),
    "task_priority": ("p0", "p1", "p2", "p3"),
    "task_source": ("manual", "nl"),
    "decision_action": ("send", "skip", "digest", "defer"),
    "notification_channel": ("email", "in_app"),
    "notification_status": ("pending", "sent", "failed", "skipped"),
}


def _ensure_enums() -> dict[str, postgresql.ENUM]:
    bind = op.get_bind()
    created: dict[str, postgresql.ENUM] = {}
    for name, values in ENUMS.items():
        enum = postgresql.ENUM(*values, name=name, create_type=False)
        # Idempotent create for partial/re-run local DBs
        op.execute(
            sa.text(
                f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({', '.join(repr(v) for v in values)}); "
                f"EXCEPTION WHEN duplicate_object THEN null; END $$;"
            )
        )
        enum.create(bind, checkfirst=True)
        created[name] = enum
    return created


def upgrade() -> None:
    enums = _ensure_enums()

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", enums["task_status"], nullable=False),
        sa.Column("priority", enums["task_priority"], nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", enums["task_source"], nullable=False),
        sa.Column("explicit_remind_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("force_within_quiet", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tasks_user_due", "tasks", ["user_id", "due_at"])
    op.create_index("ix_tasks_user_status", "tasks", ["user_id", "status"])

    op.create_table(
        "reminder_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("quiet_start", sa.Time(), nullable=False),
        sa.Column("quiet_end", sa.Time(), nullable=False),
        sa.Column("channels", sa.JSON(), nullable=False),
        sa.Column("digest_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("digest_time", sa.Time(), nullable=False),
        sa.Column("min_score_threshold", sa.Float(), nullable=False, server_default="0.45"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "reminder_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("action", enums["decision_action"], nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("weights_version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("guaranteed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("idempotency_key", name="uq_reminder_decisions_idem"),
    )

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", enums["notification_channel"], nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", enums["notification_status"], nullable=False),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column(
            "related_decision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reminder_decisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "in_app_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "related_decision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reminder_decisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_in_app_notifications_user_id", "in_app_notifications", ["user_id"])

    op.create_table(
        "daily_notify_counts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "day", name="uq_daily_notify_user_day"),
    )


def downgrade() -> None:
    op.drop_table("daily_notify_counts")
    op.drop_index("ix_in_app_notifications_user_id", table_name="in_app_notifications")
    op.drop_table("in_app_notifications")
    op.drop_table("notifications")
    op.drop_table("reminder_decisions")
    op.drop_table("reminder_preferences")
    op.drop_index("ix_tasks_user_status", table_name="tasks")
    op.drop_index("ix_tasks_user_due", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    for name in ENUMS:
        op.execute(sa.text(f"DROP TYPE IF EXISTS {name}"))
