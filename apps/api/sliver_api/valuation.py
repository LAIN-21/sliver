"""Explainable, deterministic sliver pricing (#15).

    suggested = base × quality × uniqueness × demand × public availability × coverage

`value()` is a pure function of `ValuationInputs`: no database, clock, randomness or model, so
the same inputs always give the same price. Every factor is rounded before it is multiplied and
is returned in the breakdown with the inputs it used, so the breakdown multiplies out to exactly
the suggested price. Claude may explain these numbers in words (`seller/pricing.py`) but never
chooses or changes one.

- base: the median price of published comparable slivers in the same category (at least
  MIN_COMPARABLES of them), otherwise a fixed category base.
- quality: the acceptance stage's quality score (0-100) maps to 0.5-1.0.
- uniqueness: the largest share of rows also found in existing catalog data lowers the price.
- demand: catalog searches that found nothing but match this sliver raise the price.
- public availability: research finding a free equivalent lowers the price; neutral when the
  research did not run or could not tell.
- coverage: rows relative to the comparables' median (or REFERENCE_ROWS), with diminishing
  returns (square root).
"""

import math
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal

# The database bounds on resources.price_minor (USD cents).
MIN_PRICE_MINOR = 1
MAX_PRICE_MINOR = 100_000_000

MIN_COMPARABLES = 2
# Category bases in USD cents when there are too few comparables; DEFAULT_BASE for the rest.
CATEGORY_BASE_MINOR = {
    "port-operations": 800,
    "shipping-schedules": 600,
    "freight-rates": 500,
    "customs": 400,
    "trade": 500,
    "logistics": 500,
    "finance": 800,
    "energy": 700,
}
DEFAULT_BASE_MINOR = 300
REFERENCE_ROWS = 1_000

QUALITY_FLOOR = 0.5  # a score of 0 halves the price; 100 leaves it unchanged
OVERLAP_WEIGHT = 0.6  # fully overlapping data keeps 40% of the price
DEMAND_STEP = 0.1  # each matching unmet search adds 10%
DEMAND_CAP = 0.5  # up to +50%
PUBLIC_AVAILABILITY = {"yes": 0.5, "partly": 0.75, "no": 1.0, "unknown": 1.0}
COVERAGE_BOUNDS = (0.25, 4.0)
# The range around the suggestion is narrower when there are enough comparables to anchor it.
SPREAD_ANCHORED = 0.2
SPREAD_UNANCHORED = 0.35

FACTOR_ORDER = ("quality", "uniqueness", "demand", "public_availability", "coverage")


@dataclass(frozen=True)
class Comparable:
    price_minor: int
    row_count: int


@dataclass(frozen=True)
class DemandMatch:
    query: str
    unmet_searches: int


@dataclass(frozen=True)
class ValuationInputs:
    category: str
    row_count: int
    quality_score: int
    comparables: tuple[Comparable, ...] = ()
    # Largest share (0-1) of sampled rows also found in existing catalog data.
    max_overlap: float = 0.0
    demand: tuple[DemandMatch, ...] = ()
    # The research verdict ("yes", "partly", "no", "unknown") or None when research did not run.
    public_availability: str | None = None


@dataclass(frozen=True)
class Factor:
    name: str
    label: str
    factor: float
    inputs: dict
    reason: str


@dataclass(frozen=True)
class Valuation:
    suggested_price_minor: int
    low_price_minor: int
    high_price_minor: int
    base_price_minor: int
    base_source: str  # "comparables" or "category"
    base_inputs: dict
    factors: tuple[Factor, ...] = field(default_factory=tuple)

    def to_json(self) -> dict:
        return {
            "suggested_price_minor": self.suggested_price_minor,
            "range": {"low_price_minor": self.low_price_minor, "high_price_minor": self.high_price_minor},
            "base": {
                "price_minor": self.base_price_minor,
                "source": self.base_source,
                "inputs": self.base_inputs,
            },
            "factors": [asdict(factor) for factor in self.factors],
        }


