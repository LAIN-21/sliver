"""Buyer-defined custom slices (#39).

A buyer's agent asks for exactly the rows it needs from a published full-dataset Resource: a time
range on the dataset's time column and/or equality on its slice column or another low-cardinality,
non-personal text column. Sliver cuts those rows from the parent's stored object (SHA-256
checked), prices them with `valuation.custom_slice_price` and stores them as a derived Resource:
published, so the unchanged x402 path (`GET /api/resources/{id}/data`) sells it, with whatever
payee and fee rules that path applies, and the sale counts for the same seller, but unlisted, so
it never appears in search, categories, demand or the x402 directory.

What may be filtered follows the leak rules the pipeline already applies to public text
(`pipeline/leakguard.py`): the time column only when the privacy scan did not flag it, and
equality only on category columns whose values may be public anyway. Columns the privacy scan
flagged (in the pipeline's findings or by a fresh scan of the stored rows) are never filterable,
so a filter can never select rows by personal data. A quote reveals counts, coverage, the price
and the SHA-256, never row values.

Identical requests find the same Resource: its key is the SHA-256 of the parent id and the
normalized filter, and two filters that select the same bytes share one Resource too.
"""

import calendar
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import slicing, valuation
from ..models import Dataset, PipelineStep, Resource, is_full_dataset, utcnow
from ..pipeline.leakguard import TEMPORAL, flagged_columns, is_categorical
from ..pipeline.privacy import scan_column
from ..pipeline.profile import profile_column
from ..pipeline.table import Table, read_table
from ..storage import ObjectStore

logger = logging.getLogger(__name__)

# Smaller results are refused: a custom slice is a slice of a dataset, not a row lookup.
MIN_ROWS = 5
# Stored derived objects per parent; past this, buyers are pointed at existing slices.
MAX_PER_PARENT = 50
MAX_WHERE = 3
MAX_VALUE_CHARS = 120
SNAPSHOT_VERSION = 1
BOUND = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


class Refused(Exception):
    """A quote Sliver will not make. `extra` holds public hints (ids, filterable columns)."""

    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


@dataclass(frozen=True)
class Schema:
    """What a buyer may filter on, derived from the parent's own rows and the privacy findings."""

    time_column: str | None
    time_type: str | None
    time_start: str | None
    time_end: str | None
    where_columns: tuple[str, ...]

    def public(self) -> dict:
        time = (
            {"column": self.time_column, "start": self.time_start, "end": self.time_end}
            if self.time_column
            else None
        )
        return {"time": time, "where": list(self.where_columns), "min_rows": MIN_ROWS}


