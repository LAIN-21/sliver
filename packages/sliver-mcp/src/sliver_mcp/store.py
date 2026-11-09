"""Local buyer state in `~/.sliver/`: wallet, spend ledger, pinned payees, the in-flight lock.

Everything is owner-only (directory 0700, files 0600) and written atomically. Nothing here is
ever sent anywhere.
"""

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

# Statuses where a signed payment left this machine and may have moved funds.
SPENDING_STATUSES = frozenset({"pending", "delivered", "delivered_unverified", "failed"})


class PurchaseInFlight(RuntimeError):
    pass


def now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class Store:
    def __init__(self, home: Path):
        self.home = home
        self._lock = threading.Lock()

    def ensure(self) -> Path:
        self.home.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.home, 0o700)
        return self.home

    def read_json(self, name: str, default: Any) -> Any:
        path = self.home / name
        if not path.exists():
            return default
        return json.loads(path.read_text())

    def write_json(self, name: str, value: Any) -> Path:
        path = self.ensure() / name
        temporary = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        return path

    # Spend ledger

    def purchases(self) -> list[dict[str, Any]]:
        return self.read_json("purchases.json", [])

    def save_purchase(self, record: dict[str, Any]) -> None:
        records = [item for item in self.purchases() if item["id"] != record["id"]]
        self.write_json("purchases.json", [*records, record])

    def spent_minor(self, window: timedelta = timedelta(hours=24), at: datetime | None = None) -> int:
        since = (at or now()) - window
        return sum(
            item["price_minor"]
            for item in self.purchases()
            if item["status"] in SPENDING_STATUSES and datetime.fromisoformat(item["created_at"]) >= since
        )

    # Payees pinned on first payment to a seller (trust on first use)

    def payee(self, key: str) -> str | None:
        return self.read_json("payees.json", {}).get(key)

    def pin_payee(self, key: str, address: str) -> None:
        payees = self.read_json("payees.json", {})
        payees[key] = address
        self.write_json("payees.json", payees)

    # One purchase at a time, across threads and across MCP processes on this machine

    @contextmanager
    def one_purchase(self) -> Iterator[None]:
        if not self._lock.acquire(blocking=False):
            raise PurchaseInFlight("Another purchase is in flight; wait for it to finish.")
        try:
            handle = open(self.ensure() / "purchase.lock", "a")  # noqa: SIM115
            try:
                if fcntl is not None:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise PurchaseInFlight(
                            "Another Sliver MCP on this machine is buying; wait for it to finish."
                        ) from None
                yield
            finally:
                handle.close()
        finally:
            self._lock.release()
