from dataclasses import dataclass
from functools import cached_property

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import PipelineSettings, get_pipeline_settings
from ..models import Dataset, PipelineStep
from ..storage import ObjectStore
from .table import Table, read_table


@dataclass
class StageContext:
    db: Session
    store: ObjectStore
    dataset: Dataset
    data: bytes

    @cached_property
    def table(self) -> Table:
        return read_table(self.data)

    @cached_property
    def settings(self) -> PipelineSettings:
        return get_pipeline_settings()

    @cached_property
    def earlier(self) -> dict[str, PipelineStep]:
        """This dataset's finished steps by stage name; later stages build on their results."""
        steps = self.db.scalars(
            select(PipelineStep)
            .where(PipelineStep.dataset_id == self.dataset.id)
            .order_by(PipelineStep.position)
        )
        return {step.stage: step for step in steps if step.finished_at is not None}

    def details(self, stage: str) -> dict:
        step = self.earlier.get(stage)
        return ((step.result or {}).get("details") or {}) if step else {}

    def findings(self, stage: str) -> list[dict]:
        step = self.earlier.get(stage)
        return list((step.result or {}).get("findings") or []) if step else []
