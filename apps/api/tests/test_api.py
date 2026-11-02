"""Behavior/security tests use explicit SQLite and memory adapters, never live data."""

import hashlib
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from sliver_api.config import Settings
from sliver_api.csv_validation import MAX_FILE_BYTES, InvalidCSV, inspect_csv
from sliver_api.main import COOKIE, create_app
from sliver_api.models import Dataset, LoginSession, User, utcnow
from sliver_api.security import hash_password, token_hash, verify_password
from sliver_api.seed import DEMO_ACCOUNTS, seed_accounts
from sliver_api.storage import MemoryStore

PASSWORD = "synthetic-demo-password"
ORIGIN = "http://127.0.0.1:5173"
PROVENANCE = {
    "source": "Synthetic port observations", "method": "Generated example",
    "collected_at": "2026-11-02", "coverage": "Example port, two observations",
    "rights_statement": "PRIVATE_RIGHTS_DECLARATION_ONLY",
}
CSV = b"port,delay_hours\nPRIVATE_ROW_ALPHA,4\nPRIVATE_ROW_BETA,8\n"


@pytest.fixture
def setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    seed_accounts(engine, {key: PASSWORD for _email, _role, key in DEMO_ACCOUNTS})
    store = MemoryStore()
    app = create_app(Settings(database_url="sqlite://"), engine=engine, store=store)
    yield app, engine, store
    engine.dispose()


def client_for(app, email="seller-a@sliver.local"):
    client = TestClient(app)
    initial = client.get("/api/session")
    response = client.post("/api/session", json={"email": email, "password": PASSWORD},
                           headers={"Origin": ORIGIN, "X-CSRF-Token": initial.json()["csrf_token"]})
    assert response.status_code == 200
    client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]})
    return client


def upload(client, data=CSV, title="Port observations", provenance=None):
    return client.post("/api/datasets", files={"file": ("observations.csv", data, "text/csv")},
                       data={"title": title, "provenance": json.dumps(provenance or PROVENANCE)})


def draft(client):
    dataset = upload(client).json()
    response = client.post("/api/resources", json={"dataset_id": dataset["id"], "title": "Port data",
                           "description": "Synthetic observations", "price_minor": 250, "currency": "USD"})
    assert response.status_code == 201, response.text
    return dataset, response.json()


def test_login_rotates_session_and_csrf_and_uses_opaque_cookie(setup):
    app, engine, _store = setup
    client = TestClient(app)
    initial = client.get("/api/session")
    old_cookie = client.cookies[COOKIE]
    old_csrf = initial.json()["csrf_token"]
    assert initial.json()["user"] is None
    assert "httponly" in initial.headers["set-cookie"].lower()
    assert "samesite=strict" in initial.headers["set-cookie"].lower()
    response = client.post("/api/session", json={"email": "seller-a@sliver.local", "password": PASSWORD},
                           headers={"Origin": ORIGIN, "X-CSRF-Token": old_csrf})
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "seller"
    assert response.json()["csrf_token"] != old_csrf
    assert client.cookies[COOKIE] != old_cookie
    with Session(engine) as db:
        assert db.get(LoginSession, token_hash(old_cookie)) is None
        user = db.scalar(select(User).where(User.email == "seller-a@sliver.local"))
        assert PASSWORD not in user.password_hash


def test_login_requires_csrf_and_valid_origin(setup):
    app, _, _ = setup
    client = TestClient(app)
    csrf = client.get("/api/session").json()["csrf_token"]
    credentials = {"email": "seller-a@sliver.local", "password": PASSWORD}
    assert client.post("/api/session", json=credentials).status_code == 403
    assert client.post("/api/session", json=credentials,
                       headers={"Origin": "https://attacker.invalid", "X-CSRF-Token": csrf}).status_code == 403
    assert client.post("/api/session", json=credentials,
                       headers={"Origin": ORIGIN, "X-CSRF-Token": "wrong"}).status_code == 403


