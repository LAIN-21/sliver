"""Stage 5: Claude proposes the public listing (category, tags, title, description), raises quality
and sensitivity concerns and suggests a slice column. Deterministic rules check every proposal:
the slice column must be a public-safe category or a date cut by month, and public text that
repeats raw cell values is replaced by the standard text.
"""

import logging

from .. import ai
from .context import StageContext
from .duplicates import sample
from .leakguard import TEMPORAL, LeakGuard, flagged_columns, is_categorical, number_forms, shareable_coverage
from .privacy import scan_column
from .profile import profile_column
from .table import StageResult, Table, finding

logger = logging.getLogger(__name__)

REDACTED = "[redacted]"
# Profile entries that hold raw cell values; dropped for columns the privacy scan flagged.
VALUE_STATS = ("min", "max", "mean")
# Value slices the rule picks on its own stay few; Claude may propose up to MAX_CATEGORIES.
RULE_MAX_SLICES = 24
MAX_MONTHS = 36


def redact(row: list[str], header: list[str], flagged: set[str]) -> list[str]:
    return [
        REDACTED if name in flagged or (cell and scan_column([cell])) else cell
        for name, cell in zip(header, row, strict=True)
    ]


def model_profile(profile: list[dict], flagged: set[str]) -> list[dict]:
    """The profile without the value statistics of flagged columns (a phone number as `max`)."""
    return [
        {key: value for key, value in column.items() if key not in VALUE_STATS}
        if column["name"] in flagged
        else column
        for column in profile
    ]


def review_payload(table: Table, profile: list[dict], time_coverage: dict | None, flagged: set[str]) -> dict:
    """Everything the model sees: schema, profile and at most 20 redacted sample rows.

    Nothing from a flagged column leaves as a raw value: its cells, its value statistics and a
    time coverage built from it are all withheld.
    """
    return {
        "header": table.header,
        "row_count": len(table.rows),
        "columns": model_profile(profile, flagged),
        "time_coverage": shareable_coverage(time_coverage, flagged),
        "redacted_columns": sorted(flagged),
        "sample_rows": [redact(row, table.header, flagged) for row in sample(table.rows, ai.MAX_SAMPLE_ROWS)],
    }


def month_count(table: Table, name: str) -> int:
    return len({value.strip()[:7] for value in table.column(table.header.index(name)) if value.strip()})


def valid_slice(table: Table, column: dict, period: str, flagged: set[str], max_values: int) -> bool:
    if period == "month":
        return column["type"] in TEMPORAL and 2 <= month_count(table, column["name"]) <= MAX_MONTHS
    if period == "value":
        return is_categorical(column, len(table.rows), flagged) and 2 <= column["distinct"] <= max_values
    return False


def choose_slice(table: Table, profile: list[dict], flagged: set[str], proposal: dict | None) -> dict:
    """Claude's proposal when it passes the rules, otherwise the first category column, then month."""
    by_name = {column["name"]: column for column in profile}
    if proposal and proposal.get("column") in by_name:
        column = by_name[proposal["column"]]
        if valid_slice(table, column, proposal.get("period", ""), flagged, max_values=50):
            return {"column": column["name"], "period": proposal["period"], "source": "claude"}
    for column in profile:
        if column["type"] == "text" and valid_slice(table, column, "value", flagged, RULE_MAX_SLICES):
            return {"column": column["name"], "period": "value", "source": "rule"}
    for column in profile:
        if valid_slice(table, column, "month", flagged, RULE_MAX_SLICES):
            return {"column": column["name"], "period": "month", "source": "rule"}
    return {"column": "", "period": "none", "source": "none"}


def quoted(columns: list[str]) -> str:
    return ", ".join(f"“{name}”" for name in columns)


def leak_finding(field: str, columns: list[str], replacement: str) -> dict:
    return finding(
        "public_text_leak",
        "low",
        f"The proposed public {field} repeated cell values from {quoted(columns)}; {replacement}",
        field=field,
        columns=columns,
    )


