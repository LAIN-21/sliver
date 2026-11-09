"""Which columns are public-safe categories, and the guard that keeps raw cell values out of public text.

Titles, descriptions, tags and categories are shown in discovery before anyone pays, so they may
name columns and the values of low-cardinality category columns (a port, a route, a month), but
never other cell values. The guard reports offending columns, never the values it found.
"""

from collections.abc import Iterable

from .table import Table

# A category column has at most this many distinct values, each at most this long.
MAX_CATEGORIES = 50
MAX_CATEGORY_CHARS = 40
# Shorter values ("12", "yes") are too common in ordinary prose to count as a leak.
MIN_VALUE_CHARS = 4
MAX_VALUE_WORDS = 12
TEMPORAL = ("date", "month")
EDGE_PUNCTUATION = ".,;:!?()[]{}<>\"'“”‘’«»`*"


def flagged_columns(privacy_findings: list[dict]) -> set[str]:
    """Columns the privacy scan flagged; their values are never public, even when categorical."""
    return {item["column"] for item in privacy_findings if item.get("column")}


def is_categorical(column: dict, row_count: int, flagged: set[str]) -> bool:
    """`column` is a profile entry (see pipeline/profile.py)."""
    if column["name"] in flagged or column["type"] in (*TEMPORAL, "decimal"):
        return False
    if column["distinct"] > MAX_CATEGORIES or column["distinct"] * 2 > row_count:
        return False
    return column["type"] == "integer" or column.get("max_length", 0) <= MAX_CATEGORY_CHARS


def words(text: str) -> list[str]:
    return [token for token in (raw.strip(EDGE_PUNCTUATION) for raw in text.casefold().split()) if token]


class LeakGuard:
    def __init__(
        self,
        table: Table,
        profile: list[dict],
        flagged: set[str],
        allowed: Iterable[str] = (),
    ):
        """`allowed` lists strings that are public anyway (column names, counts, coverage dates)."""
        public = {" ".join(words(text)) for text in allowed}
        public.update(" ".join(words(name)) for name in table.header)
        by_name = {column["name"]: column for column in profile}
        self.values: dict[str, str] = {}
        for index, name in enumerate(table.header):
            column = by_name.get(name)
            if column is None:
                continue
            if name not in flagged and (
                column["type"] in TEMPORAL or is_categorical(column, len(table.rows), flagged)
            ):
                continue  # dates are public coverage; category values name public slivers
            for cell in table.column(index):
                value = " ".join(words(cell))
                if (
                    len(value) >= MIN_VALUE_CHARS
                    and value not in public
                    and value.count(" ") < MAX_VALUE_WORDS
                ):
                    self.values.setdefault(value, name)
        self.longest = max((value.count(" ") + 1 for value in self.values), default=0)

    def leaks(self, text: str) -> list[str]:
        """Columns whose raw values appear in `text` (as whole words), in header order of discovery."""
        tokens = words(text)
        columns: list[str] = []
        for size in range(1, self.longest + 1):
            for start in range(len(tokens) - size + 1):
                column = self.values.get(" ".join(tokens[start : start + size]))
                if column and column not in columns:
                    columns.append(column)
        return columns


def public_texts(listing: dict) -> dict[str, str]:
    """The public fields of a listing as texts the guard can check."""
    return {
        "title": listing["title"],
        "description": listing["description"],
        "category": listing["category"],
        "tags": " ; ".join(listing["tags"]),
    }


def number_forms(*numbers: int) -> set[str]:
    return {form for number in numbers for form in (str(number), f"{number:,}")}
