"""Marketplace core: users, datasets, resources (slivers) and search events.

Revision ID: 0002_marketplace_core
Revises: 0001_baseline
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_marketplace_core"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEARCH_VECTOR = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(description, '')), 'B') || "
    "setweight(to_tsvector('english', coalesce(search_text, '')), 'C')"
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("password_hash", sa.Text()),
        sa.Column("xrpl_address", sa.String(35)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('seller', 'reviewer')", name="users_role"),
    )
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("object_key", sa.String(200), nullable=False, unique=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("columns", postgresql.JSONB(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "resources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_id", sa.String(36), sa.ForeignKey("datasets.id"), nullable=False, index=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(60), nullable=False, index=True),
        sa.Column("tags", postgresql.ARRAY(sa.String(60)), nullable=False),
        sa.Column("columns", postgresql.JSONB(), nullable=False),
        sa.Column("column_names", postgresql.ARRAY(sa.String(160)), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("coverage", postgresql.JSONB(), nullable=False),
        sa.Column("slice_filter", postgresql.JSONB()),
        sa.Column("object_key", sa.String(200), nullable=False, unique=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), sa.Computed(SEARCH_VECTOR, persisted=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("price_minor > 0 AND price_minor <= 100000000", name="resources_price"),
        sa.CheckConstraint("currency = 'USD'", name="resources_currency"),
        sa.CheckConstraint("status IN ('draft', 'review', 'published', 'rejected')", name="resources_status"),
    )
    op.create_index("resources_search_vector", "resources", ["search_vector"], postgresql_using="gin")
    op.create_index("resources_column_names", "resources", ["column_names"], postgresql_using="gin")
    op.create_table(
        "search_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("query", sa.String(300), nullable=False),
        sa.Column("normalized_query", sa.String(300), nullable=False, index=True),
        sa.Column("filters", postgresql.JSONB(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("top_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("search_events")
    op.drop_index("resources_column_names", table_name="resources")
    op.drop_index("resources_search_vector", table_name="resources")
    op.drop_table("resources")
    op.drop_table("datasets")
    op.drop_table("users")
