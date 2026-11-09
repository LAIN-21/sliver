"""A small per-IP budget for custom-slice quotes.

Quoting reads a stored dataset and may write a new object, so each client gets a few per
minute. It is a token bucket in this process's memory, like the per-IP limiter proposed in #37
(`sliver_api/ratelimit.py`): no Redis or queue (docs/agents/infrastructure.md), client addresses
are never logged or stored, IPv6 clients are keyed by their /64, and `X-Forwarded-For` is not
trusted. When #37 merges, this budget can become one of its route budgets.
"""

import ipaddress
import math
import time
from collections.abc import Callable

WINDOW_SECONDS = 60.0
QUOTES_PER_MINUTE = 20
MAX_TRACKED = 10_000


def client_key(host: str | None) -> str:
    try:
        address = ipaddress.ip_address((host or "").strip())
    except ValueError:
        return host or "unknown"
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.IPv6Network((address, 64), strict=False))
    return str(address)


class QuoteBudget:
    """`per_minute` quotes per client, refilled continuously, with a burst of `per_minute`."""

    def __init__(
        self,
        per_minute: int = QUOTES_PER_MINUTE,
        clock: Callable[[], float] = time.monotonic,
        max_tracked: int = MAX_TRACKED,
    ):
        self.per_minute, self.clock, self.max_tracked = per_minute, clock, max_tracked
        self.buckets: dict[str, tuple[float, float]] = {}  # client -> (tokens, updated)

    def take(self, host: str | None) -> int:
        """Spend one quote. Returns 0 when allowed, otherwise the seconds until one is available."""
        now, key = self.clock(), client_key(host)
        rate = self.per_minute / WINDOW_SECONDS
        tokens, updated = self.buckets.get(key, (float(self.per_minute), now))
        tokens = min(float(self.per_minute), tokens + (now - updated) * rate)
        if key not in self.buckets and len(self.buckets) >= self.max_tracked:
            self._evict(now)
        if tokens >= 1:
            self.buckets[key] = (tokens - 1, now)
            return 0
        self.buckets[key] = (tokens, now)
        return max(1, math.ceil((1 - tokens) / rate))

    def _evict(self, now: float) -> None:
        # A bucket idle for a whole window is full again, so forgetting it changes nothing.
        for key in [key for key, (_t, updated) in self.buckets.items() if now - updated >= WINDOW_SECONDS]:
            del self.buckets[key]
        if len(self.buckets) >= self.max_tracked:
            for key in list(self.buckets)[: len(self.buckets) // 2]:
                del self.buckets[key]
