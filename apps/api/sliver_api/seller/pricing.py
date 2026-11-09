"""Valuation, explanation, public sample rows and publication of a seller's accepted dataset (#15).

Numbers come only from `valuation.value()`. Claude writes the plain-language explanation from
those numbers and nothing else: its payload holds the computed prices, factors and their short
reasons (aggregates and counts, never cell values or search texts), and an answer that contains
a number not in the payload is discarded. Without ANTHROPIC_API_KEY, or when Claude fails, a
deterministic template explains the same numbers. Publishing never calls Claude: it reuses a
cached explanation or the template.

Sample rows stay private unless the seller selects them, and rows holding anything the privacy
scan flagged are refused.
"""

import hashlib
import json
import logging
import re
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import ai, valuation
from ..catalog.search import unmet_demand
from ..config import get_pipeline_settings
from ..models import Dataset, PipelineStep, Resource, User, utcnow
from ..pipeline.ai_review import redact
from ..pipeline.leakguard import flagged_columns
from ..pipeline.privacy import scan_column
from ..pipeline.table import Table, read_table
from ..storage import ObjectStore

logger = logging.getLogger(__name__)

# Datasets that may be priced and published: accepted automatically or approved by a reviewer.
PUBLISHABLE = "accepted"
PUBLISHED = "published"
DEMAND_DAYS = 30
DEMAND_LIMIT = 50
MAX_PUBLIC_SAMPLE_ROWS = 5
SAMPLE_CANDIDATES = 20
MAX_EXPLANATION = 900
# A GET must not wait as long as a pipeline stage may; on timeout the template is used.
EXPLANATION_BUDGET_SECONDS = 25.0
SNAPSHOT_VERSION = 1

Price = Annotated[int, Field(ge=valuation.MIN_PRICE_MINOR, le=valuation.MAX_PRICE_MINOR)]
ResourceId = Annotated[str, StringConstraints(min_length=1, max_length=36)]


class NotPublishable(Exception):
    """The dataset is not (or no longer) waiting for pricing."""


class PricesChanged(Exception):
    """A suggestion the seller accepted is no longer the current one (demand or comparables moved)."""


class DataUnavailable(Exception):
    """The stored upload could not be read or no longer matches its SHA-256."""


class InvalidSelection(ValueError):
    """A price override or sample row the seller may not use. The message names rows, never values."""


class PublishForm(BaseModel):
    # Price overrides in USD cents by sliver id; slivers left out take the suggested price.
    prices: dict[ResourceId, Price] = Field(default_factory=dict, max_length=200)
    # The suggestions the seller saw, by sliver id. A sliver without an override is published only
    # if its current suggestion still equals this one; otherwise the seller is asked to reload.
    suggested: dict[ResourceId, Price] = Field(default_factory=dict, max_length=200)
    # 1-based data row numbers of the uploaded CSV to show publicly. Empty keeps every row private.
    sample_rows: list[Annotated[int, Field(ge=1)]] = Field(
        default_factory=list, max_length=MAX_PUBLIC_SAMPLE_ROWS
    )
    # Whether buyers may quote custom slices of the published dataset (#39). On by default.
    allow_custom_slices: bool = True


# --- reading what the pipeline found --------------------------------------------------------


def stage_results(db: Session, dataset_id: str) -> dict[str, PipelineStep]:
    steps = db.scalars(select(PipelineStep).where(PipelineStep.dataset_id == dataset_id))
    return {step.stage: step for step in steps}


def details(steps: dict[str, PipelineStep], stage: str) -> dict:
    step = steps.get(stage)
    return ((step.result or {}).get("details") or {}) if step else {}


def findings(steps: dict[str, PipelineStep], stage: str) -> list[dict]:
    step = steps.get(stage)
    return list((step.result or {}).get("findings") or []) if step else []


