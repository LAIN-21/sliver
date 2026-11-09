"""Persisted metadata. Dataset and Resource bytes stay private in object storage."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16))
    password_hash: Mapped[str | None] = mapped_column(Text)
    # Sellers receive x402 payments here directly; Sliver never holds funds.
    xrpl_address: Mapped[str | None] = mapped_column(String(35))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (CheckConstraint("role IN ('seller', 'reviewer')", name="users_role"),)


class Dataset(Base):
    """A private, immutable upload. Never serialized publicly."""

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    filename: Mapped[str] = mapped_column(String(200))
    object_key: Mapped[str] = mapped_column(String(200), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer)
    columns: Mapped[list] = mapped_column(JSONB)
    provenance: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(24), default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Resource(Base):
    """A purchasable view (a "sliver") over a dataset, stored as its own immutable object."""

    __tablename__ = "resources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(60), index=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(60)), default=list)
    columns: Mapped[list] = mapped_column(JSONB)
    column_names: Mapped[list[str]] = mapped_column(ARRAY(String(160)))
    row_count: Mapped[int] = mapped_column(Integer)
    coverage: Mapped[dict] = mapped_column(JSONB, default=dict)
    slice_filter: Mapped[dict | None] = mapped_column(JSONB)
    object_key: Mapped[str] = mapped_column(String(200), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    price_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    search_text: Mapped[str] = mapped_column(Text, default="")
    search_vector = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(description, '')), 'B') || "
            "setweight(to_tsvector('english', coalesce(search_text, '')), 'C')",
            persisted=True,
        ),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("price_minor > 0 AND price_minor <= 100000000", name="resources_price"),
        CheckConstraint("currency = 'USD'", name="resources_currency"),
        CheckConstraint("status IN ('draft', 'review', 'published', 'rejected')", name="resources_status"),
        Index("resources_search_vector", "search_vector", postgresql_using="gin"),
        Index("resources_column_names", "column_names", postgresql_using="gin"),
    )


class SearchEvent(Base):
    """Anonymous record of a catalog search; it carries no buyer identity."""

    __tablename__ = "search_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    query: Mapped[str] = mapped_column(String(300))
    normalized_query: Mapped[str] = mapped_column(String(300), index=True)
    filters: Mapped[dict] = mapped_column(JSONB, default=dict)
    result_count: Mapped[int] = mapped_column(Integer)
    top_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
