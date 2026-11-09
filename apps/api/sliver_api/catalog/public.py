"""The only serializer allowed to describe a Resource to the public.

It is an explicit allow-list: new model fields stay private until they are added here on
purpose. Discovery must never expose protected data (docs/PRODUCT.md), so object keys,
filenames, raw rows, owner emails and rights statements are never included. The one exception
to "no raw rows" is `sample_rows`: rows the seller explicitly selected to make public when
publishing (#15). It is empty unless they chose some, and the privacy-flagged rows are refused.

Custom slices (#39) are described by the same allow-list, plus their parent id and normalized
filter (dates and values of public-safe category columns only). A quote adds the price
breakdown and nothing else: counts, coverage, price and hash, never row values.
"""

from datetime import datetime

from ..models import Resource

PUBLIC_PROVENANCE_FIELDS = ("source", "method", "collected_at")
PUBLIC_COVERAGE_FIELDS = {"time": ("column", "start", "end"), "slice": ("column", "value")}


def iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def public_coverage(coverage: dict) -> dict:
    return {
        section: {key: coverage[section][key] for key in keys if key in coverage[section]}
        for section, keys in PUBLIC_COVERAGE_FIELDS.items()
        if isinstance(coverage.get(section), dict)
    }


def public_resource(
    resource: Resource, seller_name: str, provenance: dict, *, custom_slices: bool = False
) -> dict:
    """`custom_slices`: whether buyers may quote custom slices of this (full-dataset) listing."""
    return {
        "id": resource.id,
        "title": resource.title,
        "description": resource.description,
        "category": resource.category,
        "tags": list(resource.tags),
        "columns": [{"name": column["name"], "type": column["type"]} for column in resource.columns],
        "row_count": resource.row_count,
        "coverage": public_coverage(resource.coverage),
        "price": {"amount_minor": resource.price_minor, "currency": resource.currency},
        "seller": {"name": seller_name},
        "provenance": {key: provenance[key] for key in PUBLIC_PROVENANCE_FIELDS if key in provenance},
        # Lets a buyer verify the bytes it receives after paying; reveals nothing about content.
        "content": {"sha256": resource.sha256, "size_bytes": resource.size_bytes, "format": "text/csv"},
        # Only rows the seller selected for public view; column order matches `columns`.
        "sample_rows": [[str(cell) for cell in row] for row in resource.sample_rows or []],
        "published_at": iso(resource.published_at),
        # Set only on a buyer-defined custom slice: the listing it was cut from and the filter.
        "derived_from": (
            {"id": resource.parent_id, "filter": dict(resource.custom_filter or {})}
            if resource.parent_id
            else None
        ),
        "custom_slices": {"available": custom_slices},
    }


PUBLIC_BREAKDOWN_FIELDS = (
    "price_minor",
    "reference_price_minor",
    "reference_rows",
    "rows",
    "rate_minor_per_row",
    "prorated_minor",
    "floor_minor",
    "cap_minor",
    "rule",
)


def public_quote(
    resource: Resource,
    parent: Resource,
    seller_name: str,
    breakdown: dict,
    created: bool,
    payment: dict,
    validity: dict,
) -> dict:
    """The answer to a custom-slice quote: what will be sold, for how much and how to verify it.

    `payment` is the XRP amount at the disclosed demo rate; `validity` says how long it holds.
    Enough for an agent to tell its human "$X for N rows × M columns" before buying.
    """
    return {
        "id": resource.id,
        "created": created,
        "parent": {"id": parent.id, "title": parent.title},
        "filter": dict(resource.custom_filter or {}),
        "row_count": resource.row_count,
        "columns": [{"name": column["name"], "type": column["type"]} for column in resource.columns],
        "column_count": len(resource.columns),
        "coverage": public_coverage(resource.coverage),
        "price": {"amount_minor": resource.price_minor, "currency": resource.currency},
        "payment": payment,
        "validity": validity,
        "price_breakdown": {key: breakdown[key] for key in PUBLIC_BREAKDOWN_FIELDS if key in breakdown},
        "seller": {"name": seller_name},
        "content": {"sha256": resource.sha256, "size_bytes": resource.size_bytes, "format": "text/csv"},
        "purchase": {"method": "GET", "path": f"/api/resources/{resource.id}/data", "protocol": "x402"},
    }
