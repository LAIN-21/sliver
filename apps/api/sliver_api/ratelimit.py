"""Per-IP rate limiting for the public endpoints that cost Sliver the most.

A token bucket per (route budget, client) lives in this process's memory: the API runs as one
uvicorn process and the repository adds no Redis (docs/agents/infrastructure.md). Limiting runs
as ASGI middleware before routing, so an over-budget request never reaches a handler, a body
parser or the database. Client addresses stay in memory only; they are never logged or stored.
"""

import ipaddress
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

WINDOW_SECONDS = 60.0
# Bound the memory an address-rotating client can make us hold.
MAX_TRACKED = 50_000

PAYMENT_DATA_PATH = re.compile(r"^/api/resources/[^/]+/data/?$")


@dataclass(frozen=True)
class Budget:
    name: str
    per_minute: int


@dataclass
class _Bucket:
    tokens: float
    updated: float


class TokenBuckets:
    """`per_minute` requests per client, refilled continuously; a burst of up to `per_minute`."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, max_tracked: int = MAX_TRACKED):
        self.clock = clock
        self.max_tracked = max_tracked
        self.buckets: dict[tuple[str, str], _Bucket] = {}

    def take(self, budget: Budget, client: str) -> int:
        """Spend one token. Returns 0 when allowed, otherwise the seconds until one is available."""
        now = self.clock()
        rate = budget.per_minute / WINDOW_SECONDS
        key = (budget.name, client)
        bucket = self.buckets.get(key)
        if bucket is None:
            if len(self.buckets) >= self.max_tracked:
                self._evict(now)
            bucket = self.buckets[key] = _Bucket(tokens=float(budget.per_minute), updated=now)
        else:
            bucket.tokens = min(budget.per_minute, bucket.tokens + (now - bucket.updated) * rate)
            bucket.updated = now
        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return 0
        return max(1, math.ceil((1 - bucket.tokens) / rate))

    def _evict(self, now: float) -> None:
        # A bucket idle for a whole window is full again, so forgetting it changes nothing.
        idle = [key for key, bucket in self.buckets.items() if now - bucket.updated >= WINDOW_SECONDS]
        for key in idle:
            del self.buckets[key]
        if len(self.buckets) >= self.max_tracked:
            # Still full of active clients: forget the oldest half rather than grow without bound.
            for key in list(self.buckets)[: len(self.buckets) // 2]:
                del self.buckets[key]


Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_networks(value: str) -> tuple[Network, ...]:
    """Comma-separated IPs or CIDR ranges. Raises ValueError on anything else."""
    items = [item.strip() for item in value.split(",") if item.strip()]
    return tuple(ipaddress.ip_network(item, strict=False) for item in items)


def _address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def client_key(scope: Scope, trusted: tuple[Network, ...]) -> str:
    """The address to limit. `X-Forwarded-For` counts only when the peer is a trusted proxy.

    The forwarded chain is read from the right, skipping trusted proxies, so a client cannot pick
    its own key by prepending addresses. IPv6 clients are keyed by their /64, which one host
    usually controls entirely.
    """
    peer = (scope.get("client") or ("unknown", 0))[0]
    address = _address(peer)
    if address is None:
        return peer
    if trusted and any(address in network for network in trusted):
        forwarded = ",".join(Headers(scope=scope).getlist("x-forwarded-for"))
        for hop in reversed([part for part in forwarded.split(",") if part.strip()]):
            hop_address = _address(hop)
            if hop_address is None:
                break  # malformed chain: fall back to the last trusted address we saw
            address = hop_address
            if not any(address in network for network in trusted):
                break
    if isinstance(address, ipaddress.IPv6Address):
        return str(ipaddress.IPv6Network((address, 64), strict=False))
    return str(address)


@dataclass(frozen=True)
class RateLimitConfig:
    login: Budget
    upload: Budget
    search: Budget
    payment: Budget
    trusted_proxies: tuple[Network, ...] = ()


def budget_for(scope: Scope, config: RateLimitConfig, upload_path: str) -> Budget | None:
    method, path = scope["method"], scope["path"]
    if method == "POST":
        if path == "/api/auth/login":
            return config.login
        if path == upload_path:
            return config.upload
        return None
    if method not in ("GET", "HEAD"):
        return None
    if path in ("/api/catalog", "/api/catalog/"):
        return config.search
    if PAYMENT_DATA_PATH.match(path) and "payment-signature" not in Headers(scope=scope):
        # Only challenge (402) issuance: a buyer who already signed a payment is never turned away.
        return config.payment
    return None


class RateLimit:
    """Answers 429 with `Retry-After` once a client spends a route's budget."""

    def __init__(self, app: ASGIApp, config: RateLimitConfig, upload_path: str, buckets: TokenBuckets):
        self.app = app
        self.config = config
        self.upload_path = upload_path
        self.buckets = buckets

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            budget = budget_for(scope, self.config, self.upload_path)
            if budget is not None:
                wait = self.buckets.take(budget, client_key(scope, self.config.trusted_proxies))
                if wait:
                    await _too_many(send, wait)
                    return
        await self.app(scope, receive, send)


async def _too_many(send: Send, wait: int) -> None:
    body = json.dumps({"detail": f"Too many requests. Retry in {wait} seconds."}).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        (b"retry-after", str(wait).encode()),
    ]
    await send({"type": "http.response.start", "status": 429, "headers": headers})
    await send({"type": "http.response.body", "body": body})
