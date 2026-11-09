"""Valuation and publication: public sample rows and a private valuation snapshot per Resource.

Revision ID: 0007_valuation
Revises: 0006_ai_review
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007_valuation"
down_revision: str | None = "0006_ai_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resources", sa.Column("sample_rows", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb"))
    )
    op.add_column("resources", sa.Column("valuation", JSONB()))


def downgrade() -> None:
    op.drop_column("resources", "valuation")
    op.drop_column("resources", "sample_rows")
