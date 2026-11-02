"""Explicit local-demo schema bootstrap and account creation; never runs on startup."""

import os

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from .config import Settings
from .models import Base, User
from .security import hash_password
from .storage import S3Store

DEMO_ACCOUNTS = (
    ("seller-a@sliver.local", "seller", "SLIVER_SELLER_A_PASSWORD"),
    ("seller-b@sliver.local", "seller", "SLIVER_SELLER_B_PASSWORD"),
    ("reviewer@sliver.local", "reviewer", "SLIVER_REVIEWER_PASSWORD"),
)


def seed_accounts(engine, passwords: dict[str, str]) -> None:
    for _email, _role, key in DEMO_ACCOUNTS:
        password = passwords.get(key, "")
        if len(password) < 12 or len(password) > 256:
            raise RuntimeError(f"Set {key} to a local demo password between 12 and 256 characters.")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for email, role, key in DEMO_ACCOUNTS:
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                db.add(User(email=email, role=role, password_hash=hash_password(passwords[key])))
            # Repeat seeding preserves existing accounts and their passwords/sessions.
        db.commit()


def main():
    settings = Settings.from_env()
    passwords = {key: os.environ.get(key, "") for _email, _role, key in DEMO_ACCOUNTS}
    # Validate supplied credentials before creating any infrastructure state.
    for key, password in passwords.items():
        if not 12 <= len(password) <= 256:
            raise RuntimeError(f"Set {key} to a local demo password between 12 and 256 characters.")
    store = S3Store(settings)
    store.initialize()
    engine = create_engine(settings.database_url)
    try:
        seed_accounts(engine, passwords)
    finally:
        engine.dispose()
    print("Local demo schema and three accounts are ready. Existing passwords are preserved.")


if __name__ == "__main__":
    main()
