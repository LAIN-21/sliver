"""Stage 4: exact duplicates (same SHA-256) and near duplicates of data already on Sliver.

Both are compared only against the seller's own datasets and datasets with a published
Resource, so another seller's private upload is never revealed through a finding.
"""

import hashlib
import logging

from sqlalchemy import and_, exists, or_, select

from ..models import Dataset, Resource
from .context import StageContext
from .table import StageResult, Table, count, finding, read_table

logger = logging.getLogger(__name__)

COLUMN_SIMILARITY = 0.8
MAX_CANDIDATES = 20
SAMPLE_ROWS = 1_000
NEAR_DUPLICATE = 0.9
OVERLAP = 0.5


def column_key(name: str) -> str:
    return name.strip().casefold()


def jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left | right else 0.0


def sample(rows: list, size: int = SAMPLE_ROWS) -> list:
    if len(rows) <= size:
        return rows
    step = len(rows) / size
    return [rows[int(index * step)] for index in range(size)]


def row_hashes(table: Table, columns: list[str]) -> list[str]:
    positions = {column_key(name): index for index, name in enumerate(table.header)}
    indexes = [positions[name] for name in columns]
    return [
        hashlib.sha256("\x1f".join(row[i].strip().casefold() for i in indexes).encode()).hexdigest()
        for row in table.rows
    ]


def overlap(upload: Table, other: Table) -> float:
    """Share of sampled rows found in the other table, in whichever direction is larger."""
    common = sorted(
        {column_key(name) for name in upload.header} & {column_key(name) for name in other.header}
    )
    if not common:
        return 0.0
    mine, theirs = row_hashes(upload, common), row_hashes(other, common)
    if not mine or not theirs:
        return 0.0
    mine_set, theirs_set = set(mine), set(theirs)
    forward = sum(value in theirs_set for value in sample(mine)) / min(len(mine), SAMPLE_ROWS)
    backward = sum(value in mine_set for value in sample(theirs)) / min(len(theirs), SAMPLE_ROWS)
    return max(forward, backward)


def describe(context: StageContext, other: Dataset, published_title: str | None) -> str:
    if other.owner_id == context.dataset.owner_id:
        return f"your dataset “{other.title}”"
    return f"the published catalog listing “{published_title}”"


def own_link(context: StageContext, other: Dataset) -> dict:
    """Findings link only to the seller's own datasets."""
    return {"matched_dataset": other.id} if other.owner_id == context.dataset.owner_id else {}


def published_title(context: StageContext, dataset_id: str) -> str | None:
    """The full-dataset listing's title (already public), if any part of the dataset is published."""
    return context.db.scalar(
        select(Resource.title)
        .where(Resource.dataset_id == dataset_id, Resource.status == "published")
        .order_by(Resource.slice_filter.is_not(None), Resource.title)
        .limit(1)
    )


def run(context: StageContext) -> StageResult:
    dataset = context.dataset
    is_published = exists().where(Resource.dataset_id == Dataset.id, Resource.status == "published")
    # Only the seller's own datasets and published ones: matching another seller's private upload
    # would reveal that it exists and would let whoever uploads a copy first block the owner.
    # Only earlier uploads count, so of two identical uploads the later one is the duplicate,
    # however the worker interleaves them.
    earlier = or_(
        Dataset.created_at < dataset.created_at,
        and_(Dataset.created_at == dataset.created_at, Dataset.id < dataset.id),
    )
    others = (
        earlier,
        Dataset.status != "rejected",
        or_(Dataset.owner_id == dataset.owner_id, is_published),
    )
    findings = []

    exact = context.db.scalars(select(Dataset).where(*others, Dataset.sha256 == dataset.sha256)).all()
    for other in exact:
        target = describe(context, other, published_title(context, other.id))
        findings.append(
            finding(
                "exact_duplicate",
                "high",
                f"This file is byte-for-byte identical to {target}.",
                **own_link(context, other),
            )
        )

    table = context.table
    mine = {column_key(name) for name in table.header}
    candidates = context.db.scalars(select(Dataset).where(*others, Dataset.sha256 != dataset.sha256)).all()
    scored = []
    for other in candidates:
        names = {column_key(column["name"]) for column in other.columns or []}
        similarity = jaccard(mine, names)
        if similarity >= COLUMN_SIMILARITY:
            scored.append((similarity, other))
    scored.sort(key=lambda item: item[0], reverse=True)

    compared = []
    for similarity, other in scored[:MAX_CANDIDATES]:
        try:
            other_table = read_table(context.store.get(other.object_key))
        except Exception:
            logger.warning("could not read dataset %s for duplicate comparison", other.id)
            continue
        share = overlap(table, other_table)
        compared.append({"columns": round(similarity, 2), "rows": round(share, 2)})
        if share < OVERLAP:
            continue
        near = share >= NEAR_DUPLICATE
        target = describe(context, other, published_title(context, other.id))
        findings.append(
            finding(
                "near_duplicate" if near else "row_overlap",
                "medium" if near else "low",
                f"{round(share * 100)}% of sampled rows also appear in {target} "
                f"({round(similarity * 100)}% of columns in common).",
                **own_link(context, other),
                row_overlap=round(share, 3),
                column_similarity=round(similarity, 3),
            )
        )

    if any(item["code"] == "exact_duplicate" for item in findings):
        summary = "Exact duplicate of data already on Sliver."
    elif findings:
        summary = f"Overlaps with {count(len(findings), 'existing dataset')}."
    else:
        checked = count(len(candidates), "dataset")
        summary = f"No duplicates found ({checked} checked, {len(compared)} compared row by row)."
    return StageResult(summary=summary, findings=findings, details={"comparisons": compared})