@dataclass(frozen=True)
class SliceFilter:
    time_column: str | None
    start: date | None
    end: date | None
    where: tuple[tuple[str, str], ...]

    def to_json(self) -> dict:
        result: dict = {}
        if self.time_column:
            result["time"] = {
                "column": self.time_column,
                "start": self.start.isoformat() if self.start else None,
                "end": self.end.isoformat() if self.end else None,
            }
        if self.where:
            result["where"] = dict(self.where)
        return result

    def key(self, parent_id: str) -> str:
        canonical = json.dumps({"parent": parent_id, "filter": self.to_json()}, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def label(self) -> str:
        parts = []
        if self.time_column:
            if self.start and self.end:
                parts.append(f"{self.time_column} {self.start.isoformat()} to {self.end.isoformat()}")
            elif self.start:
                parts.append(f"{self.time_column} from {self.start.isoformat()}")
            else:
                parts.append(f"{self.time_column} until {self.end.isoformat()}")  # type: ignore[union-attr]
        parts.extend(f"{column} {value}" for column, value in self.where)
        return ", ".join(parts)


# --- the schema and the filter --------------------------------------------------------------


def build_schema(table: Table, flagged: set[str], slice_column: str | None) -> Schema:
    profile = [profile_column(name, table.column(index)) for index, name in enumerate(table.header)]
    # The same time column the profile stage reports, and only when it may be public.
    time = next((column for column in profile if column["type"] in TEMPORAL and "min" in column), None)
    if time is not None and time["name"] in flagged:
        time = None
    rows = len(table.rows)
    where = tuple(
        column["name"]
        for column in profile
        if is_categorical(column, rows, flagged)
        and (column["type"] == "text" or column["name"] == slice_column)
    )
    return Schema(
        time_column=time["name"] if time else None,
        time_type=time["type"] if time else None,
        time_start=time["min"] if time else None,
        time_end=time["max"] if time else None,
        where_columns=where,
    )


def parse_bound(value: str, *, end: bool) -> date:
    """YYYY, YYYY-MM or YYYY-MM-DD; partial dates expand to their first (or last) day."""
    if not BOUND.match(value):
        raise ValueError(value)
    parts = [int(part) for part in value.split("-")]
    if len(parts) == 1:
        return date(parts[0], 12, 31) if end else date(parts[0], 1, 1)
    if len(parts) == 2:
        year, month = parts
        return date(year, month, calendar.monthrange(year, month)[1] if end else 1)
    return date(*parts)


def normalize(
    schema: Schema, time_start: str | None, time_end: str | None, where: dict[str, str] | None
) -> SliceFilter:
    filterable = schema.public()
    time_start = (time_start or "").strip() or None
    time_end = (time_end or "").strip() or None
    where = where or {}
    if not (time_start or time_end or where):
        raise Refused(
            422, "empty_filter", "Give a time range and/or equality conditions.", filterable=filterable
        )
    start = end = None
    if time_start or time_end:
        if not schema.time_column:
            raise Refused(
                422, "no_time_column", "This dataset has no filterable time column.", filterable=filterable
            )
        try:
            start = parse_bound(time_start, end=False) if time_start else None
            end = parse_bound(time_end, end=True) if time_end else None
        except ValueError:
            raise Refused(
                422,
                "invalid_time",
                "time_start and time_end must be YYYY, YYYY-MM or YYYY-MM-DD.",
                filterable=filterable,
            ) from None
        if start and end and start > end:
            raise Refused(422, "invalid_time", "time_start is after time_end.", filterable=filterable)
    if len(where) > MAX_WHERE:
        raise Refused(
            422, "too_many_conditions", f"At most {MAX_WHERE} equality conditions.", filterable=filterable
        )
    conditions = []
    for column, value in where.items():
        if column not in schema.where_columns:
            raise Refused(
                422,
                "not_filterable",
                f"Column “{str(column)[:160]}” cannot be filtered.",
                filterable=filterable,
            )
        text = value.strip() if isinstance(value, str) else ""
        if not text or len(text) > MAX_VALUE_CHARS:
            raise Refused(
                422,
                "invalid_value",
                f"Each value must be text of 1 to {MAX_VALUE_CHARS} characters.",
                filterable=filterable,
            )
        conditions.append((column, text))
    return SliceFilter(
        time_column=schema.time_column if (start or end) else None,
        start=start,
        end=end,
        where=tuple(sorted(conditions)),
    )


def row_span(cell: str, kind: str | None) -> tuple[date, date] | None:
    try:
        if kind == "month":
            first = parse_bound(cell[:7], end=False)
            return first, parse_bound(cell[:7], end=True)
        day = date.fromisoformat(cell[:10])
        return day, day
    except ValueError:
        return None


def cut(table: Table, schema: Schema, chosen: SliceFilter) -> list[list[str]]:
    """The rows matching every condition, in their original order. A month row counts only when
    the whole month is inside the requested range."""
    conditions = [(table.header.index(column), value) for column, value in chosen.where]
    time_index = table.header.index(chosen.time_column) if chosen.time_column else None
    rows = []
    for row in table.rows:
        if any(row[index].strip() != value for index, value in conditions):
            continue
        if time_index is not None:
            span = row_span(row[time_index].strip(), schema.time_type)
            if span is None:
                continue
            if (chosen.start and span[0] < chosen.start) or (chosen.end and span[1] > chosen.end):
                continue
        rows.append(row)
    return rows


# --- the quote ------------------------------------------------------------------------------


def privacy_flagged(db: Session, dataset_id: str, table: Table) -> set[str]:
    """Columns the pipeline's privacy stage flagged, plus any a fresh scan of these rows flags
    (seeded datasets never ran the pipeline)."""
    step = db.scalar(
        select(PipelineStep).where(PipelineStep.dataset_id == dataset_id, PipelineStep.stage == "privacy")
    )
    flagged = flagged_columns(list(((step.result or {}).get("findings") or []) if step else []))
    flagged.update(name for index, name in enumerate(table.header) if scan_column(table.column(index)))
    return flagged


def slice_column(siblings: list[Resource]) -> str | None:
    for sibling in siblings:
        if sibling.slice_filter and sibling.slice_filter.get("period") != "month":
            return sibling.slice_filter.get("column")
    return None


def read_parent(store: ObjectStore, parent: Resource) -> Table:
    try:
        data = store.get(parent.object_key)
    except Exception:
        logger.warning("could not read resource %s for a custom slice", parent.id)
        raise Refused(503, "storage_unavailable", "The data is temporarily unavailable.") from None
    if hashlib.sha256(data).hexdigest() != parent.sha256:
        logger.error("integrity check failed for resource %s", parent.id)
        raise Refused(503, "integrity_check_failed", "The stored data failed its integrity check.")
    return read_table(data)


def checked_parent(db: Session, resource_id: str) -> tuple[Resource, Dataset]:
    """The full-dataset Resource to cut from, locked so quotes for one parent run one at a time."""
    parent = db.scalar(select(Resource).where(Resource.id == resource_id).with_for_update())
    if parent is None or parent.status != "published":
        raise Refused(404, "not_found", "Resource not found.")
    if parent.parent_id is not None:
        raise Refused(
            409,
            "use_full_dataset",
            "Custom slices are cut from the full dataset.",
            full_dataset_id=parent.parent_id,
        )
    if parent.slice_filter is not None:
        full = db.scalar(
            select(Resource.id).where(
                Resource.dataset_id == parent.dataset_id,
                is_full_dataset(),
                Resource.parent_id.is_(None),
                Resource.status == "published",
            )
        )
        raise Refused(
            409, "use_full_dataset", "Custom slices are cut from the full dataset.", full_dataset_id=full
        )
    dataset = db.get(Dataset, parent.dataset_id)
    if dataset is None or dataset.status != "published":
        raise Refused(409, "not_published", "This dataset is not published.")
    if not dataset.allow_custom_slices:
        raise Refused(
            409, "custom_slices_disabled", "The seller does not offer custom slices of this dataset."
        )
    # Who is paid, and whether a sale is possible right now, is the payment path's decision.
    return parent, dataset


def quote(
    db: Session,
    store: ObjectStore,
    resource_id: str,
    *,
    time_start: str | None = None,
    time_end: str | None = None,
    where: dict[str, str] | None = None,
) -> tuple[Resource, Resource, bool]:
    """(custom slice, parent, created). Raises `Refused`; the caller rolls back."""
    parent, dataset = checked_parent(db, resource_id)
    siblings = list(
        db.scalars(
            select(Resource).where(
                Resource.dataset_id == parent.dataset_id,
                Resource.parent_id.is_(None),
                Resource.status == "published",
            )
        )
    )
    table = read_parent(store, parent)
    flagged = privacy_flagged(db, dataset.id, table)
    schema = build_schema(table, flagged, slice_column(siblings))
    chosen = normalize(schema, time_start, time_end, where)

    key = chosen.key(parent.id)
    existing = db.scalar(select(Resource).where(Resource.custom_key == key))
    if existing is not None:
        return existing, parent, False

    rows = cut(table, schema, chosen)
    if len(rows) < MIN_ROWS:
        raise Refused(
            422,
            "too_few_rows",
            f"Fewer than {MIN_ROWS} rows match; custom slices need at least {MIN_ROWS}.",
            filterable=schema.public(),
        )
    body = slicing.to_csv(table.header, rows)
    sha256 = hashlib.sha256(body).hexdigest()
    for sibling in siblings:
        if sibling.sha256 == sha256:
            code = "equals_full_dataset" if sibling.id == parent.id else "equals_sliver"
            what = "the full dataset" if sibling.id == parent.id else "an existing sliver"
            raise Refused(
                409, code, f"These rows are exactly {what}; buy it instead.", resource_id=sibling.id
            )
    same_bytes = db.scalar(select(Resource).where(Resource.parent_id == parent.id, Resource.sha256 == sha256))
    if same_bytes is not None:
        return same_bytes, parent, False
    stored = db.scalar(select(func.count()).select_from(Resource).where(Resource.parent_id == parent.id)) or 0
    if stored >= MAX_PER_PARENT:
        raise Refused(
            409,
            "custom_slice_limit",
            f"This dataset already has {MAX_PER_PARENT} custom slices; "
            "buy an existing sliver or the full dataset.",
        )

    price = valuation.custom_slice_price(parent.price_minor, parent.row_count, len(rows))
    snapshot = parent.valuation or {}
    price["parent_suggested_minor"] = (snapshot.get("valuation") or {}).get("suggested_price_minor")
    price["parent_accepted_suggestion"] = snapshot.get("accepted_suggestion")
    time_column = ((parent.coverage or {}).get("time") or {}).get("column")
    coverage = slicing.coverage(table.header, rows, time_column if time_column in table.header else None)
    if len(chosen.where) == 1:
        coverage["slice"] = {"column": chosen.where[0][0], "value": chosen.where[0][1]}
    label = chosen.label()
    object_key = f"resources/{dataset.owner_id}/{dataset.id}/custom/{key}.csv"
    slicing.store_object(store, object_key, body)
    now = utcnow()
    resource = Resource(
        dataset_id=dataset.id,
        owner_id=dataset.owner_id,
        parent_id=parent.id,
        custom_key=key,
        custom_filter=chosen.to_json(),
        title=f"{parent.title}: custom slice ({label})"[:160],
        description=f"{parent.description} Custom slice for a buyer: {label}; {len(rows):,} rows.",
        category=parent.category,
        tags=list(parent.tags),
        columns=slicing.describe(table.header, rows),
        column_names=list(parent.column_names),
        row_count=len(rows),
        coverage=coverage,
        object_key=object_key,
        sha256=sha256,
        size_bytes=len(body),
        price_minor=price["price_minor"],
        status="published",
        published_at=now,
        search_text="",
        valuation={
            "version": SNAPSHOT_VERSION,
            "computed_at": now.isoformat().replace("+00:00", "Z"),
            "custom_slice": price,
            "price_minor": price["price_minor"],
        },
    )
    db.add(resource)
    db.flush()
    return resource, parent, True


def price_breakdown(resource: Resource) -> dict:
    return dict((resource.valuation or {}).get("custom_slice") or {})
