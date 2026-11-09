from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from ..auth.deps import CurrentSeller, CurrentUser
from ..deps import DB
from ..models import Dataset, PipelineStep, User
from ..pipeline.table import MAX_FILE_BYTES
from .uploads import UploadForm, create_dataset, dataset_detail, dataset_summary, visible_datasets

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


@router.post("/datasets", status_code=201)
async def upload_dataset(request: Request, db: DB, seller: CurrentSeller) -> dict:
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
    steps = steps_by_dataset(db, [dataset.id])[dataset.id]
    return dataset_detail(dataset, steps, db.get(User, dataset.owner_id))
