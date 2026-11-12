from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from ..auth.deps import CurrentReviewer, CurrentSeller, CurrentUser
from ..deps import DB
from ..models import Dataset, PipelineStep, Resource, User, utcnow
from ..pipeline.table import MAX_FILE_BYTES
from . import pricing
from .agreements import AgreedSeller, AgreementDecision, accept_agreement, agreement_status
from .insights import insights
from .uploads import (
    NotReviewable,
    ReviewDecision,
    UploadForm,
    create_dataset,
    dataset_detail,
    dataset_summary,
    decide,
    visible_datasets,
)

router = APIRouter(prefix="/api/seller", tags=["seller"])

UPLOAD_PATH = "/api/seller/datasets"
# Multipart framing and the text fields on top of the 5 MiB file.
UPLOAD_BODY_LIMIT = MAX_FILE_BYTES + 64 * 1024


def steps_by_dataset(db, dataset_ids: list[str]) -> dict[str, list[PipelineStep]]:
    grouped: dict[str, list[PipelineStep]] = {dataset_id: [] for dataset_id in dataset_ids}
    if dataset_ids:
        rows = db.scalars(
            select(PipelineStep)
            .where(PipelineStep.dataset_id.in_(dataset_ids))
            .order_by(PipelineStep.position)
        )
        for step in rows:
            grouped[step.dataset_id].append(step)
    return grouped


@router.get("/agreement")
def get_agreement(response: Response, db: DB, seller: CurrentSeller) -> dict:
    response.headers["Cache-Control"] = "private, no-store"
    return agreement_status(db, seller)


@router.post("/agreement")
def record_agreement(form: AgreementDecision, db: DB, seller: CurrentSeller) -> dict:
    return accept_agreement(db, seller, form)


@router.post("/datasets", status_code=201)
async def upload_dataset(request: Request, db: DB, seller: AgreedSeller) -> dict:
    """Multipart upload: `file` (UTF-8 CSV, at most 5 MiB), `title`, `source`, `method`,
    `collected_at` (ISO date), `rights_confirmed` and an optional `rights_statement`.

    Authentication and the body-size limit are checked before the body is parsed; storage and
    database work run in the threadpool so the event loop never blocks.
    """
    form = await request.form(max_files=1, max_fields=10, max_part_size=64 * 1024)
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise RequestValidationError(
                [{"type": "missing", "loc": ("body", "file"), "msg": "Choose a CSV file.", "input": None}]
            )
        try:
            fields = UploadForm.model_validate({key: value for key, value in form.items() if key != "file"})
        except ValidationError as error:
            raise RequestValidationError(
                [
                    {"type": item["type"], "loc": ("body", *item["loc"]), "msg": item["msg"]}
                    for item in error.errors(include_url=False)
                ]
            ) from None
        data = await upload.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="CSV files may be at most 5 MiB.")
        if not data:
            raise RequestValidationError(
                [{"type": "value_error", "loc": ("body", "file"), "msg": "The file is empty.", "input": None}]
            )
        dataset = await run_in_threadpool(
            create_dataset, db, request.app.state.store, seller, fields, upload.filename, data
        )
    finally:
        await form.close()
    steps = await run_in_threadpool(lambda: steps_by_dataset(db, [dataset.id])[dataset.id])
    return dataset_summary(dataset, steps)


@router.get("/datasets")
def list_datasets(db: DB, user: CurrentUser) -> dict:
    datasets = db.scalars(visible_datasets(user).order_by(Dataset.created_at.desc()).limit(200)).all()
    steps = steps_by_dataset(db, [dataset.id for dataset in datasets])
    return {"items": [dataset_summary(dataset, steps[dataset.id]) for dataset in datasets]}


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: Annotated[str, Path(max_length=36)], db: DB, user: CurrentUser) -> dict:
    dataset = db.scalar(visible_datasets(user).where(Dataset.id == dataset_id))
    if dataset is None:
        # The same answer for "missing" and "someone else's", so ids cannot be probed.
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return detail_view(db, dataset)


