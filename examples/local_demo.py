"""Explicit loopback recording adapter; never a production database/storage fallback."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
import uvicorn

from sliver_api.config import Settings
from sliver_api.main import create_app
from sliver_api.seed import DEMO_ACCOUNTS, seed_accounts


class LocalDemoStore:
    """Dedicated private directory, conditional writes and no public file server."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, key: str) -> Path:
        target = (self.root / key).resolve()
        if not target.is_relative_to(self.root) or target == self.root:
            raise ValueError("Invalid private object key")
        return target

    def put(self, key: str, body: bytes) -> None:
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with target.open("xb") as stream:
            stream.write(body)

    def get(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)


def credentials(directory: Path) -> dict[str, str]:
    path = directory / "credentials.json"
    if path.exists():
        result = json.loads(path.read_text(encoding="utf-8"))
        if set(result) != {key for _, _, key in DEMO_ACCOUNTS}:
            raise RuntimeError("Existing recording credentials are invalid; preserve and inspect them.")
        return result
    result = {key: os.environ.get(key) or secrets.token_urlsafe(24)
              for _, _, key in DEMO_ACCOUNTS}
    with path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    path.chmod(0o600)
    return result


def seed_fixture(app, passwords: dict[str, str], directory: Path) -> None:
    marker = directory / "fixtures-ready.json"
    if marker.exists():
        return
    fixture = ROOT / "examples" / "fixtures" / "synthetic-routes.csv"
    data = fixture.read_bytes() if fixture.exists() else (
        b"observed_at,route,delay_minutes,delivered_on_time\n"
        b"2026-11-01,Singapore-Jakarta,10,true\n"
        b"2026-11-02,Singapore-Jakarta,20,false\n"
        b"2026-11-03,Singapore-Jakarta,0,true\n"
        b"2026-11-01,Singapore-Port Klang,30,false\n"
        b"2026-11-02,Singapore-Port Klang,15,true\n"
        b"2026-11-03,Singapore-Port Klang,45,false\n"
    )
    origin = "http://127.0.0.1:5173"

    def login(client, email, password):
        initial = client.get("/api/session").json()
        response = client.post("/api/session", json={"email": email, "password": password},
                               headers={"Origin": origin, "X-CSRF-Token": initial["csrf_token"]})
        response.raise_for_status()
        client.headers.update({"Origin": origin, "X-CSRF-Token": response.json()["csrf_token"]})

    offers = []
    with TestClient(app, client=("127.0.0.1", 41001)) as seller:
        login(seller, "seller-a@sliver.local", passwords["SLIVER_SELLER_A_PASSWORD"])
        for title, price, date in [
            ("Synthetic route performance - demo week", 100, "2026-11-07"),
            ("Synthetic route performance - premium example", 900, "2026-11-07"),
            ("Synthetic route performance - historical example", 50, "2026-10-01"),
        ]:
            provenance = {"source": "Sliver synthetic demonstration fixtures",
                          "method": "Fictional generated records; not observations of real routes",
                          "collected_at": date, "coverage": "Fictional demo data, two routes; not live maritime information",
                          "rights_statement": "Synthetic example authored for this demonstration; no private third-party records"}
            response = seller.post("/api/datasets", files={"file": ("route-performance.csv", data, "text/csv")},
                                   data={"title": title, "provenance": json.dumps(provenance)})
            response.raise_for_status()
            dataset = response.json()
            response = seller.post("/api/resources", json={"dataset_id": dataset["id"], "title": title,
                                   "description": "SYNTHETIC CSV for testing buyer selection and route analysis; no real-world performance claim.",
                                   "price_minor": price, "currency": "USD"})
            response.raise_for_status()
            resource = response.json()
            seller.post(f"/api/resources/{resource['id']}/submit").raise_for_status()
            offers.append(resource["id"])
    with TestClient(app, client=("127.0.0.1", 41002)) as reviewer:
        login(reviewer, "reviewer@sliver.local", passwords["SLIVER_REVIEWER_PASSWORD"])
        for resource_id in offers:
            reviewer.post(f"/api/resources/{resource_id}/review", json={"decision": "approve",
                          "reason": "Reviewed synthetic local recording fixture; no real-data quality or ownership claim"}).raise_for_status()
    marker.write_text(json.dumps({"resources": offers}), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".sliver-demo" / "current")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use a loopback port between 1024 and 65535")
    directory = args.data_dir.resolve()
    marker = directory / ".sliver-demo-marker"
    if directory.exists() and any(directory.iterdir()) and not marker.exists():
        raise RuntimeError("Use a new dedicated data directory; refusing an unmarked nonempty directory")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker.touch(exist_ok=True)
    passwords = credentials(directory)
    database_url = "sqlite:///" + (directory / "demo.sqlite3").as_posix()
    engine = create_engine(database_url, connect_args={"check_same_thread": False, "timeout": 30})

    schema = inspect(engine)
    if "quotes" in schema.get_table_names():
        columns = {column["name"] for column in schema.get_columns("quotes")}
        unique = schema.get_unique_constraints("quotes")
        if "settled_transaction_hash" not in columns or any(
            rule.get("column_names") == ["transaction_hash"] for rule in unique
        ):
            engine.dispose()
            raise RuntimeError("Recording database uses an earlier unreleased quote schema. Preserve it and select a NEW --data-dir; no data was reset.")

    @event.listens_for(engine, "connect")
    def sqlite_settings(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")

    seed_accounts(engine, passwords)
    settings = Settings(database_url=database_url, payment_mode="simulated")
    app = create_app(settings, engine=engine, store=LocalDemoStore(directory / "private-objects"))
    seed_fixture(app, passwords, directory)
    print("SIMULATED / NO REAL MONEY - explicit SQLite/local-file recording adapter", flush=True)
    print(f"API: http://127.0.0.1:{args.port} | UI: http://127.0.0.1:5173", flush=True)
    print(f"Local credentials are in {directory / 'credentials.json'}; never commit or record this file.", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