def test_bad_credentials_and_unknown_email_have_same_error(setup):
    client = TestClient(setup[0])
    csrf = client.get("/api/session").json()["csrf_token"]
    headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
    first = client.post("/api/session", json={"email": "seller-a@sliver.local", "password": "wrong"}, headers=headers)
    second = client.post("/api/session", json={"email": "nobody@sliver.local", "password": "wrong"}, headers=headers)
    assert first.status_code == second.status_code == 401
    assert first.json() == second.json()


def test_logout_revokes_cookie_and_old_csrf(setup):
    app, engine, _ = setup
    client = client_for(app)
    raw = client.cookies[COOKIE]
    assert client.delete("/api/session").status_code == 204
    assert client.get("/api/datasets").status_code == 401
    assert client.delete("/api/session").status_code == 403
    with Session(engine) as db:
        assert db.get(LoginSession, token_hash(raw)) is None
    other = TestClient(app)
    other.cookies.set(COOKIE, raw)
    assert other.get("/api/datasets").status_code == 401


def test_expired_sessions_fail_closed(setup):
    app, engine, _ = setup
    client = client_for(app)
    with Session(engine) as db:
        record = db.get(LoginSession, token_hash(client.cookies[COOKIE]))
        record.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/datasets").status_code == 401
    assert upload(client).status_code == 403


def test_private_upload_preview_and_download_preserve_exact_bytes(setup):
    app, _, store = setup
    client = client_for(app)
    response = upload(client)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["version"] == 1
    assert data["sha256"] == hashlib.sha256(CSV).hexdigest()
    assert data["row_count"] == 2
    assert data["validation"]["valid"] is True
    assert "object_key" not in data
    preview = client.get(f"/api/datasets/{data['id']}/preview")
    assert preview.json()["rows"][0] == ["PRIVATE_ROW_ALPHA", "4"]
    download = client.get(f"/api/datasets/{data['id']}/download")
    assert download.content == CSV
    assert download.headers["cache-control"] == "no-store"
    assert download.headers["content-type"] == "application/octet-stream"
    assert len(store.objects) == 1


def test_cross_seller_cannot_enumerate_or_access_private_evidence(setup):
    app, _, _ = setup
    seller = client_for(app)
    dataset, resource = draft(seller)
    other = client_for(app, "seller-b@sliver.local")
    assert other.get("/api/datasets").json() == {"items": []}
    assert other.get("/api/resources").json() == {"items": []}
    for suffix in ("", "/preview", "/download"):
        assert other.get(f"/api/datasets/{dataset['id']}{suffix}").status_code == 404
    assert other.post(f"/api/resources/{resource['id']}/submit").status_code == 404
    assert other.post("/api/resources", json={"dataset_id": dataset["id"], "title": "Stolen",
                      "description": "Not mine", "price_minor": 1, "currency": "USD"}).status_code == 404
    anonymous = TestClient(app)
    assert anonymous.get(f"/api/datasets/{dataset['id']}/download").status_code == 401


