"""Buyer-defined custom slices: unlisted derived Resources and a per-dataset seller toggle (#39).

Revision ID: 0009_custom_slices
Revises: 0008_platform_fee
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0009_custom_slices"
down_revision: str | None = "0008_platform_fee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column("allow_custom_slices", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column("resources", sa.Column("parent_id", sa.String(36), sa.ForeignKey("resources.id")))
    op.add_column("resources", sa.Column("custom_key", sa.String(64)))
    op.add_column("resources", sa.Column("custom_filter", JSONB()))
    op.create_index("ix_resources_parent_id", "resources", ["parent_id"])
    op.create_unique_constraint("resources_custom_key_key", "resources", ["custom_key"])


def downgrade() -> None:
    op.drop_constraint("resources_custom_key_key", "resources", type_="unique")
    op.drop_index("ix_resources_parent_id", table_name="resources")
    op.drop_column("resources", "custom_filter")
    op.drop_column("resources", "custom_key")
    op.drop_column("resources", "parent_id")
    op.drop_column("datasets", "allow_custom_slices")
