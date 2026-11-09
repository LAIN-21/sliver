"""Synthetic daily anchorage waiting times at the Port of Singapore for `make demo`.

    python3 examples/demo/generate.py [RUN_ID] [OUT.csv]

Every demo run uploads a table that is new to the catalog: one row per day for the six whole
calendar months before the run's month, drawn from a generator seeded by the run id. Two runs
never share rows, so a re-run is not sent to the reviewer as a duplicate of an earlier one.

The table is shaped so that the only valid way to slice it is by calendar month of `date`,
whether Claude or the offline rule chooses: `port` holds a single value and every other column
is a decimal. Ports work every day and only whole months are included, so every month's sliver
covers its whole month, and the demo's buyer question ("last month") is met by exactly one sliver.

None of the numbers describe real operations. Without arguments it prints a table for today with
run id "manual", for example to upload by hand at /sell/upload.
"""

import csv
import io
import math
import random
import sys
from datetime import date, timedelta

PORT = "Singapore"
# Typical waiting hours at anchorage before berthing, by vessel type.
WAITS = {"container_ship": 6.0, "tanker": 18.0, "bulk_carrier": 26.0}
HEADER = [
    "date",
    "port",
    *(f"{kind}_avg_anchorage_wait_hours" for kind in WAITS),
    "avg_vessels_at_anchorage",
]
MONTHS = 6


def days(today: date, months: int = MONTHS) -> list[date]:
    """Every day of the `months` whole calendar months before the month of `today`."""
    last = today.replace(day=1) - timedelta(days=1)
    first = last.replace(day=1)
    for _ in range(months - 1):
        first = (first - timedelta(days=1)).replace(day=1)
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def rows(run_id: str, today: date) -> list[list[str]]:
    rng = random.Random(f"sliver-demo:{run_id}")  # noqa: S311 - simulated data, not security
    congestion = 1.0
    table = []
    for day in days(today):
        # Slow-moving congestion, a weekly rhythm, and daily noise per vessel type.
        congestion = min(1.8, max(0.6, congestion + rng.gauss(0.0, 0.04)))
        weekly = 1 + 0.08 * math.sin(2 * math.pi * day.weekday() / 7)
        waits = [max(0.5, base * congestion * weekly * rng.uniform(0.8, 1.2)) for base in WAITS.values()]
        vessels = 95 * congestion * rng.uniform(0.9, 1.1)
        table.append([day.isoformat(), PORT, *(f"{wait:.2f}" for wait in waits), f"{vessels:.1f}"])
    return table


def generate(run_id: str, today: date) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(HEADER)
    writer.writerows(rows(run_id, today))
    return buffer.getvalue().encode("utf-8")


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "manual"
    data = generate(run_id, date.today())
    if len(sys.argv) > 2:
        with open(sys.argv[2], "wb") as handle:
            handle.write(data)
    else:
        sys.stdout.write(data.decode("utf-8"))


if __name__ == "__main__":
    main()