def test_review_publishes_only_safe_metadata_and_terminal_state(setup):
    app, _, _ = setup
    seller = client_for(app)
    dataset, resource = draft(seller)
    public = TestClient(app)
    assert public.get("/api/catalog").json() == {"items": []}
    assert seller.post(f"/api/resources/{resource['id']}/review", json={"decision": "approve", "reason": "self"}).status_code == 403
    assert seller.post(f"/api/resources/{resource['id']}/submit").status_code == 200
    assert seller.post(f"/api/resources/{resource['id']}/submit").status_code == 409
    reviewer = client_for(app, "reviewer@sliver.local")
    assert reviewer.get(f"/api/datasets/{dataset['id']}/preview").status_code == 200
    approved = reviewer.post(f"/api/resources/{resource['id']}/review", json={"decision": "approve", "reason": "Demo declaration reviewed"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    catalog = public.get("/api/catalog")
    item = catalog.json()["items"][0]
    assert set(item) == {"id", "title", "description", "price_minor", "currency", "dataset_version",
                         "row_count", "columns", "provenance", "approved_at"}
    assert set(item["provenance"]) == {"source", "method", "collected_at", "coverage"}
    for secret in ("PRIVATE_ROW_ALPHA", "PRIVATE_ROW_BETA", "PRIVATE_RIGHTS_DECLARATION_ONLY",
                   "object_key", "filename", "dataset_id", "owner_id", "csrf_token"):
        assert secret not in catalog.text
    assert reviewer.post(f"/api/resources/{resource['id']}/review", json={"decision": "reject", "reason": "Late change"}).status_code == 409
    assert seller.patch(f"/api/datasets/{dataset['id']}", json={"title": "Changed"}).status_code == 405


def test_rejection_requires_reason_and_cannot_be_resubmitted(setup):
    app, _, _ = setup
    seller = client_for(app)
    _, resource = draft(seller)
    reviewer = client_for(app, "reviewer@sliver.local")
    url = f"/api/resources/{resource['id']}/review"
    assert reviewer.post(url, json={"decision": "approve", "reason": "Premature"}).status_code == 409
    seller.post(f"/api/resources/{resource['id']}/submit")
    assert reviewer.post(url, json={"decision": "reject", "reason": " "}).status_code == 422
    assert reviewer.post(url, json={"decision": "reject", "reason": "Rights evidence missing"}).json()["status"] == "rejected"
    assert seller.post(f"/api/resources/{resource['id']}/submit").status_code == 409
    assert TestClient(app).get("/api/catalog").json() == {"items": []}


@pytest.mark.parametrize("price", [0, -1, 1.5, True, "100", 100_000_001])
def test_price_is_a_bounded_positive_integer(setup, price):
    client = client_for(setup[0])
    dataset = upload(client).json()
    response = client.post("/api/resources", json={"dataset_id": dataset["id"], "title": "Data",
                           "description": "Example", "price_minor": price, "currency": "USD"})
    assert response.status_code == 422


@pytest.mark.parametrize("data", [b"", b"header\n", b"a,a\n1,2\n", b"a,b\n1\n", b"a,b\n\xff,2\n", b"a\n\x00\n"])
def test_invalid_csv_persists_no_objects_or_metadata(setup, data):
    app, engine, store = setup
    client = client_for(app)
    response = upload(client, data=data)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_csv"
    assert response.json()["detail"]["issues"]
    assert store.objects == {}
    with Session(engine) as db:
        assert list(db.scalars(select(Dataset))) == []


def test_upload_and_request_bounds(setup):
    client = client_for(setup[0])
    assert upload(client, b"a\n" + b"x" * MAX_FILE_BYTES).status_code == 422
    assert upload(client, b"a\n" + b"x" * (MAX_FILE_BYTES + 70_000)).status_code == 413
    for data in (b"a\n" + b"x\n" * 10_001, b"a\n" + b"x" * 10_001 + b"\n"):
        with pytest.raises(InvalidCSV):
            inspect_csv(data)


def test_missing_duplicate_and_formula_cells_are_warnings():
    result = inspect_csv(b"a,b\n,2\n,2\n=1+1,3\n")
    assert {w["code"] for w in result["warnings"]} == {"missing_values", "duplicate_rows", "spreadsheet_formula"}


def test_each_upload_is_immutable_and_integrity_failure_denies_download(setup):
    app, _, store = setup
    client = client_for(app)
    first = upload(client).json()
    second = upload(client, CSV.replace(b",4", b",5")).json()
    assert first["id"] != second["id"]
    assert first["sha256"] != second["sha256"]
    assert client.get(f"/api/datasets/{first['id']}/download").content == CSV
    key = next(k for k in store.objects if first["id"] in k)
    store.objects[key] = b"tampered"
    assert client.get(f"/api/datasets/{first['id']}/download").status_code == 503


def test_reviewer_cannot_upload_or_create_resources(setup):
    reviewer = client_for(setup[0], "reviewer@sliver.local")
    assert upload(reviewer).status_code == 403


def test_seed_is_idempotent_and_passwords_are_never_default(setup):
    _, engine, _ = setup
    with pytest.raises(RuntimeError):
        seed_accounts(engine, {})
    seed_accounts(engine, {key: "new-demo-password" for _email, _role, key in DEMO_ACCOUNTS})
    with Session(engine) as db:
        users = list(db.scalars(select(User)))
        assert len(users) == 3
        assert verify_password(PASSWORD, users[0].password_hash)
        assert not verify_password("wrong", users[0].password_hash)
    assert not verify_password(PASSWORD, "bad_hash")


def test_titles_provenance_and_metadata_are_validated(setup):
    client = client_for(setup[0])
    assert upload(client, title=" ").status_code == 422
    invalid = {**PROVENANCE, "collected_at": "not-a-date"}
    assert upload(client, provenance=invalid).status_code == 422
    assert upload(client, provenance={**PROVENANCE, "rights_statement": " "}).status_code == 422


def test_csrf_applies_to_upload_and_resource_mutations(setup):
    client = client_for(setup[0])
    csrf = client.headers.pop("X-CSRF-Token")
    assert upload(client).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    dataset, _ = draft(client)
    client.headers["Origin"] = "https://attacker.invalid"
    assert client.post("/api/resources", json={"dataset_id": dataset["id"], "title": "Data",
                      "description": "Example", "price_minor": 1, "currency": "USD"}).status_code == 403


def test_non_ascii_csrf_header_is_denied_without_server_error(setup):
    client = client_for(setup[0])
    response = client.delete("/api/session", headers=[
        (b"Origin", ORIGIN.encode("ascii")), (b"X-CSRF-Token", b"\xff"),
    ])
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "csrf_failed"
    # Invalid token must not log out the legitimate session.
    assert client.get("/api/session").json()["user"]["role"] == "seller"


def test_nul_upload_metadata_is_rejected_before_storage(setup):
    client = client_for(setup[0])
    requests = [
        {"title": "Port\0data"},
        *({"provenance": {**PROVENANCE, field: "bad\0value"}} for field in PROVENANCE),
    ]
    for arguments in requests:
        response = upload(client, **arguments)
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "invalid_input"
    # Send literal U+0000 in the multipart filename, rather than a URL-escaped name.
    boundary = "sliver-nul-regression"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nPort data\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="provenance"\r\n\r\n{json.dumps(PROVENANCE)}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="bad\0name.csv"\r\n'
        'Content-Type: text/csv\r\n\r\n'
    ).encode("utf-8") + CSV + f"\r\n--{boundary}--\r\n".encode("ascii")
    response = client.post("/api/datasets", content=body,
                           headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "invalid_input"
    assert setup[2].objects == {}


def test_nul_resource_review_and_login_metadata_are_rejected(setup):
    app, _, _ = setup
    seller = client_for(app)
    dataset, resource = draft(seller)
    body = {"dataset_id": dataset["id"], "title": "Data", "description": "Example",
            "price_minor": 250, "currency": "USD"}
    for field in ("dataset_id", "title", "description", "currency"):
        response = seller.post("/api/resources", json={**body, field: "bad\0value"})
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "invalid_input"
    seller.post(f"/api/resources/{resource['id']}/submit")
    reviewer = client_for(app, "reviewer@sliver.local")
    response = reviewer.post(f"/api/resources/{resource['id']}/review",
                             json={"decision": "approve", "reason": "bad\0reason"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_input"
    for field in ("email", "password"):
        credentials = {"email": "seller-a@sliver.local", "password": PASSWORD, field: "bad\0value"}
        response = seller.post("/api/session", json=credentials)
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "invalid_input"
    # URL selectors also become SQL text parameters, so reject them before querying.
    assert seller.get("/api/datasets/bad%00id").status_code == 422
    assert seller.post("/api/resources/bad%00id/submit").status_code == 422
    assert reviewer.post("/api/resources/bad%00id/review",
                         json={"decision": "approve", "reason": "Example"}).status_code == 422