def max_overlap(steps: dict[str, PipelineStep]) -> float:
    """The largest share of rows also found in the seller's own or published datasets."""
    shares = [float(item.get("rows", 0)) for item in details(steps, "duplicates").get("comparisons") or []]
    for item in findings(steps, "duplicates"):
        if item["code"] == "exact_duplicate":
            shares.append(1.0)
        elif "row_overlap" in item:
            shares.append(float(item["row_overlap"]))
    return max(shares, default=0.0)


def research_verdict(steps: dict[str, PipelineStep]) -> str | None:
    step = steps.get("research")
    if step is None or step.status == "skipped":
        return None
    return details(steps, "research").get("freely_available")


def comparables(db: Session, dataset: Dataset, category: str) -> tuple[valuation.Comparable, ...]:
    rows = db.execute(
        select(Resource.price_minor, Resource.row_count)
        .where(
            Resource.status == "published",
            Resource.category == category,
            Resource.dataset_id != dataset.id,
            # Buyer-defined custom slices are priced from their parent, never used as comparables.
            Resource.parent_id.is_(None),
        )
        .order_by(Resource.id)
    ).all()
    return tuple(valuation.Comparable(price, count) for price, count in rows)


def listing_text(resource: Resource) -> str:
    slice_label = (resource.coverage or {}).get("slice", {}).get("value", "")
    return " ".join(
        [resource.title, resource.description, resource.category, *resource.tags,
         *resource.column_names, slice_label]
    )  # fmt: skip


def gather_inputs(
    db: Session, dataset: Dataset, resources: list[Resource], steps: dict[str, PipelineStep]
) -> dict[str, valuation.ValuationInputs]:
    """Everything `valuation.value` needs, read once from the pipeline results and the catalog."""
    demand = unmet_demand(db, DEMAND_DAYS, DEMAND_LIMIT)
    quality = int(details(steps, "decide").get("quality_score") or 0)
    overlap = max_overlap(steps)
    verdict = research_verdict(steps)
    by_category: dict[str, tuple[valuation.Comparable, ...]] = {}
    inputs = {}
    for resource in resources:
        if resource.category not in by_category:
            by_category[resource.category] = comparables(db, dataset, resource.category)
        inputs[resource.id] = valuation.ValuationInputs(
            category=resource.category,
            row_count=resource.row_count,
            quality_score=quality,
            comparables=by_category[resource.category],
            max_overlap=overlap,
            demand=valuation.matching_demand(listing_text(resource), demand),
            public_availability=verdict,
        )
    return inputs


# --- the explanation ------------------------------------------------------------------------


def dollars(minor: int) -> str:
    return f"${minor / 100:,.2f}"


def change_pct(factor: float) -> int:
    return valuation.whole((factor - 1) * 100)


def explanation_payload(
    full: Resource, priced: dict[str, valuation.Valuation], resources: list[Resource]
) -> dict:
    """What Claude sees: computed numbers, short reasons and public listing facts. No rows, no queries."""
    result = priced[full.id]
    slices = [priced[resource.id].suggested_price_minor for resource in resources if resource.id != full.id]
    payload = {
        "category": full.category,
        "slivers": len(resources),
        "full_dataset": {
            "rows": full.row_count,
            "suggested_price": dollars(result.suggested_price_minor),
            "range": {"low": dollars(result.low_price_minor), "high": dollars(result.high_price_minor)},
            "base": {
                "price": dollars(result.base_price_minor),
                "source": result.base_source,
                "comparables": result.base_inputs["comparables"],
            },
            "factors": [
                {
                    "name": item.name,
                    "label": item.label,
                    "factor": item.factor,
                    "change_pct": change_pct(item.factor),
                    "reason": item.reason,
                }
                for item in result.factors
            ],
        },
    }
    if slices:
        payload["slices"] = {
            "count": len(slices),
            "lowest": dollars(min(slices)),
            "highest": dollars(max(slices)),
        }
    return payload


