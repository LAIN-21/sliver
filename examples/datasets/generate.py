"""Regenerate the synthetic demo datasets: `python3 examples/datasets/generate.py`.

Every value is simulated with a fixed seed. Terminal, zone and route names are real places, but
none of the numbers describe real operations, volumes, tariffs, rents or wages.
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


def months(start: tuple[int, int], count: int) -> list[tuple[int, int]]:
    year, month = start
    result = []
    for _ in range(count):
        result.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


# November 2024 to October 2026: the 24 months before the demo catalog was collected.
LAST_24_MONTHS = months((2024, 11), 24)


def port_container_throughput(rng: random.Random) -> None:
    # terminal: (base TEU per month, monthly growth, transshipment share, TEU exchanged per call,
    #            average vessel size in TEU). Simulated magnitudes, not official statistics.
    terminals = {
        "Pasir Panjang": (1_480_000, 0.000, 0.89, 2_450, 9_600),
        "Tuas": (980_000, 0.018, 0.91, 3_300, 13_200),
        "Keppel": (430_000, -0.012, 0.86, 1_750, 6_100),
        "Brani": (340_000, -0.015, 0.87, 1_500, 5_300),
        "Jurong Port": (52_000, 0.004, 0.25, 420, 1_900),
    }
    # Lunar New Year dip in February, peak season from August to October.
    season = {2: 0.93, 8: 1.03, 9: 1.04, 10: 1.03}
    rows = []
    for index, (year, month) in enumerate(LAST_24_MONTHS):
        for terminal, (base, growth, transshipment_share, per_call, vessel_size) in terminals.items():
            total = base * (1 + growth) ** index * season.get(month, 1.0) * rng.uniform(0.96, 1.04)
            transshipment = round(total * min(0.97, max(0.0, rng.gauss(transshipment_share, 0.01))))
            gateway = round(total) - transshipment
            imports = round(gateway * rng.uniform(0.49, 0.55))
            exports = gateway - imports
            calls = max(1, round(total / (per_call * rng.uniform(0.94, 1.06))))
            size = round(vessel_size * (1 + 0.002 * index) * rng.uniform(0.97, 1.03))
            rows.append(
                [f"{year}-{month:02d}", terminal, imports, exports, transshipment, round(total), calls, size]
            )
    write(
        "sg-port-container-throughput.csv",
        [
            "month",
            "terminal",
            "import_teu",
            "export_teu",
            "transshipment_teu",
            "total_teu",
            "vessel_calls",
            "avg_vessel_size_teu",
        ],
        rows,
    )


def port_business_operating_costs(rng: random.Random) -> None:
    # (cost_category, item, zone_or_type, unit, SGD amount in November 2024, yearly drift).
    # Simulated benchmarks, not real tariffs or quotes.
    items = [
        ("terminal handling charges", "dry container, laden", "20ft", "SGD per container", 205.0, 0.03),
        ("terminal handling charges", "dry container, laden", "40ft", "SGD per container", 300.0, 0.03),
        ("terminal handling charges", "reefer container, laden", "20ft", "SGD per container", 265.0, 0.03),
        ("terminal handling charges", "reefer container, laden", "40ft", "SGD per container", 390.0, 0.03),
        ("port dues", "ocean-going container vessel", "per call", "SGD per gross ton", 0.098, 0.02),
        ("port dues", "regional feeder vessel", "per call", "SGD per gross ton", 0.122, 0.02),
        ("warehouse rent", "ambient warehouse space", "Jurong", "SGD per sqm per month", 17.8, 0.035),
        ("warehouse rent", "ambient warehouse space", "Tuas", "SGD per sqm per month", 15.2, 0.045),
        ("warehouse rent", "ambient warehouse space", "Pasir Panjang", "SGD per sqm per month", 21.5, 0.03),
        ("warehouse rent", "ambient warehouse space", "Changi", "SGD per sqm per month", 19.9, 0.03),
        ("warehouse rent", "cold-store warehouse space", "Jurong", "SGD per sqm per month", 33.0, 0.035),
        ("warehouse rent", "cold-store warehouse space", "Tuas", "SGD per sqm per month", 29.5, 0.045),
        ("warehouse rent", "cold-store warehouse space", "Pasir Panjang", "SGD per sqm per month", 38.0, 0.03),
        ("warehouse rent", "cold-store warehouse space", "Changi", "SGD per sqm per month", 35.5, 0.03),
        ("trucking", "container haulage, port to warehouse", "20ft", "SGD per trip", 215.0, 0.04),
        ("trucking", "container haulage, port to warehouse", "40ft", "SGD per trip", 275.0, 0.04),
        ("trucking", "lorry delivery, 10ft truck", "island-wide", "SGD per trip", 118.0, 0.04),
        ("labour", "forklift operator", "full-time", "SGD per month", 2_750.0, 0.045),
        ("labour", "warehouse assistant", "full-time", "SGD per month", 2_250.0, 0.045),
        ("labour", "prime mover driver", "full-time", "SGD per month", 3_350.0, 0.045),
        ("customs brokerage", "import permit declaration", "per declaration", "SGD per declaration", 45.0, 0.02),
        ("customs brokerage", "export permit declaration", "per declaration", "SGD per declaration", 35.0, 0.02),
        ("customs brokerage", "transshipment permit declaration", "per declaration", "SGD per declaration", 30.0, 0.02),
    ]
    rows = []
    for index, (year, month) in enumerate(LAST_24_MONTHS):
        usd_per_sgd = 0.745 + 0.012 * index / 23 + rng.uniform(-0.006, 0.006)
        for category, item, zone_or_type, unit, base, drift in items:
            # Tariffs, wages and fees step up each January; rents and trucking drift monthly.
            if category in ("terminal handling charges", "port dues", "labour", "customs brokerage"):
                level = (1 + drift) ** (year - 2024)
                noise = 1.0
            else:
                level = (1 + drift) ** (index / 12)
                noise = rng.uniform(0.985, 1.015)
            sgd = base * level * noise
            digits = 4 if sgd < 1 else 2
            rows.append(
                [
                    f"{year}-{month:02d}",
                    category,
                    item,
                    zone_or_type,
                    unit,
                    f"{sgd:.{digits}f}",
                    f"{sgd * usd_per_sgd:.{digits}f}",
                ]
            )
    write(
        "sg-port-business-operating-costs.csv",
        ["month", "cost_category", "item", "zone_or_type", "unit", "sgd_amount", "usd_amount"],
        rows,
    )


if __name__ == "__main__":
    rng = random.Random(20261109)
    berth_waiting_times(rng)
    route_eta_delays(rng)
    container_spot_rates(rng)
    customs_clearance_times(rng)
    port_container_throughput(rng)
    port_business_operating_costs(rng)
