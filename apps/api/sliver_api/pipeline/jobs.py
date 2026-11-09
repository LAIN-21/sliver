"""Pipeline jobs are `pipeline_steps` rows claimed with `FOR UPDATE SKIP LOCKED` (ADR 0003).

A step is claimable when it is pending, or running but abandoned by a worker that died, and
every earlier step of the same dataset has finished. Steps of one dataset therefore run in
order, while several workers can process different datasets at once.
"""

import hashlib
import logging
from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, aliased, sessionmaker

from ..models import Dataset, PipelineStep, utcnow
from ..storage import ObjectStore
from .context import StageContext
from .registry import STAGES, STAGES_BY_NAME
from .table import StageResult

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
FINISHED = ("passed", "warning", "failed", "skipped")


def enqueue(db: Session, dataset: Dataset) -> list[PipelineStep]:
    steps = [
        PipelineStep(dataset_id=dataset.id, stage=stage.name, position=position, status="pending")
        for position, stage in enumerate(STAGES)
    ]
    db.add_all(steps)
    return steps


def claim_next(sessions: sessionmaker[Session], step_timeout_seconds: int) -> str | None:
    """Atomically mark the next runnable step as running and return its id."""
    now = utcnow()
    earlier = aliased(PipelineStep)
    unfinished_before = (
        select(earlier.id)
        .where(
            earlier.dataset_id == PipelineStep.dataset_id,
            earlier.position < PipelineStep.position,
            earlier.status.not_in(FINISHED),
        )
        .exists()
    )
    abandoned = and_(
        PipelineStep.status == "running",
        PipelineStep.started_at < now - timedelta(seconds=step_timeout_seconds),
    )
    with sessions() as db, db.begin():
        step = db.scalar(
            select(PipelineStep)
            .where(or_(PipelineStep.status == "pending", abandoned), ~unfinished_before)
            .order_by(PipelineStep.created_at, PipelineStep.position)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if step is None:
            return None
        step.status = "running"
        step.started_at = now
        step.attempts += 1
        db.execute(update(Dataset).where(Dataset.id == step.dataset_id).values(status="inspecting"))
        return step.id


def execute(sessions: sessionmaker[Session], store: ObjectStore, step_id: str) -> str:
    """Run one claimed step and record its outcome. Returns the step's final status."""
    with sessions() as db:
        step = db.get(PipelineStep, step_id)
        dataset = db.get(Dataset, step.dataset_id)
        stage = STAGES_BY_NAME.get(step.stage)
        result: StageResult | None = None
        error: str | None = None
        if stage is None:
            error = f"Unknown stage {step.stage!r}."
        elif step.attempts > MAX_ATTEMPTS:
            error = f"Stopped after {MAX_ATTEMPTS} attempts; the worker did not finish this stage."
        else:
            try:
                data = store.get(dataset.object_key)
            except Exception:
                # Storage may be briefly unavailable: leave the step running so it is reclaimed
                # after the timeout and retried, up to MAX_ATTEMPTS.
                logger.exception("could not read dataset %s; will retry", dataset.id)
                db.rollback()
                return "running"
            try:
                if hashlib.sha256(data).hexdigest() != dataset.sha256:
                    error = "Stored bytes do not match the upload's SHA-256."
                else:
                    result = stage.run(StageContext(db=db, store=store, dataset=dataset, data=data))
            except Exception:
                logger.exception("stage %s failed for dataset %s", step.stage, dataset.id)
                error = "The stage could not finish because of an internal error."
        db.rollback()  # stages only read; end the read transaction before recording the result
        return finish(db, step_id, result, error)


def finish(db: Session, step_id: str, result: StageResult | None, error: str | None) -> str:
    with db.begin():
        step = db.get(PipelineStep, step_id, with_for_update=True)
        dataset = db.get(Dataset, step.dataset_id, with_for_update=True)
        step.finished_at = utcnow()
        if result is None:
            step.status, step.error = "failed", error
        else:
            step.status, step.result = result.status, result.to_json()
            for field, value in result.dataset_updates.items():
                setattr(dataset, field, value)
        stage = STAGES_BY_NAME.get(step.stage)
        if step.status == "failed" and (stage is None or stage.halts_on_failure):
            db.execute(
                update(PipelineStep)
                .where(PipelineStep.dataset_id == dataset.id, PipelineStep.position > step.position)
                .values(status="skipped", finished_at=step.finished_at)
            )
        db.flush()
        statuses = db.scalars(select(PipelineStep.status).where(PipelineStep.dataset_id == dataset.id)).all()
        if all(status in FINISHED for status in statuses):
            # "review" means inspection passed and the dataset waits for review (#14).
            dataset.status = "rejected" if "failed" in statuses else "review"
        return step.status


def process_available(
    sessions: sessionmaker[Session], store: ObjectStore, step_timeout_seconds: int, limit: int = 100
) -> int:
    """Run claimable steps until none remain (or `limit` is reached). Returns how many ran."""
    ran = 0
    while ran < limit:
        step_id = claim_next(sessions, step_timeout_seconds)
        if step_id is None:
            break
        execute(sessions, store, step_id)
        ran += 1
    return ran
