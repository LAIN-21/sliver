import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from sliver_api.config import Settings
from sliver_api.main import create_app
from sliver_api.ratelimit import Budget, TokenBuckets, client_key, parse_networks

ORIGIN = {"Origin": "http://127.0.0.1:5173"}
LOGIN = {"email": "nobody@sliver.local", "password": "wrong"}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def limited(settings, engine, store, clock):
    """Clients of one app with tiny budgets and a controllable clock; `build(ip)` sets the peer."""
    limited_settings = settings.model_copy(
        update={
            "sliver_rate_limit_enabled": True,
            "sliver_rate_limit_login_per_minute": 2,
            "sliver_rate_limit_upload_per_minute": 2,
            "sliver_rate_limit_search_per_minute": 3,
            "sliver_rate_limit_payment_per_minute": 2,
            "sliver_trusted_proxies": "10.0.0.0/8",
        }
    )
    app = create_app(limited_settings, engine=engine, store=store, rate_buckets=TokenBuckets(clock=clock))
    clients = []

    def build(ip: str = "203.0.113.7") -> TestClient:
        test_client = TestClient(app, headers=ORIGIN, client=(ip, 50000)).__enter__()
        clients.append(test_client)
        return test_client

    yield build
    for test_client in clients:
        test_client.__exit__(None, None, None)


def test_login_over_budget_gets_429_with_retry_after(limited, clock):
    client = limited()
    assert [client.post("/api/auth/login", json=LOGIN).status_code for _ in range(2)] == [401, 401]
    refused = client.post("/api/auth/login", json=LOGIN)
    assert refused.status_code == 429
    # 2 per minute refill one token every 30 seconds.
    assert refused.headers["retry-after"] == "30"
    assert "Too many requests" in refused.json()["detail"]

    clock.now += 29
    assert client.post("/api/auth/login", json=LOGIN).headers["retry-after"] == "1"
    clock.now += 1
    assert client.post("/api/auth/login", json=LOGIN).status_code == 401


def test_budgets_are_per_client_and_per_route(limited):
    first, second = limited("203.0.113.7"), limited("198.51.100.4")
    for _ in range(3):
        first.post("/api/auth/login", json=LOGIN)
    assert first.post("/api/auth/login", json=LOGIN).status_code == 429
    assert second.post("/api/auth/login", json=LOGIN).status_code == 401
    # Another route keeps its own budget, and unlimited routes are never refused.
    assert first.get("/api/catalog").status_code == 200
    assert first.get("/api/health").status_code in (200, 503)
    assert first.get("/api/catalog/categories").status_code == 200


def test_search_budget(limited):
    client = limited()
    assert [client.get("/api/catalog", params={"q": "berth"}).status_code for _ in range(4)] == [
        200,
        200,
        200,
        429,
    ]


def test_upload_is_limited_before_auth_and_body_parsing(limited):
    client = limited()
    codes = [client.post("/api/seller/datasets", content=b"x").status_code for _ in range(3)]
    assert 429 not in codes[:2] and codes[2] == 429


def test_only_unsigned_payment_requests_are_limited(limited):
    client = limited()
    path = "/api/resources/does-not-exist/data"
    assert [client.get(path).status_code for _ in range(3)] == [404, 404, 429]
    # A buyer who already signed a payment is never turned away by the limiter.
    signed = client.get(path, headers={"PAYMENT-SIGNATURE": "not-a-real-payment"})
    assert signed.status_code != 429


def test_forwarded_for_counts_only_behind_a_trusted_proxy(limited):
    proxy = limited("10.0.0.2")

    def via_proxy(client_ip: str) -> int:
        return proxy.post("/api/auth/login", json=LOGIN, headers={"X-Forwarded-For": client_ip}).status_code

    assert [via_proxy("203.0.113.7") for _ in range(3)] == [401, 401, 429]
    # Behind the trusted proxy, another forwarded client has its own budget.
    assert via_proxy("203.0.113.8") == 401

    # An untrusted peer cannot choose its key with the header.
    direct = limited("198.51.100.4")
    codes = [
        direct.post("/api/auth/login", json=LOGIN, headers={"X-Forwarded-For": f"192.0.2.{n}"}).status_code
        for n in range(3)
    ]
    assert codes == [401, 401, 429]


def test_disabled_limiter_never_refuses(client):
    # The shared `settings` fixture switches the limiter off.
    codes = {client.post("/api/auth/login", json=LOGIN, headers=ORIGIN).status_code for _ in range(30)}
    assert codes == {401}


def test_client_key_reads_the_forwarded_chain_from_the_right():
    trusted = parse_networks("10.0.0.0/8, 172.16.0.1")

    def scope(peer: str, forwarded: str | None = None) -> dict:
        headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
        return {"type": "http", "client": (peer, 1), "headers": headers}

    # The client's own spoofed prefix is ignored: the first untrusted hop from the right wins.
    assert client_key(scope("10.0.0.2", "1.1.1.1, 203.0.113.7, 172.16.0.1"), trusted) == "203.0.113.7"
    assert client_key(scope("10.0.0.2"), trusted) == "10.0.0.2"
    assert client_key(scope("10.0.0.2", "garbage"), trusted) == "10.0.0.2"
    assert client_key(scope("203.0.113.9", "1.1.1.1"), trusted) == "203.0.113.9"
    # IPv6 clients are keyed by their /64; IPv4-mapped addresses as plain IPv4.
    assert client_key(scope("2001:db8:1:2:aaaa::1"), ()) == "2001:db8:1:2::/64"
    assert client_key(scope("::ffff:203.0.113.7"), ()) == "203.0.113.7"


def test_buckets_stay_bounded(clock):
    buckets = TokenBuckets(clock=clock, max_tracked=4)
    budget = Budget("search", 10)
    for n in range(20):
        buckets.take(budget, f"198.51.100.{n}")
        assert len(buckets.buckets) <= 4
    while len(buckets.buckets) < 4:
        buckets.take(budget, f"192.0.2.{len(buckets.buckets)}")
    clock.now += 60
    buckets.take(budget, "203.0.113.1")
    assert len(buckets.buckets) == 1  # idle buckets were full again, so they were dropped


def test_settings_reject_malformed_trusted_proxies():
    base = {
        "database_url": "postgresql+psycopg://u:p@db/sliver",
        "s3_endpoint_url": "http://127.0.0.1:9000",
        "s3_access_key_id": "key",
        "s3_secret_access_key": "secret",
    }
    with pytest.raises(ValidationError):
        Settings(sliver_trusted_proxies="proxy.internal", **base)
    assert Settings(sliver_trusted_proxies="10.0.0.0/8, ::1", **base).rate_limits.trusted_proxies
