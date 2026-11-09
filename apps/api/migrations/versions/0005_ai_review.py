"""AI review and acceptance: a reviewer's decision and reason on each dataset.

Revision ID: 0005_ai_review
Revises: 0004_seller_pipeline
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_ai_review"
down_revision: str | None = "0004_seller_pipeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("reviewed_by", sa.String(36), sa.ForeignKey("users.id")))
    op.add_column("datasets", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.add_column("datasets", sa.Column("review_reason", sa.Text()))


def downgrade() -> None:
    op.drop_column("datasets", "review_reason")
    op.drop_column("datasets", "reviewed_at")
    op.drop_column("datasets", "reviewed_by")
