"""Cutting a table into slivers: the full dataset plus one piece per column value or calendar month.

Shared by the demo seed and the seller pipeline's `package` stage. Each piece becomes its own
immutable CSV object with its own SHA-256, so the helpers here are deterministic: the same rows
and the same slice choice always produce the same bytes.
"""

import csv
import hashlib
import io
import re
from dataclasses import dataclass

from .storage import ObjectExistsError, ObjectStore

MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def infer_type(values: list[str]) -> str:
    present = [value for value in values if value.strip()]
    if not present:
        return "text"
    for kind, pattern in (
        ("integer", r"-?\d+"),
        ("decimal", r"-?\d+(\.\d+)?"),
        ("date", r"\d{4}-\d{2}-\d{2}"),
        ("month", r"\d{4}-\d{2}"),
    ):
        if all(re.fullmatch(pattern, value) for value in present):
            return kind
    return "text"


def to_csv(header: list[str], rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def month_label(value: str) -> str:
    year, month = value[:7].split("-")
    return f"{MONTHS[int(month) - 1]} {year}"


def describe(header: list[str], rows: list[list[str]]) -> list[dict]:
    return [{"name": name, "type": infer_type([row[i] for row in rows])} for i, name in enumerate(header)]


def coverage(header: list[str], rows: list[list[str]], time_column: str | None) -> dict:
    result: dict = {}
    if time_column and time_column in header:
        index = header.index(time_column)
        values = sorted(row[index] for row in rows if row[index])
        if values:
            result["time"] = {"column": time_column, "start": values[0], "end": values[-1]}
    return result


@dataclass(frozen=True)
class Piece:
    """One sliver: `key` names its object, `label` is the public slice name."""

    key: str
    label: str
    filter: dict | None
    rows: list[list[str]]


def plan(header: list[str], rows: list[list[str]], column: str | None, period: str | None) -> list[Piece]:
    """The full dataset first, then one piece per value of `column` (or per month when period="month")."""
    pieces = [Piece("full", "full dataset", None, rows)]
    if not column:
        return pieces
    index = header.index(column)
    by_month = period == "month"
    groups: dict[str, list[list[str]]] = {}
    for row in rows:
        value = row[index].strip()
        if not value:
            continue
        groups.setdefault(value[:7] if by_month else value, []).append(row)
    used = {"full"}
    for value, group in sorted(groups.items()):
        label = month_label(value) if by_month else value
        key = slug(label) or "slice"
        while key in used:  # keep object keys unique when labels slug alike ("A/B", "A-B")
            key = f"{key}-{len(used)}"
        used.add(key)
        slice_filter = {"column": column, "period": "month" if by_month else None, "value": value}
        pieces.append(Piece(key, label, slice_filter, group))
    return pieces


def piece_coverage(header: list[str], piece: Piece, time_column: str | None) -> dict:
    result = coverage(header, piece.rows, time_column)
    if piece.filter:
        result["slice"] = {"column": piece.filter["column"], "value": piece.label}
    return result


def piece_title(title: str, piece: Piece) -> str:
    return title if piece.filter is None else f"{title}: {piece.label}"


def piece_description(description: str, piece: Piece) -> str:
    return description if piece.filter is None else f"{description} This sliver covers {piece.label} only."


def search_text(category: str, tags: list[str], header: list[str], label: str) -> str:
    return " ".join([category, *tags, *header, label])


def store_object(store: ObjectStore, key: str, body: bytes, hint: str = "") -> None:
    """Write once; an existing object is accepted only when it holds exactly the same bytes."""
    try:
        store.put(key, body)
    except ObjectExistsError:
        if hashlib.sha256(store.get(key)).hexdigest() != hashlib.sha256(body).hexdigest():
            raise RuntimeError(f"stored object {key} differs from the bytes being written{hint}") from None
