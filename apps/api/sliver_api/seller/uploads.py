"""Upload form validation and the immutable store-then-record step."""

import hashlib
import re
from datetime import date

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Dataset, PipelineStep, User, new_id, utcnow
from ..pipeline.jobs import enqueue
from ..pipeline.registry import STAGES_BY_NAME
from ..pipeline.table import MAX_FILE_BYTES
from ..storage import ObjectStore

# Datasets a reviewer may see: inspection finished cleanly (#14 adds the review itself).
REVIEW_STATUSES = ("review", "accepted")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
TRUE_VALUES = ("true", "on", "yes", "1")


class UploadForm(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    source: str = Field(min_length=3, max_length=300)
    method: str = Field(min_length=3, max_length=1000)
    collected_at: date
    rights_confirmed: bool
    rights_statement: str = Field(default="", max_length=1000)

    @field_validator("title", "source", "method", "rights_statement", mode="before")
    @classmethod
    def strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("collected_at", mode="before")
    @classmethod
    def iso_date(cls, value: object) -> date:
        # Parsed here so overflowing or odd inputs ("99999-01-01", "1e30") are a 422, never a 500.
        if not isinstance(value, str) or not ISO_DATE.fullmatch(value.strip()):
            raise ValueError("Use an ISO date such as 2026-11-01.")
        try:
            parsed = date.fromisoformat(value.strip())
        except (ValueError, OverflowError):
            raise ValueError("Use a real calendar date such as 2026-11-01.") from None
        if parsed.year < 1900 or parsed > date.today():
            raise ValueError("The collection date must be between 1900 and today.")
        return parsed

    @field_validator("rights_confirmed", mode="before")
    @classmethod
    def confirmed(cls, value: object) -> bool:
        if not (value is True or (isinstance(value, str) and value.strip().lower() in TRUE_VALUES)):
            raise ValueError("Confirm that you have the right to sell this data.")
        return True


def safe_filename(name: str | None) -> str:
    base = (name or "upload.csv").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip(" .") or "upload.csv"
    return cleaned[-200:]


def create_dataset(
    db: Session, store: ObjectStore, owner: User, form: UploadForm, filename: str | None, data: bytes
) -> Dataset:
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("too large")
    dataset_id = new_id()
    object_key = f"datasets/{owner.id}/{dataset_id}.csv"
    # Immutable: the key is new, and the store refuses to overwrite an existing object.
    store.put(object_key, data, content_type="text/csv")
    provenance = {
        "source": form.source,
        "method": form.method,
        "collected_at": form.collected_at.isoformat(),
        "rights_confirmed": True,
        "rights_confirmed_at": utcnow().isoformat().replace("+00:00", "Z"),
    }
    if form.rights_statement:
        provenance["rights_statement"] = form.rights_statement
    dataset = Dataset(
        id=dataset_id,
        owner_id=owner.id,
        title=form.title,
        filename=safe_filename(filename),
        object_key=object_key,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        row_count=0,
        columns=[],
        provenance=provenance,
        status="queued",
    )
    try:
        db.add(dataset)
        db.flush()
        enqueue(db, dataset)
        db.commit()
    except Exception:
        db.rollback()
        store.delete(object_key)  # nothing references it; do not leave an orphan
        raise
    return dataset


def visible_datasets(user: User):
    """Sellers see only their own uploads; reviewers only datasets that reached review."""
    query = select(Dataset)
    if user.role == "seller":
        return query.where(Dataset.owner_id == user.id)
    return query.where(Dataset.status.in_(REVIEW_STATUSES))


def iso(value) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def dataset_summary(dataset: Dataset, steps: list[PipelineStep]) -> dict:
    return {
        "id": dataset.id,
        "title": dataset.title,
        "filename": dataset.filename,
        "status": dataset.status,
        "sha256": dataset.sha256,
        "size_bytes": dataset.size_bytes,
        "row_count": dataset.row_count,
        "created_at": iso(dataset.created_at),
        "steps": [
            {
                "stage": step.stage,
                "label": STAGES_BY_NAME[step.stage].label if step.stage in STAGES_BY_NAME else step.stage,
                "status": step.status,
                "summary": (step.result or {}).get("summary") or step.error,
                "finding_count": len((step.result or {}).get("findings", [])),
            }
            for step in steps
        ],
    }


def dataset_detail(dataset: Dataset, steps: list[PipelineStep], owner: User) -> dict:
    detail = dataset_summary(dataset, steps)
    detail.update(
        columns=dataset.columns,
        provenance=dataset.provenance,
        seller={"name": owner.display_name},
    )
    for view, step in zip(detail["steps"], steps, strict=True):
        view.update(
            findings=(step.result or {}).get("findings", []),
            details=(step.result or {}).get("details", {}),
            error=step.error,
            attempts=step.attempts,
            started_at=iso(step.started_at),
            finished_at=iso(step.finished_at),
        )
    return detail
