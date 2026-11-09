"""Deterministic fit report: does a listing cover the buyer's need, and is it worth buying?

Only public listing metadata is used, so the report never needs, or spends, anything. The same
listings, need and date always give the same report.

Per listing:
- look_elsewhere: it does not cover the need (missing required columns or terms, no overlap
  with the requested time range, or too few of the need's terms in its metadata).
- skip: it covers the need but a buyer constraint fails (no budget, over budget, stale).
- buy: it covers the need and fits the budget.
"""

import calendar
import re
from datetime import date
from typing import Any

MIN_TERM_COVERAGE = 0.6
STOPWORDS = frozenset(
    "a about all an and any are as at between by data dataset datasets for from get i in into is it "
    "latest me my need of on or per some the to via vs want we with".split()
)


def stem(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith("s") and not token.endswith("ss") else token


def terms(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        if token not in STOPWORDS:
            seen[stem(token)] = None
    return list(seen)


def column_key(name: str) -> str:
    return "_".join(re.findall(r"[a-z0-9]+", name.lower()))


def parse_day(value: str, *, end: bool) -> date:
    """YYYY, YYYY-MM or YYYY-MM-DD as a date; partial dates expand to the first or last day."""
    parts = [int(part) for part in value.strip()[:10].split("-")]
    if len(parts) == 1:
        return date(parts[0], 12, 31) if end else date(parts[0], 1, 1)
    if len(parts) == 2:
        year, month = parts
        return date(year, month, calendar.monthrange(year, month)[1] if end else 1)
    return date(*parts[:3])


def requested_day(value: str | None, name: str, *, end: bool) -> date | None:
    if not value:
        return None
    try:
        return parse_day(value, end=end)
    except ValueError:
        raise ValueError(f"{name} must be YYYY, YYYY-MM or YYYY-MM-DD, got {value!r}") from None


def listing_text(listing: dict[str, Any]) -> str:
    coverage = listing.get("coverage") or {}
    pieces = [
        listing.get("title", ""),
        listing.get("description", ""),
        listing.get("category", ""),
        " ".join(listing.get("tags") or []),
        " ".join(column.get("name", "") for column in listing.get("columns") or []),
        str((coverage.get("slice") or {}).get("value", "")),
    ]
    return " ".join(pieces)


def listing_end(listing: dict[str, Any]) -> date | None:
    end = ((listing.get("coverage") or {}).get("time") or {}).get("end")
    collected = (listing.get("provenance") or {}).get("collected_at")
    for value in (end, collected, listing.get("published_at")):
        if value:
            try:
                return parse_day(str(value), end=True)
            except ValueError:
                continue
    return None


def evaluate_listing(
    listing: dict[str, Any],
    *,
    need: str,
    required_columns: list[str],
    required_terms: list[str],
    time_start: str | None,
    time_end: str | None,
    max_age_days: int | None,
    budget_minor: int | None,
    today: date,
) -> dict[str, Any]:
    gaps: list[str] = []  # the listing does not cover the need
    blockers: list[str] = []  # it covers the need, but the buyer should not buy it now
    notes: list[str] = []

    columns = {column_key(column.get("name", "")) for column in listing.get("columns") or []}
    missing_columns = [name for name in required_columns if column_key(name) not in columns]
    if missing_columns:
        gaps.append(f"missing required columns: {', '.join(missing_columns)}")
    column_coverage = 1 - len(missing_columns) / len(required_columns) if required_columns else 1.0

    available = set(terms(listing_text(listing)))
    wanted = terms(need)
    matched = [term for term in wanted if term in available]
    term_coverage = len(matched) / len(wanted) if wanted else 1.0
    if wanted and term_coverage < MIN_TERM_COVERAGE:
        unmatched = [term for term in wanted if term not in available]
        gaps.append(f"metadata does not mention: {', '.join(unmatched)}")
    missing_terms = [term for term in required_terms if not set(terms(term)) <= available]
    if missing_terms:
        gaps.append(f"metadata does not mention required terms: {', '.join(missing_terms)}")

    time_overlap = None
    if time_start or time_end:
        window = (listing.get("coverage") or {}).get("time") or {}
        try:
            have_start = parse_day(str(window["start"]), end=False)
            have_end = parse_day(str(window["end"]), end=True)
        except (KeyError, TypeError, ValueError):
            have_start = have_end = None
        if have_start is None or have_end is None:
            gaps.append("no readable time coverage to compare with the requested range")
        else:
            # An open side of the requested range means "whatever the listing has".
            want_start = requested_day(time_start, "time_start", end=False) or have_start
            want_end = requested_day(time_end, "time_end", end=True) or have_end
            overlap = (min(want_end, have_end) - max(want_start, have_start)).days + 1
            requested = (want_end - want_start).days + 1
            time_overlap = round(max(overlap, 0) / max(requested, 1), 3)
            if overlap <= 0:
                gaps.append(f"covers {window['start']} to {window['end']}, outside the requested range")
            elif time_overlap < 1:
                notes.append(
                    f"covers {time_overlap:.0%} of the requested range ({window['start']} to {window['end']})"
                )

    end = listing_end(listing)
    age_days = (today - end).days if end else None
    if max_age_days is not None:
        if age_days is None:
            notes.append("freshness unknown")
        elif age_days > max_age_days:
            blockers.append(f"data ends {age_days} days ago, older than the {max_age_days}-day limit")

    price_minor = (listing.get("price") or {}).get("amount_minor")
    if budget_minor is None:
        blockers.append("no budget given: ask your human for one before buying")
    elif price_minor is None or price_minor > budget_minor:
        blockers.append(
            f"price ${(price_minor or 0) / 100:.2f} exceeds the ${budget_minor / 100:.2f} budget: "
            "ask your human before spending more"
        )

    verdict = "look_elsewhere" if gaps else "skip" if blockers else "buy"
    score = (
        0.4 * column_coverage + 0.4 * term_coverage + 0.2 * (1.0 if time_overlap is None else time_overlap)
    )
    return {
        "resource_id": listing.get("id"),
        "title": listing.get("title"),
        "price_usd": None if price_minor is None else price_minor / 100,
        "verdict": verdict,
        "score": round(score, 3),
        "column_coverage": round(column_coverage, 3),
        "term_coverage": round(term_coverage, 3),
        "matched_terms": matched,
        "time_overlap": time_overlap,
        "data_age_days": age_days,
        "reasons": gaps + blockers + notes,
    }


def evaluate(listings: list[dict[str, Any]], *, need: str, today: date, **criteria: Any) -> dict[str, Any]:
    requested_day(criteria.get("time_start"), "time_start", end=False)  # clear error before any listing
    requested_day(criteria.get("time_end"), "time_end", end=True)
    reports = [evaluate_listing(listing, need=need, today=today, **criteria) for listing in listings]
    rank = {"buy": 0, "skip": 1, "look_elsewhere": 2}
    reports.sort(key=lambda r: (rank[r["verdict"]], -r["score"], r["price_usd"] or 0, r["title"] or ""))
    best = reports[0] if reports else None
    if best and best["verdict"] == "buy":
        recommendation = "buy"
        summary = f"Buy {best['title']!r} (${best['price_usd']:.2f}): it covers the need within budget."
    elif best and best["verdict"] == "skip":
        recommendation = "skip"
        summary = (
            f"{best['title']!r} covers the need but should not be bought now: {'; '.join(best['reasons'])}."
        )
    else:
        recommendation = "look_elsewhere"
        summary = (
            "Nothing on Sliver covers this need. Say so plainly and look for another source; "
            "do not buy a near miss."
        )
    return {
        "need": need,
        "recommendation": recommendation,
        "best": best["resource_id"] if best and recommendation != "look_elsewhere" else None,
        "summary": summary,
        "candidates": reports,
        "spent": 0,
    }