def template_explanation(payload: dict) -> str:
    full = payload["full_dataset"]
    base = full["base"]
    category = payload["category"].replace("-", " ")
    if base["source"] == "comparables":
        start = f"the median price of {base['comparables']} published {category} slivers ({base['price']})"
    else:
        start = (
            f"Sliver's base price for {category} data ({base['price']}), "
            "since there are too few comparable listings"
        )
    adjustments = "; ".join(
        f"{item['label'].lower()} ×{item['factor']:g} ({item['reason'].rstrip('.')})"
        for item in full["factors"]
    )
    text = (
        f"Suggested price for your full dataset: {full['suggested_price']} "
        f"(range {full['range']['low']} to {full['range']['high']}). "
        f"It starts from {start} and is multiplied by {adjustments}."
    )
    if "slices" in payload:
        slices = payload["slices"]
        text += (
            f" Your {slices['count']} slices are priced the same way, "
            "from their own rows and matching demand, "
            f"from {slices['lowest']} to {slices['highest']}."
        )
    return text


NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(value) -> set[Decimal]:
    """Every number in `value` (recursively), normalized: "1,200" and "1200.0" are the same."""
    found: set[Decimal] = set()
    if isinstance(value, bool):
        return found
    if isinstance(value, int | float):
        return {Decimal(repr(abs(value))).normalize()}
    if isinstance(value, str):
        for match in NUMBER.findall(value):
            try:
                found.add(Decimal(match.replace(",", "")).normalize())
            except InvalidOperation:
                continue
        return found
    items = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
    for item in items:
        found |= numbers_in(item)
    return found


