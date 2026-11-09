"""Seller pipeline: server-side sign-in sessions and per-dataset inspection steps.

Revision ID: 0004_seller_pipeline
Revises: 0003_payments
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_seller_pipeline"
down_revision: str | None = "0003_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )
    op.create_table(
        "pipeline_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.String(36),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'passed', 'warning', 'failed', 'skipped')",
            name="pipeline_steps_status",
        ),
        sa.UniqueConstraint("dataset_id", "stage", name="pipeline_steps_dataset_stage"),
    )


def downgrade() -> None:
    op.drop_table("pipeline_steps")
    op.drop_table("auth_sessions")
