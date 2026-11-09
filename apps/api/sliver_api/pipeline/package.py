"""Stage 7: materialize the full dataset and each slice as Resources ("slivers") in `draft`.

Each sliver is its own immutable CSV object with its own SHA-256. Its public text is checked by
the leak guard once more, with the slice label added, and nothing is packaged if it would reveal
raw cell values. Publication and pricing are #15: Resources carry a placeholder price until then.
"""

import hashlib

from .. import slicing
from ..models import Resource
from .context import StageContext
from .leakguard import LeakGuard, flagged_columns, number_forms, public_texts
from .profile import profile_column
from .table import StageResult, count, finding

# resources.price_minor is required and positive; #15 sets the real price before publication,
# and only published Resources are ever shown or sold.
PLACEHOLDER_PRICE_MINOR = 1


def object_key(context: StageContext, piece: slicing.Piece) -> str:
    return f"resources/{context.dataset.owner_id}/{context.dataset.id}/{piece.key}.csv"


def run(context: StageContext) -> StageResult:
    review = context.details("ai_review")
    listing = review.get("listing")
    if not listing:
        return StageResult(
            summary="Nothing was packaged: the AI review did not finish.",
            findings=[
                finding("not_packaged", "high", "The AI review did not finish, so no slivers were made.")
            ],
        )
    table, dataset = context.table, context.dataset
    choice = review.get("slice") or {}
    column = choice.get("column") or None
    period = "month" if choice.get("period") == "month" else None
    pieces = slicing.plan(table.header, table.rows, column, period)

    profile_details = context.details("profile")
    profile = profile_details.get("columns") or [
        profile_column(name, table.column(index)) for index, name in enumerate(table.header)
    ]
    time_column = (profile_details.get("time_coverage") or {}).get("column")
    guard = LeakGuard(
        table,
        profile,
        flagged_columns(context.findings("privacy")),
        allowed={
            *number_forms(len(table.rows), len(table.header), *(len(piece.rows) for piece in pieces)),
            *(piece.label for piece in pieces),
        },
    )

    drafts = []
    leaks = []
    for piece in pieces:
        text = {
            **listing,
            "title": slicing.piece_title(listing["title"], piece)[:160],
            "description": slicing.piece_description(listing["description"], piece),
        }
        for field, value in public_texts(text).items():
            leaked = guard.leaks(value)
            if leaked:
                leaks.append((piece, field, leaked))
        drafts.append((piece, text))
    if leaks:
        piece, field, columns = leaks[0]
        names = ", ".join(f"“{name}”" for name in columns)
        return StageResult(
            summary="Nothing was packaged: public text would reveal raw cell values.",
            findings=[
                finding(
                    "public_text_leak",
                    "high",
                    f"The public {field} of the {piece.label} sliver repeats cell values from {names}.",
                    field=field,
                    columns=columns,
                )
            ],
        )

    records, packaged = [], []
    for piece, text in drafts:
        body = slicing.to_csv(table.header, piece.rows)
        key = object_key(context, piece)
        slicing.store_object(context.store, key, body)
        sha256 = hashlib.sha256(body).hexdigest()
        records.append(
            Resource(
                dataset_id=dataset.id,
                owner_id=dataset.owner_id,
                title=text["title"],
                description=text["description"],
                category=text["category"],
                tags=text["tags"],
                columns=slicing.describe(table.header, piece.rows),
                column_names=[name.lower() for name in table.header],
                row_count=len(piece.rows),
                coverage=slicing.piece_coverage(table.header, piece, time_column),
                slice_filter=piece.filter,
                object_key=key,
                sha256=sha256,
                size_bytes=len(body),
                price_minor=PLACEHOLDER_PRICE_MINOR,
                status="draft",
                search_text=slicing.search_text(text["category"], text["tags"], table.header, piece.label),
            )
        )
        packaged.append(
            {"label": piece.label, "title": text["title"], "rows": len(piece.rows), "sha256": sha256,
             "size_bytes": len(body)}
        )  # fmt: skip
    slivers = count(len(pieces) - 1, "sliver")
    summary = (
        f"Packaged the full dataset and {slivers} as draft Resources."
        if column
        else ("Packaged the full dataset as a draft Resource (no slice column).")
    )
    return StageResult(
        summary=summary,
        details={"slice": choice, "placeholder_price_minor": PLACEHOLDER_PRICE_MINOR, "resources": packaged},
        records=records,
    )