def validate_explanation(output: dict, payload: dict) -> str:
    text = output.get("explanation") if isinstance(output, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise ai.Unavailable("invalid_output")
    text = ai.clean_text(text, MAX_EXPLANATION)
    # Claude explains the numbers; it never introduces one of its own.
    if not numbers_in(text) <= numbers_in(payload):
        raise ai.Unavailable("invented_number")
    return text


def explain(store: ObjectStore, payload: dict, *, allow_call: bool) -> dict:
    """{"text", "source": "claude" | "template", ...}. With allow_call False, only a cached answer is used."""
    template = {"text": template_explanation(payload), "source": "template"}
    settings = get_pipeline_settings()
    engine = ai.engine(settings)
    if engine is None:
        return {**template, "reason": "no_api_key"}
    if isinstance(engine, ai.Claude):
        engine.budget = min(engine.budget, EXPLANATION_BUDGET_SECONDS)
    prompt = ai.load_prompt(ai.EXPLANATION_PROMPT, effort="low")
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def validate(answer: ai.Answer) -> str:
        return validate_explanation(answer.output, payload)

    try:
        if allow_call:
            text, answer, _cached = ai.ask_cached(store, engine, prompt, payload, key, validate=validate)
        else:
            answer = ai.read_cache(store, prompt, engine.model, key)
            if answer is None:
                return {**template, "reason": "not_cached"}
            text = validate(answer)
    except ai.Unavailable as error:
        logger.warning("claude explanation unavailable: %s", error)
        return {**template, "reason": str(error)}
    return {"text": text, "source": "claude", "model": answer.model}


# --- sample rows ----------------------------------------------------------------------------


def read_dataset(store: ObjectStore, dataset: Dataset) -> Table:
    try:
        data = store.get(dataset.object_key)
    except Exception:
        logger.warning("could not read dataset %s for pricing", dataset.id)
        raise DataUnavailable("storage") from None
    if hashlib.sha256(data).hexdigest() != dataset.sha256:
        raise DataUnavailable("sha256")
    return read_table(data)


def row_problem(table: Table, row: list[str], flagged: set[str]) -> str | None:
    """Why a row may not be public: a value in a flagged column, or a value a privacy detector matches."""
    for name, cell in zip(table.header, row, strict=True):
        if cell.strip() and name in flagged:
            return f"holds a value in “{name}”, which the privacy scan flagged"
        if cell.strip() and scan_column([cell]):
            return f"holds a value in “{name}” that looks like personal data"
    return None


def sample_candidates(table: Table, flagged: set[str]) -> list[dict]:
    """The first rows, so the seller can choose a few to make public. Only the owner sees these."""
    candidates = []
    for number, row in enumerate(table.rows[:SAMPLE_CANDIDATES], start=1):
        problem = row_problem(table, row, flagged)
        # Even to their owner, flagged cells are shown redacted: these rows cannot be chosen anyway.
        values = redact(row, table.header, flagged) if problem else row
        candidates.append({"row": number, "values": values, "problem": problem})
    return candidates


def check_sample(table: Table, rows: list[int], flagged: set[str]) -> list[int]:
    chosen = sorted(set(rows))
    outside = [number for number in chosen if number > len(table.rows)]
    if outside:
        raise InvalidSelection(f"Row {outside[0]} does not exist; the dataset has {len(table.rows):,} rows.")
    refused = [number for number in chosen if row_problem(table, table.rows[number - 1], flagged)]
    if refused:
        listed = ", ".join(str(number) for number in refused)
        raise InvalidSelection(
            f"Row{'s' if len(refused) > 1 else ''} {listed} cannot be public: they hold values the privacy "
            "scan flagged."
        )
    return chosen


def in_sliver(table: Table, resource: Resource, row: list[str]) -> bool:
    """Whether a dataset row belongs to this sliver (see `slicing.plan`)."""
    if not resource.slice_filter:
        return True
    value = row[table.header.index(resource.slice_filter["column"])].strip()
    if resource.slice_filter.get("period") == "month":
        value = value[:7]
    return value == resource.slice_filter["value"]


# --- the seller's report and publication ----------------------------------------------------


def dataset_resources(db: Session, dataset: Dataset) -> list[Resource]:
    """The slivers packaged from this dataset; buyer-defined custom slices are counted separately."""
    return list(
        db.scalars(
            select(Resource)
            .where(Resource.dataset_id == dataset.id, Resource.parent_id.is_(None))
            .order_by(Resource.slice_filter.is_not(None), Resource.title)
        )
    )


def price_all(db: Session, dataset: Dataset, resources: list[Resource]):
    steps = stage_results(db, dataset.id)
    inputs = gather_inputs(db, dataset, resources, steps)
    priced = {resource.id: valuation.value(inputs[resource.id]) for resource in resources}
    return steps, inputs, priced


def custom_slices_view(db: Session, dataset: Dataset) -> dict:
    count = db.scalar(
        select(func.count())
        .select_from(Resource)
        .where(Resource.dataset_id == dataset.id, Resource.parent_id.is_not(None))
    )
    return {"allowed": dataset.allow_custom_slices, "count": count or 0}


def sliver_view(resource: Resource, result: valuation.Valuation | None = None) -> dict:
    snapshot = resource.valuation or {}
    view = {
        "id": resource.id,
        "title": resource.title,
        "label": (resource.coverage or {}).get("slice", {}).get("value") or "Full dataset",
        "row_count": resource.row_count,
        "status": resource.status,
        "valuation": result.to_json() if result is not None else snapshot.get("valuation"),
    }
    if resource.status == "published":
        view.update(
            price_minor=resource.price_minor,
            accepted_suggestion=snapshot.get("accepted_suggestion"),
            published_at=resource.published_at.isoformat().replace("+00:00", "Z")
            if resource.published_at
            else None,
            sample_rows=len(resource.sample_rows or []),
        )
    return view


def report(db: Session, store: ObjectStore, dataset: Dataset) -> dict:
    """The seller's valuation report: live for an accepted dataset, the snapshot once published."""
    resources = [resource for resource in dataset_resources(db, dataset) if resource.status != "rejected"]
    if dataset.status == PUBLISHED:
        published = [resource for resource in resources if resource.valuation]
        first = published[0].valuation if published else {}
        return {
            "dataset_id": dataset.id,
            "status": dataset.status,
            "publishable": False,
            "payout_ready": bool((owner := db.get(User, dataset.owner_id)) and owner.xrpl_address),
            "explanation": first.get("explanation"),
            "slivers": [sliver_view(resource) for resource in resources],
            "custom_slices": custom_slices_view(db, dataset),
            "sample": {
                "max_rows": MAX_PUBLIC_SAMPLE_ROWS,
                "selected": first.get("sample_row_numbers", []),
                "header": [column["name"] for column in dataset.columns],
                "candidates": [],
            },
        }
    if dataset.status != PUBLISHABLE:
        raise NotPublishable(dataset.status)
    drafts = [resource for resource in resources if resource.status == "draft"]
    if not drafts:
        raise NotPublishable(dataset.status)
    steps, _inputs, priced = price_all(db, dataset, drafts)
    table = read_dataset(store, dataset)
    flagged = flagged_columns(findings(steps, "privacy"))
    payload = explanation_payload(drafts[0], priced, drafts)
    owner = db.get(User, dataset.owner_id)
    return {
        "dataset_id": dataset.id,
        "status": dataset.status,
        "publishable": True,
        # Buyers pay the seller directly; without an XRPL address a published sliver cannot be sold.
        "payout_ready": bool(owner and owner.xrpl_address),
        "explanation": explain(store, payload, allow_call=True),
        "slivers": [sliver_view(resource, priced[resource.id]) for resource in drafts],
        "custom_slices": custom_slices_view(db, dataset),
        "sample": {
            "max_rows": MAX_PUBLIC_SAMPLE_ROWS,
            "selected": [],
            "header": table.header,
            "candidates": sample_candidates(table, flagged),
        },
    }


def owned_dataset(db: Session, seller: User, dataset_id: str, *, lock: bool = False) -> Dataset | None:
    query = select(Dataset).where(Dataset.id == dataset_id, Dataset.owner_id == seller.id)
    return db.scalar(query.with_for_update() if lock else query)


def publish(
    db: Session, store: ObjectStore, seller: User, dataset_id: str, form: PublishForm
) -> Dataset | None:
    """Price every draft sliver (the suggestion, or the seller's override) and publish them together."""
    dataset = owned_dataset(db, seller, dataset_id, lock=True)
    if dataset is None:
        db.rollback()
        return None
    drafts = [resource for resource in dataset_resources(db, dataset) if resource.status == "draft"]
    if dataset.status != PUBLISHABLE or not drafts:
        db.rollback()
        raise NotPublishable(dataset.status)
    unknown = (set(form.prices) | set(form.suggested)) - {resource.id for resource in drafts}
    if unknown:
        db.rollback()
        raise InvalidSelection("A price was given for a sliver that is not a draft of this dataset.")

    steps, inputs, priced = price_all(db, dataset, drafts)
    stale = [
        resource.id
        for resource in drafts
        if resource.id not in form.prices
        and resource.id in form.suggested
        and form.suggested[resource.id] != priced[resource.id].suggested_price_minor
    ]
    if stale:
        db.rollback()
        raise PricesChanged(stale)
    try:
        table = read_dataset(store, dataset)
        chosen = check_sample(table, form.sample_rows, flagged_columns(findings(steps, "privacy")))
    except (InvalidSelection, DataUnavailable):
        db.rollback()
        raise
    # Publishing never waits on Claude: a cached explanation of these exact numbers, or the template.
    explanation = explain(store, explanation_payload(drafts[0], priced, drafts), allow_call=False)
    now = utcnow()
    for resource in drafts:
        result = priced[resource.id]
        price = form.prices.get(resource.id, result.suggested_price_minor)
        resource.price_minor = price
        resource.status = "published"
        resource.published_at = now
        resource.sample_rows = [
            table.rows[n - 1] for n in chosen if in_sliver(table, resource, table.rows[n - 1])
        ]
        resource.valuation = {
            "version": SNAPSHOT_VERSION,
            "computed_at": now.isoformat().replace("+00:00", "Z"),
            "inputs": asdict(inputs[resource.id]),
            "valuation": result.to_json(),
            "price_minor": price,
            "accepted_suggestion": price == result.suggested_price_minor,
            "explanation": explanation,
            "sample_row_numbers": chosen,
        }
    dataset.status = PUBLISHED
    dataset.allow_custom_slices = form.allow_custom_slices
    db.commit()
    return dataset