def detail_view(db, dataset: Dataset) -> dict:
    steps = steps_by_dataset(db, [dataset.id])[dataset.id]
    resources = db.scalars(
        select(Resource)
        # Buyer-defined custom slices are summarized in the valuation report, not listed here.
        .where(Resource.dataset_id == dataset.id, Resource.parent_id.is_(None))
        .order_by(Resource.slice_filter.is_not(None), Resource.title)
    ).all()
    reviewer = db.get(User, dataset.reviewed_by) if dataset.reviewed_by else None
    return dataset_detail(dataset, steps, db.get(User, dataset.owner_id), resources, reviewer)


@router.post("/datasets/{dataset_id}/review")
def review_dataset(
    dataset_id: Annotated[str, Path(max_length=36)], form: ReviewDecision, db: DB, reviewer: CurrentReviewer
) -> dict:
    """A reviewer approves or rejects a dataset waiting in the queue, with a reason."""
    try:
        dataset = decide(db, dataset_id, reviewer, form)
    except NotReviewable:
        raise HTTPException(status_code=409, detail="This dataset is not waiting for review.") from None
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return detail_view(db, dataset)


def seller_dataset(db, seller, dataset_id: str) -> Dataset:
    dataset = pricing.owned_dataset(db, seller, dataset_id)
    if dataset is None:
        # Other sellers' datasets answer exactly like missing ones.
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return dataset


NOT_READY = "This dataset is not ready for pricing: it must be accepted (automatically or by a reviewer)."
STORAGE_DOWN = "The stored dataset could not be read. Try again shortly."


@router.get("/datasets/{dataset_id}/valuation")
def get_valuation(
    dataset_id: Annotated[str, Path(max_length=36)], request: Request, db: DB, seller: CurrentSeller
) -> dict:
    """The suggested price, range and breakdown per sliver, the explanation and sample-row candidates."""
    dataset = seller_dataset(db, seller, dataset_id)
    try:
        report = pricing.report(db, request.app.state.store, dataset)
    except pricing.NotPublishable:
        raise HTTPException(status_code=409, detail=NOT_READY) from None
    except pricing.DataUnavailable:
        raise HTTPException(status_code=503, detail=STORAGE_DOWN) from None
    # The current rate, so the seller sees their net at each price. Each sale snapshots its own rate.
    return {**report, "platform_fee": {"bps": request.app.state.settings.sliver_platform_fee_bps}}


@router.post("/datasets/{dataset_id}/publish")
def publish_dataset(
    dataset_id: Annotated[str, Path(max_length=36)],
    form: pricing.PublishForm,
    request: Request,
    db: DB,
    seller: AgreedSeller,
) -> dict:
    """Publish every draft sliver at its suggested price or the seller's override.

    Sample rows stay private unless listed in `sample_rows`; rows with flagged values are refused.
    """
    try:
        dataset = pricing.publish(db, request.app.state.store, seller, dataset_id, form)
    except pricing.NotPublishable:
        raise HTTPException(status_code=409, detail=NOT_READY) from None
    except pricing.PricesChanged:
        raise HTTPException(
            status_code=409,
            detail=(
                "Suggested prices changed since you loaded them (new demand or comparables). "
                "Reload and review."
            ),
        ) from None
    except pricing.InvalidSelection as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except pricing.DataUnavailable:
        raise HTTPException(status_code=503, detail=STORAGE_DOWN) from None
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return detail_view(db, dataset)


@router.get("/insights")
def seller_insights(request: Request, db: DB, seller: CurrentSeller) -> dict:
    """Unmet buyer demand, the signed-in seller's earnings (gross, Sliver's fee, net) with
    transaction links, and the balance Sliver owes them with the next payout date."""
    return insights(db, seller, request.app.state.settings.sliver_platform_fee_bps, utcnow().date())
