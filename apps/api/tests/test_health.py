from fastapi.testclient import TestClient

from sliver_api.db import make_engine
from sliver_api.main import create_app
from sliver_api.storage import MemoryStore


def test_health_ok_when_database_and_storage_are_ready(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "storage": "ok"}}


def test_health_degraded_when_storage_is_unavailable(settings, engine):
    app = create_app(settings, engine=engine, store=MemoryStore(healthy=False))
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "storage": "unavailable"}


def test_health_degraded_when_database_is_unavailable(settings, store):
    unreachable = make_engine("postgresql+psycopg://sliver:wrong@127.0.0.1:9/none")
    app = create_app(settings, engine=unreachable, store=store)
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "unavailable", "storage": "ok"}


class BucketMissingUntilInitialized(MemoryStore):
    """Simulates a bucket bootstrap that failed at startup and succeeds later."""

    def __init__(self):
        super().__init__(healthy=False)
        self.attempts = 0

    def initialize(self) -> None:
        self.attempts += 1
        if self.attempts == 1:
            raise ConnectionError("storage not reachable yet")
        self.healthy = True


def test_health_retries_storage_bootstrap_until_it_succeeds(settings, engine):
    store = BucketMissingUntilInitialized()
    with TestClient(create_app(settings, engine=engine, store=store)) as client:
        assert store.attempts == 1  # startup attempt failed
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["checks"]["storage"] == "ok"