def rounded(value: float, places: int = 3) -> float:
    return float(Decimal(repr(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def whole(value: float) -> int:
    return int(Decimal(repr(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def clamp_price(value: float) -> int:
    return max(MIN_PRICE_MINOR, min(MAX_PRICE_MINOR, whole(value)))


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def base_price(inputs: ValuationInputs) -> tuple[int, str, dict, int]:
    """The starting price, where it came from, its inputs and the reference row count for coverage."""
    usable = [item for item in inputs.comparables if item.price_minor > 0 and item.row_count > 0]
    if len(usable) >= MIN_COMPARABLES:
        price = whole(median([item.price_minor for item in usable]))
        rows = max(1, whole(median([item.row_count for item in usable])))
        return (
            price,
            "comparables",
            {"category": inputs.category, "comparables": len(usable), "median_rows": rows},
            rows,
        )
    price = CATEGORY_BASE_MINOR.get(inputs.category, DEFAULT_BASE_MINOR)
    return (
        price,
        "category",
        {"category": inputs.category, "comparables": len(usable), "reference_rows": REFERENCE_ROWS},
        REFERENCE_ROWS,
    )


def quality_factor(score: int) -> Factor:
    score = max(0, min(100, score))
    value = rounded(QUALITY_FLOOR + (1 - QUALITY_FLOOR) * score / 100)
    return Factor(
        "quality",
        "Quality",
        value,
        {"quality_score": score},
        f"Quality score {score} of 100.",
    )


def uniqueness_factor(overlap: float) -> Factor:
    overlap = rounded(max(0.0, min(1.0, overlap)))
    value = rounded(1 - OVERLAP_WEIGHT * overlap)
    reason = (
        f"{whole(overlap * 100)}% of sampled rows already appear in catalog data."
        if overlap
        else "No overlap with existing catalog data."
    )
    return Factor("uniqueness", "Uniqueness", value, {"max_row_overlap": overlap}, reason)


def demand_factor(matches: tuple[DemandMatch, ...]) -> Factor:
    ordered = sorted(matches, key=lambda item: (-item.unmet_searches, item.query))
    unmet = sum(max(0, item.unmet_searches) for item in ordered)
    value = rounded(1 + min(DEMAND_CAP, DEMAND_STEP * unmet))
    if unmet:
        reason = f"{unmet} unmet buyer search{'es' if unmet != 1 else ''} match this sliver."
    else:
        reason = "No unmet buyer searches match this sliver."
    return Factor(
        "demand",
        "Buyer demand",
        value,
        {
            "unmet_searches": unmet,
            "matched_queries": [
                {"query": item.query, "unmet_searches": item.unmet_searches} for item in ordered
            ],
        },
        reason,
    )


def availability_factor(verdict: str | None) -> Factor:
    known = verdict if verdict in PUBLIC_AVAILABILITY else None
    value = PUBLIC_AVAILABILITY[known] if known else 1.0
    reason = {
        None: "Research did not run, so public availability is neutral.",
        "yes": "Research found an equivalent dataset that is freely available.",
        "partly": "Research found part of this data freely available.",
        "no": "Research found no freely available equivalent.",
        "unknown": "Research could not tell whether a free equivalent exists.",
    }[known]
    return Factor(
        "public_availability",
        "Public availability",
        value,
        {"research": known or "not_run"},
        reason,
    )


def coverage_factor(rows: int, reference_rows: int) -> Factor:
    low, high = COVERAGE_BOUNDS
    raw = math.sqrt(max(0, rows) / max(1, reference_rows))
    value = rounded(max(low, min(high, raw)))
    return Factor(
        "coverage",
        "Coverage",
        value,
        {"rows": rows, "reference_rows": reference_rows},
        f"{rows:,} rows against a reference of {reference_rows:,}.",
    )


def value(inputs: ValuationInputs) -> Valuation:
    """The suggested price, its range and the per-factor breakdown for one sliver."""
    base, source, base_inputs, reference_rows = base_price(inputs)
    factors = (
        quality_factor(inputs.quality_score),
        uniqueness_factor(inputs.max_overlap),
        demand_factor(inputs.demand),
        availability_factor(inputs.public_availability),
        coverage_factor(inputs.row_count, reference_rows),
    )
    product = float(base)
    for item in factors:
        product *= item.factor
    suggested = clamp_price(product)
    spread = SPREAD_ANCHORED if source == "comparables" else SPREAD_UNANCHORED
    return Valuation(
        suggested_price_minor=suggested,
        low_price_minor=clamp_price(suggested * (1 - spread)),
        high_price_minor=clamp_price(suggested * (1 + spread)),
        base_price_minor=base,
        base_source=source,
        base_inputs=base_inputs,
        factors=factors,
    )


# --- matching unmet demand to a sliver ------------------------------------------------------

# Words too common in searches to say anything about what a buyer wants.
STOPWORDS = {
    "and", "the", "for", "with", "from", "per", "data", "dataset", "datasets", "daily", "weekly",
    "monthly", "all", "any", "about", "into", "over", "this", "that", "csv", "table", "list", "by",
}  # fmt: skip


def terms(text: str) -> set[str]:
    """Lowercase word stems of at least three characters (a trailing plural "s" is dropped)."""
    found = set()
    for token in "".join(char if char.isalnum() else " " for char in text.casefold()).split():
        if len(token) < 3 or token in STOPWORDS:
            continue
        found.add(token[:-1] if len(token) > 3 and token.endswith("s") else token)
    return found


def matching_demand(listing_text: str, demand: list[dict]) -> tuple[DemandMatch, ...]:
    """Unmet searches (`catalog.search.unmet_demand` items) whose terms this listing mostly covers.

    A search matches when at least half of its terms (rounded up) appear in the listing text.
    """
    listing = terms(listing_text)
    matches = []
    for item in demand:
        wanted = terms(item["query"])
        if not wanted or item.get("unmet_searches", 0) <= 0:
            continue
        if len(wanted & listing) >= math.ceil(len(wanted) / 2):
            matches.append(DemandMatch(item["query"], int(item["unmet_searches"])))
    return tuple(sorted(matches, key=lambda match: match.query))
