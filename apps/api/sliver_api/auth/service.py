"""Sessions and demo accounts. Cookies carry a random token; only its SHA-256 is stored."""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import AuthSession, User, utcnow
from .passwords import hash_password, verify_password

COOKIE_NAME = "sliver_session"
REVIEWER_EMAIL = "reviewer@sliver.local"


def token_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def authenticate(db: Session, email: str, password: str) -> User | None:
    # Case-insensitive, so accounts stored before emails were normalized still sign in. Two
    # accounts differing only in case are ambiguous and neither signs in this way.
    matches = db.scalars(select(User).where(func.lower(User.email) == normalize_email(email)).limit(2)).all()
    user = matches[0] if len(matches) == 1 else None
    if not verify_password(password, user.password_hash if user else None):
        return None
    return user


def start_session(db: Session, user: User, ttl_hours: int) -> str:
    now = utcnow()
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(id=token_id(token), user_id=user.id, expires_at=now + timedelta(hours=ttl_hours)))
    db.commit()
    return token


def session_user(db: Session, token: str | None) -> User | None:
    if not token or len(token) > 128:
        return None
    row = db.execute(
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(AuthSession.id == token_id(token), AuthSession.expires_at > utcnow())
    ).first()
    return row[0] if row else None


def end_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(AuthSession).where(AuthSession.id == token_id(token)))
        db.commit()


def set_password(db: Session, user: User, password: str) -> None:
    """An empty password clears the hash, so the account cannot sign in (fails closed)."""
    if not password:
        if user.password_hash is not None:
            user.password_hash = None
            db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        return
    if not verify_password(password, user.password_hash):
        user.password_hash = hash_password(password)
        db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))


def apply_demo_passwords(
    db: Session, sellers: list[User], seller_password: str, reviewer_password: str
) -> None:
    """Give the demo sellers and the demo reviewer their passwords from the environment."""
    for seller in sellers:
        set_password(db, seller, seller_password)
    reviewer = db.scalar(select(User).where(User.email == REVIEWER_EMAIL))
    if reviewer is None:
        reviewer = User(email=REVIEWER_EMAIL, display_name="Sliver reviewer", role="reviewer")
        db.add(reviewer)
        db.flush()
    set_password(db, reviewer, reviewer_password)
