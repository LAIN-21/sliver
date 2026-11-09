"""Regenerate the synthetic demo datasets: `python3 examples/datasets/generate.py`.

Every value is simulated with a fixed seed. Terminal and route names are real places, but
none of the numbers describe real operations.
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent


def write(name: str, header: list[str], rows: list[list]) -> None:
    with open(HERE / name, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    print(f"{name}: {len(rows)} rows")


def days(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def weeks(start: date, count: int):
    return [start + timedelta(weeks=i) for i in range(count)]


def berth_waiting_times(rng: random.Random) -> None:
    terminals = {"Pasir Panjang": 1.0, "Tuas": 0.7, "Keppel": 1.25, "Brani": 1.1}
    classes = {"feeder": (14, 2.5), "panamax": (6, 5.0), "ultra-large": (3, 9.0)}
    rows = []
    for day in days(date(2026, 8, 1), date(2026, 10, 31)):
        congestion = 1.0 + 0.35 * (day.month == 9) + (0.2 if day.weekday() in (0, 1) else 0.0)
        for terminal, factor in terminals.items():
            for vessel_class, (calls, base_wait) in classes.items():
                vessel_calls = max(0, round(rng.gauss(calls * (1.6 if terminal == "Tuas" else 1.0), 2)))
                average = max(0.2, rng.gauss(base_wait * factor * congestion, base_wait * 0.18))
                p90 = average * rng.uniform(1.6, 2.3)
                rows.append([day.isoformat(), terminal, vessel_class, vessel_calls, round(average, 2), round(p90, 2)])
    write(
        "sg-berth-waiting-times.csv",
        ["date", "terminal", "vessel_class", "vessel_calls", "avg_berth_wait_hours", "p90_berth_wait_hours"],
        rows,
    )


ROUTES = ["SGSIN-IDJKT", "SGSIN-MYPKG", "SGSIN-CNSHA", "SGSIN-VNSGN", "SGSIN-THLCH", "SGSIN-INNSA"]


def route_eta_delays(rng: random.Random) -> None:
    carriers = ["Carrier A", "Carrier B", "Carrier C", "Carrier D"]
    reliability = {route: rng.uniform(0.6, 1.5) for route in ROUTES}
    rows = []
    for week in weeks(date(2026, 7, 6), 17):
        for route in ROUTES:
            for carrier in carriers:
                sailings = rng.randint(1, 6)
                delay = max(0.0, rng.gauss(10 * reliability[route], 4))
                on_time = min(100.0, max(20.0, rng.gauss(88 - delay * 1.8, 6)))
                rows.append([week.isoformat(), route, carrier, sailings, round(delay, 1), round(on_time, 1)])
    write(
        "asia-route-eta-delays.csv",
        ["week_start", "route", "carrier", "sailings", "avg_eta_delay_hours", "on_time_pct"],
        rows,
    )


def container_spot_rates(rng: random.Random) -> None:
    base = {route: rng.uniform(280, 1450) for route in ROUTES}
    rows = []
    for index, week in enumerate(weeks(date(2026, 7, 6), 17)):
        trend = 1 + 0.012 * index
        for route in ROUTES:
            for container_type, multiplier in (("20GP", 1.0), ("40HC", 1.75)):
                rate = base[route] * multiplier * trend * rng.uniform(0.94, 1.06)
                rows.append([week.isoformat(), route, container_type, round(rate)])
    write("container-spot-rates.csv", ["week_start", "lane", "container_type", "usd_per_container"], rows)


def customs_clearance_times(rng: random.Random) -> None:
    chapters = {
        "84": "Machinery and mechanical appliances",
        "85": "Electrical machinery and equipment",
        "27": "Mineral fuels and oils",
        "39": "Plastics and articles thereof",
        "30": "Pharmaceutical products",
        "87": "Vehicles other than railway",
        "90": "Optical and medical instruments",
        "61": "Knitted apparel",
        "22": "Beverages and spirits",
        "71": "Precious stones and metals",
    }
    rows = []
    for month in range(1, 11):
        for chapter, description in chapters.items():
            for mode, base_hours in (("sea", 30.0), ("air", 7.0)):
                shipments = rng.randint(80, 2400) if mode == "sea" else rng.randint(40, 900)
                hours = max(1.0, rng.gauss(base_hours * (1.4 if chapter in ("30", "22", "71") else 1.0), base_hours * 0.15))
                rows.append([f"2026-{month:02d}", chapter, description, mode, shipments, round(hours, 1)])
    write(
        "customs-clearance-times.csv",
        ["month", "hs_chapter", "hs_description", "transport_mode", "shipments", "median_clearance_hours"],
        rows,
    )


if __name__ == "__main__":
    rng = random.Random(20261109)
    berth_waiting_times(rng)
    route_eta_delays(rng)
    container_spot_rates(rng)
    customs_clearance_times(rng)
