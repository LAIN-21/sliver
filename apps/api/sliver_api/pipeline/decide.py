"""Stage 8: the acceptance decision. Deterministic rules only; model output can send a dataset to a
reviewer but never accept one on its own.

Blocking (always the reviewer queue): any `high` finding, any stage that did not finish, any
`medium` privacy finding or near duplicate, any `medium` sensitivity concern from the AI review,
or nothing packaged.
Otherwise the dataset is accepted automatically when its quality score reaches
SLIVER_AUTO_ACCEPT_QUALITY (70 by default) and is then ready for pricing (#15).
"""

from .context import StageContext
from .table import StageResult

# Points a non-blocking finding takes off the quality score of 100.
DEDUCTIONS = {"medium": 10, "low": 3}
# Half a point per percent of empty cells, averaged over the columns.
NULL_WEIGHT = 0.5


def blocking_reason(stage: str, item: dict) -> bool:
    if item["severity"] == "high":
        return True
    if item["severity"] != "medium":
        return False
    return stage in ("privacy", "duplicates") or item["code"] == "ai_sensitivity_concern"


def run(context: StageContext) -> StageResult:
    threshold = context.settings.sliver_auto_accept_quality
    blocking: list[dict] = []
    deductions: list[dict] = []
    for stage, step in context.earlier.items():
        if step.status == "failed" and step.result is None:
            blocking.append(
                {"stage": stage, "code": "stage_error", "message": step.error or "The stage failed."}
            )
        for item in context.findings(stage):
            entry = {
                "stage": stage,
                "code": item["code"],
                "severity": item["severity"],
                "message": item["message"],
            }
            if blocking_reason(stage, item):
                blocking.append(entry)
            else:
                deductions.append({**entry, "points": DEDUCTIONS[item["severity"]]})
    if not context.details("package").get("resources") and not any(i["stage"] == "package" for i in blocking):
        blocking.append({"stage": "package", "code": "not_packaged", "message": "No slivers were packaged."})

    columns = context.details("profile").get("columns") or []
    if columns:
        empty = sum(column["null_pct"] for column in columns) / len(columns)
        if round(empty * NULL_WEIGHT):
            deductions.append(
                {"stage": "profile", "code": "empty_cells", "message": f"{empty:.1f}% of cells are empty.",
                 "points": round(empty * NULL_WEIGHT)}
            )  # fmt: skip
    score = max(0, 100 - sum(item["points"] for item in deductions))

    accepted = not blocking and score >= threshold
    if accepted:
        summary = f"Accepted automatically (quality {score}, threshold {threshold}); ready for pricing."
    elif blocking:
        reasons = len(blocking)
        summary = f"Sent to the reviewer queue: {reasons} blocking finding{'s' if reasons != 1 else ''}."
    else:
        summary = f"Sent to the reviewer queue: quality {score} is below the threshold of {threshold}."
    decision = "accepted" if accepted else "review"
    return StageResult(
        summary=summary,
        details={
            "decision": decision,
            "quality_score": score,
            "threshold": threshold,
            "blocking": blocking,
            "deductions": deductions,
        },
        dataset_updates={"status": decision},
        resource_updates={} if accepted else {"status": "review"},
    )