def guard_listing(guard: LeakGuard, proposal: dict | None, fallback: dict, row_count: int):
    """Pick each public field from Claude's proposal or the standard text, so nothing leaks.

    The standard description, category and tags are built from public facts only (column names,
    counts, coverage). The standard title is the seller's own title, so it is checked as well.
    """
    listing, sources, findings = {}, {}, []
    for field in ("title", "description", "category"):
        if proposal is not None:
            leaked = guard.leaks(proposal[field])
            if not leaked:
                listing[field], sources[field] = proposal[field], "claude"
                continue
            findings.append(leak_finding(field, leaked, f"Sliver used its standard {field} instead."))
        listing[field], sources[field] = fallback[field], "standard"
    if sources["title"] == "standard":
        sources["title"] = "seller"
        leaked = guard.leaks(listing["title"])
        if leaked:
            findings.append(
                leak_finding("title", leaked, "the public title stays generic until it is edited.")
            )
            category = listing["category"].replace("-", " ").capitalize()
            listing["title"], sources["title"] = f"{category} dataset ({row_count:,} rows)", "standard"
    kept = [tag for tag in proposal["tags"] if not guard.leaks(tag)] if proposal else []
    if proposal and len(kept) < len(proposal["tags"]):
        leaked = sorted({column for tag in proposal["tags"] for column in guard.leaks(tag)})
        findings.append(leak_finding("tags", leaked, "Sliver dropped those tags."))
    listing["tags"], sources["tags"] = (kept, "claude") if kept else (fallback["tags"], "standard")
    return listing, sources, findings


def concern_findings(guard: LeakGuard, proposal: dict) -> list[dict]:
    items = []
    for kind, code in (("quality", "ai_quality_concern"), ("sensitivity", "ai_sensitivity_concern")):
        for concern in proposal[f"{kind}_concerns"]:
            column = concern["column"] or None
            message = concern["message"]
            if guard.leaks(message):
                # Findings never carry cell values, even when the model quoted them.
                where = f" about “{column}”" if column else ""
                message = f"a {kind} concern{where} (details withheld because they quoted cell values)"
            severity = "medium" if concern["severity"] == "high" else concern["severity"]
            items.append(
                finding(
                    code,
                    severity,
                    f"Claude: {message}",
                    column=column,
                    model_severity=concern["severity"],
                )
            )
    return items


def run(context: StageContext) -> StageResult:
    dataset, table = context.dataset, context.table
    profile_details = context.details("profile")
    profile = profile_details.get("columns") or [
        profile_column(name, table.column(index)) for index, name in enumerate(table.header)
    ]
    flagged = flagged_columns(context.findings("privacy"))
    # A coverage built from a personal date column (a birth date) never reaches public text either.
    time_coverage = shareable_coverage(profile_details.get("time_coverage"), flagged)

    findings: list[dict] = []
    details: dict = {"prompt": ai.REVIEW_PROMPT, "engine": "fallback"}
    proposal = None
    engine = ai.engine(context.settings)
    if engine is None:
        details["fallback_reason"] = "no_api_key"
    else:
        payload = review_payload(table, profile, time_coverage, flagged)
        try:
            proposal, answer, cached = ai.ask_cached(
                context.store,
                engine,
                ai.load_prompt(ai.REVIEW_PROMPT),
                payload,
                dataset.sha256,
                validate=lambda answer: ai.validate_review(answer.output),
            )
            details.update(engine="claude", model=answer.model, cached=cached, request_id=answer.request_id)
        except ai.Unavailable as error:
            logger.warning("claude review unavailable for dataset %s: %s", dataset.id, error)
            details["fallback_reason"] = str(error)
            findings.append(
                finding(
                    "ai_unavailable",
                    "low",
                    f"Claude could not review this dataset ({error}); Sliver used its standard metadata.",
                )
            )

    slice_choice = choose_slice(table, profile, flagged, proposal["slice"] if proposal else None)
    fallback = ai.fallback_review(dataset.title, table.header, len(table.rows), time_coverage, slice_choice)
    allowed = number_forms(len(table.rows), len(table.header))
    guard = LeakGuard(table, profile, flagged, allowed=allowed)
    listing, sources, leak_findings = guard_listing(guard, proposal, fallback, len(table.rows))
    findings.extend(leak_findings)
    if proposal is not None:
        findings.extend(concern_findings(guard, proposal))

    sliced = f"sliced by {slice_choice['column']}" if slice_choice["column"] else "not sliced"
    if slice_choice["period"] == "month":
        sliced = f"sliced by month of {slice_choice['column']}"
    engine_label = "Claude" if details["engine"] == "claude" else "the offline fallback"
    summary = f"Reviewed with {engine_label}: {listing['category']}, {sliced}."
    details.update(listing=listing, listing_sources=sources, slice=slice_choice)
    return StageResult(summary=summary, findings=findings, details=details)
