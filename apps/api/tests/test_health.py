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
