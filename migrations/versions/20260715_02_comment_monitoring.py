"""Add durable comment monitoring records and retry state."""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_02"
down_revision: str | None = "20260715_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monitored_contents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform_content_id", sa.String(128), nullable=False),
        sa.Column("display_type", sa.String(32), nullable=False),
        sa.Column("comment_oid", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(256), nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("platform_content_id", name="uq_content_platform_id"),
    )
    op.create_table(
        "monitor_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("checkpoint_key", sa.String(192), nullable=False, unique=True),
        sa.Column("cursor_value", sa.String(512), nullable=True),
        sa.Column("state_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("priority", sa.String(16), nullable=False, server_default="normal"),
    )
    op.add_column("events", sa.Column("monitored_content_id", sa.Integer(), nullable=True))
    op.add_column(
        "events",
        sa.Column("processing_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "events", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("events", sa.Column("last_error_code", sa.String(64), nullable=True))
    op.add_column(
        "drafts",
        sa.Column("safety_reasons_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "drafts", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "publish_jobs",
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
    )
    op.add_column(
        "publish_jobs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "publish_jobs", sa.Column("last_error_code", sa.String(64), nullable=True)
    )
    op.add_column(
        "publish_jobs", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("publish_jobs", "completed_at")
    op.drop_column("publish_jobs", "last_error_code")
    op.drop_column("publish_jobs", "next_attempt_at")
    op.drop_column("publish_jobs", "source")
    op.drop_column("drafts", "updated_at")
    op.drop_column("drafts", "safety_reasons_json")
    op.drop_column("events", "last_error_code")
    op.drop_column("events", "next_attempt_at")
    op.drop_column("events", "processing_attempts")
    op.drop_column("events", "monitored_content_id")
    op.drop_column("events", "priority")
    op.drop_table("monitor_checkpoints")
    op.drop_table("monitored_contents")
