"""x402 payments: one invoice per 402 challenge, settled at most once.

Revision ID: 0003_payments
Revises: 0002_marketplace_core
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_payments"
down_revision: str | None = "0002_marketplace_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("invoice_id", sa.String(64), nullable=False, unique=True),
        sa.Column("resource_id", sa.String(36), sa.ForeignKey("resources.id"), nullable=False, index=True),
        sa.Column("pay_to", sa.String(35), nullable=False),
        sa.Column("amount", sa.String(32), nullable=False),
        sa.Column("asset", sa.String(40), nullable=False),
        sa.Column("network", sa.String(16), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("requirements", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("tx_hash", sa.String(64), unique=True),
        sa.Column("payer", sa.String(35)),
        sa.Column("ledger_index", sa.Integer()),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('required', 'settling', 'delivered', 'failed')", name="payments_status"
        ),
    )


def downgrade() -> None:
    op.drop_table("payments")
