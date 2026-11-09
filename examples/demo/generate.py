"""Synthetic bunker fuel prices for `make demo`: `python3 examples/demo/generate.py [RUN_ID] [OUT]`.

Every demo run uploads a table that is new to the catalog: weekly prices for the 26 weeks up to
the run's week, with values drawn from a generator seeded by the run id. Two runs never share
rows, so a re-run is not sent to the reviewer as a duplicate of an earlier run. Port names and
fuel grades are real; none of the numbers describe real prices.

Without arguments it prints a table for today with run id "manual", for example to upload by
hand at /sell/upload.
"""

import csv
import io
import random
import sys
from datetime import date, timedelta

HEADER = ["week_start", "port", "fuel_grade", "bunker_price_usd_per_tonne", "supplier_quotes"]
# Port price level relative to the regional average.
PORTS = {"Singapore": 1.0, "Fujairah": 0.985, "Rotterdam": 0.97, "Busan": 1.035, "Hong Kong": 1.045}
# Starting price in USD per tonne.
GRADES = {"VLSFO": 612.0, "HSFO": 468.0, "MGO": 765.0}
WEEKS = 26


def week_starts(today: date, count: int = WEEKS) -> list[date]:
    """The Mondays of the `count` weeks up to and including the week of `today`."""
    last = today - timedelta(days=today.weekday())
    return [last - timedelta(weeks=count - 1 - index) for index in range(count)]


def rows(run_id: str, today: date) -> list[list[str]]:
    rng = random.Random(f"sliver-demo:{run_id}")  # noqa: S311 - simulated data, not security
    level = dict(GRADES)
    table = []
    for week in week_starts(today):
        for grade in GRADES:
            # A shared weekly move per grade, then port-level noise around it.
            level[grade] = max(GRADES[grade] * 0.6, level[grade] * (1 + rng.gauss(0.0, 0.018)))
        for port, factor in PORTS.items():
            for grade in GRADES:
                price = level[grade] * factor * (1 + rng.gauss(0.0, 0.006))
                quotes = max(2, round(rng.gauss(9 if port == "Singapore" else 6, 2)))
                table.append([week.isoformat(), port, grade, f"{price:.2f}", str(quotes)])
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
