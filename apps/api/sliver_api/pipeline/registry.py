"""The ordered stage registry. Later issues (#14, #15) append AI review, packaging and valuation."""

from collections.abc import Callable
from dataclasses import dataclass

from . import duplicates, privacy, profile, validate
from .context import StageContext
from .table import StageResult


@dataclass(frozen=True)
class Stage:
    name: str
    label: str
    run: Callable[[StageContext], StageResult]
    # Later stages need a parseable CSV, so a failed validation skips them.
    halts_on_failure: bool = False


STAGES: tuple[Stage, ...] = (
    Stage("validate", "Validate CSV", validate.run, halts_on_failure=True),
    Stage("profile", "Profile columns", profile.run),
    Stage("privacy", "Privacy scan", privacy.run),
    Stage("duplicates", "Duplicate check", duplicates.run),
)
STAGES_BY_NAME = {stage.name: stage for stage in STAGES}
