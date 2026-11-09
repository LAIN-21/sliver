"""The only serializer allowed to describe a Resource to the public.

It is an explicit allow-list: new model fields stay private until they are added here on
purpose. Discovery must never expose protected data (docs/PRODUCT.md), so object keys,
filenames, raw rows, owner emails and rights statements are never included. The one exception
to "no raw rows" is `sample_rows`: rows the seller explicitly selected to make public when
publishing (#15). It is empty unless they chose some, and the privacy-flagged rows are refused.
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


def public_resource(resource: Resource, seller_name: str, provenance: dict) -> dict:
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
    }
