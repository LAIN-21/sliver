"""The ordered stage registry. #15 appends valuation after `decide`."""

from collections.abc import Callable
from dataclasses import dataclass

from . import ai_review, decide, duplicates, package, privacy, profile, research, validate
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
    Stage("ai_review", "AI review", ai_review.run),
    Stage("research", "Free-data research", research.run),
    Stage("package", "Package slivers", package.run),
    Stage("decide", "Acceptance decision", decide.run),
)
STAGES_BY_NAME = {stage.name: stage for stage in STAGES}
