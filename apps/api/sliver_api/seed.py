"""Load the demo catalog: `make seed` (python -m sliver_api.seed <datasets dir>).

Idempotent: accounts are matched by email and objects by deterministic keys, so re-running
neither duplicates rows nor rewrites stored bytes.
"""

import csv
import hashlib
import io
import logging
import sys
import tomllib
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from . import slicing
from .auth.service import apply_demo_passwords, normalize_email
from .models import Dataset, Resource, User, utcnow
from .slicing import describe, to_csv
from .storage import ObjectStore

logger = logging.getLogger("sliver_api.seed")


def store_object(store: ObjectStore, key: str, body: bytes) -> None:
    slicing.store_object(store, key, body, hint="; run `make dev-reset`")


def upsert_seller(db: Session, seller: dict) -> User:
    email = normalize_email(seller["email"])
    user = db.scalar(select(User).where(func.lower(User.email) == email).order_by(User.created_at).limit(1))
    if user is None:
        user = User(email=email, display_name=seller["display_name"], role="seller")
        db.add(user)
        db.flush()
    return user


def seed_dataset(db: Session, store: ObjectStore, folder: Path, spec: dict, owner: User) -> int:
    path = folder / spec["file"]
    raw = path.read_bytes()
    reader = csv.reader(io.StringIO(raw.decode("utf-8")))
    header = next(reader)
    rows = [row for row in reader if row]
    stem = path.stem
    dataset_key = f"datasets/seed/{stem}.csv"

    dataset = db.scalar(select(Dataset).where(Dataset.object_key == dataset_key))
    if dataset is not None and dataset.sha256 != hashlib.sha256(raw).hexdigest():
        # Datasets are immutable: new slices must never mix rows the stored dataset does not contain.
        raise RuntimeError(f"{path.name} changed since it was seeded; run `make dev-reset` and seed again")
    # Write (or restore, if the bucket lost it) the object; its hash was checked above.
    store_object(store, dataset_key, raw)
    if dataset is None:
        dataset = Dataset(
            owner_id=owner.id,
            title=spec["title"],
            filename=path.name,
            object_key=dataset_key,
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            row_count=len(rows),
            columns=describe(header, rows),
            provenance=spec["provenance"],
            status="accepted",
        )
        db.add(dataset)
        db.flush()

    column = spec.get("slice_by")
    period = spec.get("slice_period")
    created = 0
    for piece in slicing.plan(header, rows, column, period):
        object_key = f"resources/seed/{stem}/{piece.key}.csv"
        body = to_csv(header, piece.rows)
        existing_sha = db.scalar(select(Resource.sha256).where(Resource.object_key == object_key))
        if existing_sha is not None:
            if existing_sha != hashlib.sha256(body).hexdigest():
                message = f"{object_key} no longer matches its published hash; run `make dev-reset`"
                raise RuntimeError(message)
            store_object(store, object_key, body)  # restores the object if the bucket lost it
            continue
        store_object(store, object_key, body)
        db.add(
            Resource(
                dataset_id=dataset.id,
                owner_id=owner.id,
                title=slicing.piece_title(spec["title"], piece),
                description=slicing.piece_description(spec["description"], piece),
                category=spec["category"],
                tags=spec["tags"],
                columns=describe(header, piece.rows),
                column_names=[name.lower() for name in header],
                row_count=len(piece.rows),
                coverage=slicing.piece_coverage(header, piece, spec.get("time_column")),
                slice_filter=piece.filter,
                object_key=object_key,
                sha256=hashlib.sha256(body).hexdigest(),
                size_bytes=len(body),
                price_minor=spec["price_minor"] if piece.filter is None else spec["slice_price_minor"],
                status="published",
                published_at=utcnow(),
                search_text=slicing.search_text(spec["category"], spec["tags"], header, piece.label),
            )
        )
        created += 1
    return created


def seed(
    sessions: sessionmaker[Session],
    store: ObjectStore,
    folder: Path,
    passwords: tuple[str, str] | None = None,
) -> dict:
    """`passwords` is (seller, reviewer) for the demo accounts; empty strings disable sign-in."""
    manifest = tomllib.loads((folder / "manifest.toml").read_text(encoding="utf-8"))
    store.initialize()
    created = 0
    with sessions() as db:
        sellers = {seller["key"]: upsert_seller(db, seller) for seller in manifest["sellers"]}
        if passwords is not None:
            apply_demo_passwords(db, list(sellers.values()), *passwords)
        for spec in manifest["datasets"]:
            created += seed_dataset(db, store, folder, spec, sellers[spec["seller"]])
        db.commit()
        published = db.query(Resource).filter(Resource.status == "published").count()
    return {"created_resources": created, "published_resources": published}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from .config import get_settings
    from .db import make_engine, make_session_factory
    from .storage import S3Store

    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "/examples/datasets")
    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        passwords = (settings.sliver_seller_password, settings.sliver_reviewer_password)
        result = seed(make_session_factory(engine), S3Store(settings), folder, passwords)
    finally:
        engine.dispose()
    logger.info("seed complete: %s", result)


if __name__ == "__main__":
    main()
