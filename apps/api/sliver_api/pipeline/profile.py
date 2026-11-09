"""Stage 2: column types, null rates, distinct counts, value ranges and time coverage."""

from ..slicing import infer_type
from .context import StageContext
from .table import StageResult, finding

NUMERIC = ("integer", "decimal")
TEMPORAL = ("date", "month")


def number(value: str) -> float:
    return float(value.replace(",", ""))


def profile_column(name: str, values: list[str]) -> dict:
    present = [value.strip() for value in values if value.strip()]
    kind = infer_type(values)
    stats: dict = {
        "name": name,
        "type": kind,
        "null_count": len(values) - len(present),
        "null_pct": round(100 * (len(values) - len(present)) / len(values), 1) if values else 0.0,
        "distinct": len(set(present)),
    }
    if not present:
        return stats
    if kind in NUMERIC:
        numbers = [number(value) for value in present]
        cast = int if kind == "integer" else float
        stats.update(
            min=cast(min(numbers)), max=cast(max(numbers)), mean=round(sum(numbers) / len(numbers), 4)
        )
    elif kind in TEMPORAL:
        stats.update(min=min(present), max=max(present))
    else:
        lengths = [len(value) for value in present]
        stats.update(min_length=min(lengths), max_length=max(lengths))
    return stats


def run(context: StageContext) -> StageResult:
    table = context.table
    columns = [profile_column(name, table.column(index)) for index, name in enumerate(table.header)]
    findings = []
    for column in columns:
        if column["null_count"] == len(table.rows):
            findings.append(
                finding(
                    "empty_column", "low", f"Column “{column['name']}” has no values.", column=column["name"]
                )
            )
        elif column["distinct"] == 1 and len(table.rows) > 1:
            findings.append(
                finding(
                    "constant_column",
                    "low",
                    f"Column “{column['name']}” has the same value in every row.",
                    column=column["name"],
                )
            )

    time = next((column for column in columns if column["type"] in TEMPORAL and "min" in column), None)
    coverage = None
    if time:
        values = {
            value.strip()[:7] for value in table.column(table.header.index(time["name"])) if value.strip()
        }
        coverage = {"column": time["name"], "start": time["min"], "end": time["max"], "months": len(values)}

    types = ", ".join(sorted({column["type"] for column in columns}))
    summary = f"Profiled {len(columns)} columns ({types})"
    summary += (
        f"; time coverage {coverage['start']} to {coverage['end']}." if coverage else "; no date column."
    )
    return StageResult(
        summary=summary,
        findings=findings,
        details={"columns": columns, "time_coverage": coverage},
        dataset_updates={"columns": [{"name": column["name"], "type": column["type"]} for column in columns]},
    )
