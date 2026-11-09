"""Shared CSV parsing and the finding/result shapes every stage returns."""

import csv
import io
import re
from dataclasses import dataclass, field

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000
MAX_COLUMNS = 100
MAX_FIELD_CHARS = 10_000
MAX_HEADER_CHARS = 160
# Findings cite at most this many example rows; counts stay exact.
MAX_EXAMPLE_ROWS = 5

# "high" blocks publication and fails the stage; "medium" and "low" are warnings.
SEVERITIES = ("high", "medium", "low")


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]

    def column(self, index: int) -> list[str]:
        return [row[index] for row in self.rows]


def decode(data: bytes) -> str:
    return data.decode("utf-8-sig")


def read_table(data: bytes) -> Table:
    """Parse a CSV that already passed validation."""
    reader = csv.reader(io.StringIO(decode(data), newline=""), strict=True)
    header = next(reader)
    return Table(header=header, rows=[row for row in reader])


def count(number: int, noun: str) -> str:
    return f"{number:,} {noun}" + ("" if number == 1 else "s")


def finding(code: str, severity: str, message: str, *, column: str | None = None, **extra) -> dict:
    assert severity in SEVERITIES
    item = {"code": code, "severity": severity, "message": message}
    if column is not None:
        item["column"] = column
    item.update(extra)
    return item


@dataclass
class StageResult:
    summary: str
    findings: list[dict] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    # Dataset fields this stage established (for example row_count or columns).
    dataset_updates: dict = field(default_factory=dict)
    # New rows (for example packaged Resources) that `jobs.finish` adds with the result.
    records: list = field(default_factory=list)
    # Fields `jobs.finish` sets on every Resource of the dataset (for example status).
    resource_updates: dict = field(default_factory=dict)
    # The stage chose not to run (for example research while it is turned off).
    skipped: bool = False

    @property
    def status(self) -> str:
        if self.skipped:
            return "skipped"
        severities = {item["severity"] for item in self.findings}
        if "high" in severities:
            return "failed"
        return "warning" if severities else "passed"

    def to_json(self) -> dict:
        return {"summary": self.summary, "findings": self.findings, "details": self.details}


NUMBER = re.compile(r"[+-]?(?:\d+(?:[.,]\d+)*(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?%?")


def looks_like_formula(value: str) -> bool:
    """Cells a spreadsheet would evaluate. Plain numbers such as -12.5 or +3 are data, not formulas."""
    if value[:1] in ("\t", "\r"):
        return True
    stripped = value.strip()
    if not stripped or stripped[0] not in "=+-@":
        return False
    if stripped[0] in "+-" and (NUMBER.fullmatch(stripped) or stripped in ("+", "-")):
        return False
    return True
