"""Persisted metadata. Dataset bytes remain private in S3-compatible storage."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def identifier() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    # Stored as naive UTC consistently on PostgreSQL and the SQLite test adapter.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    role: Mapped[str] = mapped_column(String(16))
    password_hash: Mapped[str] = mapped_column(Text)
    __table_args__ = (CheckConstraint("role IN ('seller', 'reviewer')"),)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    filename: Mapped[str] = mapped_column(String(200))
    object_key: Mapped[str] = mapped_column(String(100), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer)
    columns: Mapped[list] = mapped_column(JSON)
    provenance: Mapped[dict] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Resource(Base):
    __tablename__ = "resources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    price_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (
        CheckConstraint("price_minor > 0 AND price_minor <= 100000000"),
        CheckConstraint("currency = 'USD'"),
        CheckConstraint("status IN ('draft', 'submitted', 'approved', 'rejected')"),
    )


class Quote(Base):
    """Immutable offer snapshot and one payment attempt; no wallet or signing keys."""

    __tablename__ = "quotes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    # Session deletion must revoke access without deleting payment/accounting evidence.
    owner_session_hash: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"))
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"))
    dataset_version: Mapped[int] = mapped_column(Integer, default=1)
    object_key: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(160))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    price_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    mode: Mapped[str] = mapped_column(String(16))
    network: Mapped[str] = mapped_column(String(16))
    amount_drops: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pay_to: Mapped[str | None] = mapped_column(String(35), nullable=True)
    buyer_address: Mapped[str | None] = mapped_column(String(35), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="quoted")
    # Unverified attempts must never reserve another buyer's public ledger proof.
    transaction_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    settled_transaction_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    receipt_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (
        CheckConstraint("dataset_version = 1"),
        CheckConstraint("currency = 'USD' AND price_minor > 0"),
        CheckConstraint("mode IN ('simulated', 'xrpl-testnet')"),
        CheckConstraint("status IN ('quoted', 'pending', 'paid', 'failed')"),
    )
