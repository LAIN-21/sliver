"""Record seller agreement acceptances.

Revision ID: 0010_seller_agreements
Revises: 0009_custom_slices
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_seller_agreements"
down_revision: str | None = "0009_custom_slices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "seller_agreement_acceptances",
        sa.Column("seller_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("version", sa.String(32), primary_key=True),
        sa.Column("content_sha256", sa.String(64), primary_key=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("seller_agreement_acceptances")
