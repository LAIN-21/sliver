"""Activity events: the public, append-only log behind the live feed and purchase timelines.

Revision ID: 0005_activity_events
Revises: 0004_seller_pipeline
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_activity_events"
down_revision: str | None = "0004_seller_pipeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activity_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(32), nullable=False),
        # No foreign key on purpose: see ActivityEvent in sliver_api/models.py.
        sa.Column("payment_id", sa.String(36), nullable=False, index=True),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("amount", sa.String(32), nullable=False),
        sa.Column("asset", sa.String(40), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("network", sa.String(16), nullable=False),
        sa.Column("pay_to", sa.String(35), nullable=False),
        sa.Column("payer", sa.String(35)),
        sa.Column("tx_hash", sa.String(64)),
        sa.Column("ledger_index", sa.Integer()),
        sa.Column("ledger_closed_at", sa.DateTime(timezone=True)),
        sa.Column("detail", sa.String(200)),
        sa.Column("agent_note", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("activity_events")
