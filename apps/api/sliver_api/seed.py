"""Load the demo catalog: `make seed` (python -m sliver_api.seed <datasets dir>).

Idempotent: accounts are matched by email and objects by deterministic keys, so re-running
neither duplicates rows nor rewrites stored bytes.
"""

import csv
import hashlib
import io
import logging
import re
import sys
import tomllib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .models import Dataset, Resource, User, utcnow
from .storage import ObjectExistsError, ObjectStore

logger = logging.getLogger("sliver_api.seed")

MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def infer_type(values: list[str]) -> str:
    present = [value for value in values if value.strip()]
    if not present:
        return "text"
    for kind, pattern in (
        ("integer", r"-?\d+"),
        ("decimal", r"-?\d+(\.\d+)?"),
        ("date", r"\d{4}-\d{2}-\d{2}"),
        ("month", r"\d{4}-\d{2}"),
    ):
        if all(re.fullmatch(pattern, value) for value in present):
            return kind
    return "text"


def to_csv(header: list[str], rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def month_label(value: str) -> str:
    year, month = value[:7].split("-")
    return f"{MONTHS[int(month) - 1]} {year}"


def describe(header: list[str], rows: list[list[str]]) -> list[dict]:
    return [{"name": name, "type": infer_type([row[i] for row in rows])} for i, name in enumerate(header)]


def coverage(header: list[str], rows: list[list[str]], time_column: str | None) -> dict:
    result: dict = {}
    if time_column and time_column in header:
        index = header.index(time_column)
        values = sorted(row[index] for row in rows if row[index])
        if values:
            result["time"] = {"column": time_column, "start": values[0], "end": values[-1]}
    return result


def store_object(store: ObjectStore, key: str, body: bytes) -> None:
    try:
        store.put(key, body)
    except ObjectExistsError:
        if hashlib.sha256(store.get(key)).hexdigest() != hashlib.sha256(body).hexdigest():
            message = f"stored object {key} differs from the seed data; run `make dev-reset`"
            raise RuntimeError(message) from None


def upsert_seller(db: Session, seller: dict) -> User:
    user = db.scalar(select(User).where(User.email == seller["email"]))
    if user is None:
        user = User(email=seller["email"], display_name=seller["display_name"], role="seller")
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
    if dataset is None:
        store_object(store, dataset_key, raw)
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

    slices: list[tuple[str, str, dict | None, list[list[str]], int]] = [
        ("full", "full dataset", None, rows, spec["price_minor"])
    ]
    column = spec.get("slice_by")
    if column:
        index = header.index(column)
        by_month = spec.get("slice_period") == "month"
        groups: dict[str, list[list[str]]] = {}
        for row in rows:
            groups.setdefault(row[index][:7] if by_month else row[index], []).append(row)
        for value, group in sorted(groups.items()):
            label = month_label(value) if by_month else value
            slice_filter = {"column": column, "period": "month" if by_month else None, "value": value}
            slices.append((slug(label), label, slice_filter, group, spec["slice_price_minor"]))

    created = 0
    for key_part, label, slice_filter, group, price in slices:
        object_key = f"resources/seed/{stem}/{key_part}.csv"
        if db.scalar(select(Resource.id).where(Resource.object_key == object_key)):
            continue
        body = to_csv(header, group)
        store_object(store, object_key, body)
        resource_coverage = coverage(header, group, spec.get("time_column"))
        if slice_filter:
            resource_coverage["slice"] = {"column": column, "value": label}
        title = spec["title"] if slice_filter is None else f"{spec['title']}: {label}"
        description = spec["description"]
        if slice_filter:
            description += f" This sliver covers {label} only."
        db.add(
            Resource(
                dataset_id=dataset.id,
                owner_id=owner.id,
                title=title,
                description=description,
                category=spec["category"],
                tags=spec["tags"],
                columns=describe(header, group),
                column_names=[name.lower() for name in header],
                row_count=len(group),
                coverage=resource_coverage,
                slice_filter=slice_filter,
                object_key=object_key,
                sha256=hashlib.sha256(body).hexdigest(),
                size_bytes=len(body),
                price_minor=price,
                status="published",
                published_at=utcnow(),
                search_text=" ".join([spec["category"], *spec["tags"], *header, label]),
            )
        )
        created += 1
    return created


def seed(sessions: sessionmaker[Session], store: ObjectStore, folder: Path) -> dict:
    manifest = tomllib.loads((folder / "manifest.toml").read_text(encoding="utf-8"))
    store.initialize()
    created = 0
    with sessions() as db:
        sellers = {seller["key"]: upsert_seller(db, seller) for seller in manifest["sellers"]}
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
        result = seed(make_session_factory(engine), S3Store(settings), folder)
    finally:
        engine.dispose()
    logger.info("seed complete: %s", result)


if __name__ == "__main__":
    main()
