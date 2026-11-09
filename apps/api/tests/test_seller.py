import hashlib

import pytest
from accounts import make_user, sign_in
from sqlalchemy import select

from sliver_api.models import Dataset, PipelineStep
from sliver_api.pipeline.jobs import process_available
from sliver_api.storage import ObjectExistsError

CSV = b"date,terminal,wait_hours\n2026-10-01,Tuas,2.5\n2026-10-02,Keppel,-0.5\n"
FORM = {
    "title": "Terminal waits",
    "source": "Our own berth logs",
    "method": "Exported from the terminal operating system",
    "collected_at": "2026-10-31",
    "rights_confirmed": "true",
}


def upload(client, body: bytes = CSV, filename: str = "waits.csv", **overrides):
    data = {**FORM, **overrides}
    return client.post("/api/seller/datasets", data=data, files={"file": (filename, body, "text/csv")})


@pytest.fixture
def seller(make_client, sessions):
    make_user(sessions, "seller@example.test")
    client = make_client()
    sign_in(client, "seller@example.test")
    return client


def test_upload_stores_immutable_bytes_with_sha256_and_queues_every_stage(seller, sessions, store):
    response = upload(seller, filename="../../etc/waits.csv")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["sha256"] == hashlib.sha256(CSV).hexdigest()
    assert [step["stage"] for step in body["steps"]] == ["validate", "profile", "privacy", "duplicates"]
    assert {step["status"] for step in body["steps"]} == {"pending"}
    with sessions() as db:
        dataset = db.get(Dataset, body["id"])
    assert store.get(dataset.object_key) == CSV
    assert dataset.filename == "waits.csv"
    assert dataset.provenance["collected_at"] == "2026-10-31"
    assert dataset.provenance["rights_confirmed"] is True
    with pytest.raises(ObjectExistsError):
        store.put(dataset.object_key, b"tampered")


def test_upload_requires_a_signed_in_seller(make_client, sessions):
    assert upload(make_client()).status_code == 401
    make_user(sessions, "reviewer@example.test", role="reviewer")
    reviewer = make_client()
    sign_in(reviewer, "reviewer@example.test")
    assert upload(reviewer).status_code == 403


def test_oversized_uploads_are_refused_before_parsing(seller, sessions, store):
    big = b"a\n" + b"1\n" * (3 * 1024 * 1024)
    response = upload(seller, body=big)
    assert response.status_code == 413
    assert store.objects == {}
    with sessions() as db:
        assert db.scalars(select(Dataset)).all() == []


def test_a_file_just_over_5_mib_is_refused(seller, store):
    body = b"a\n" + b"x" * (5 * 1024 * 1024 - 1)
    assert upload(seller, body=body).status_code == 413
    assert store.objects == {}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("collected_at", "99999-01-01"),
        ("collected_at", "2026-02-30"),
        ("collected_at", "1e30"),
        ("collected_at", "2999-01-01"),
        ("rights_confirmed", "false"),
        ("title", "  "),
        ("source", "x" * 301),
    ],
)
def test_invalid_declarations_are_422_not_500(seller, store, field, value):
    response = upload(seller, **{field: value})
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == ["body", field]
    assert store.objects == {}


def test_missing_file_and_empty_file_are_422(seller):
    assert seller.post("/api/seller/datasets", data=FORM).status_code == 422
    assert upload(seller, body=b"").status_code == 422


def test_sellers_cannot_read_each_others_datasets(seller, make_client, sessions):
    mine = upload(seller).json()["id"]
    make_user(sessions, "other@example.test")
    other = make_client()
    sign_in(other, "other@example.test")
    theirs = upload(other, title="Other seller data").json()["id"]

    assert [item["id"] for item in seller.get("/api/seller/datasets").json()["items"]] == [mine]
    assert seller.get(f"/api/seller/datasets/{theirs}").status_code == 404
    assert other.get(f"/api/seller/datasets/{mine}").status_code == 404
    assert seller.get(f"/api/seller/datasets/{mine}").status_code == 200
    assert make_client().get(f"/api/seller/datasets/{mine}").status_code == 401


def test_reviewers_see_only_datasets_that_reached_review(seller, make_client, sessions, store, settings):
    clean = upload(seller).json()["id"]
    broken = upload(seller, body=b"a,b\n1\n", title="Broken upload").json()["id"]
    make_user(sessions, "reviewer@example.test", role="reviewer")
    reviewer = make_client()
    sign_in(reviewer, "reviewer@example.test")
    assert reviewer.get("/api/seller/datasets").json()["items"] == []

    process_available(sessions, store, settings.pipeline_step_timeout_seconds)
    queued_only = upload(seller, title="Still queued").json()["id"]
    listed = [item["id"] for item in reviewer.get("/api/seller/datasets").json()["items"]]
    assert listed == [clean]
    assert reviewer.get(f"/api/seller/datasets/{broken}").status_code == 404
    assert reviewer.get(f"/api/seller/datasets/{queued_only}").status_code == 404
    detail = reviewer.get(f"/api/seller/datasets/{clean}").json()
    assert detail["status"] == "review" and detail["seller"] == {"name": "seller"}


def test_detail_shows_per_stage_status_and_findings(seller, sessions, store, settings):
    dataset_id = upload(seller).json()["id"]
    process_available(sessions, store, settings.pipeline_step_timeout_seconds, limit=1)
    detail = seller.get(f"/api/seller/datasets/{dataset_id}").json()
    assert [(step["stage"], step["status"]) for step in detail["steps"]] == [
        ("validate", "passed"),
        ("profile", "pending"),
        ("privacy", "pending"),
        ("duplicates", "pending"),
    ]
    assert detail["status"] == "inspecting"
    process_available(sessions, store, settings.pipeline_step_timeout_seconds)
    detail = seller.get(f"/api/seller/datasets/{dataset_id}").json()
    assert detail["status"] == "review"
    assert detail["row_count"] == 2
    assert detail["columns"] == [
        {"name": "date", "type": "date"},
        {"name": "terminal", "type": "text"},
        {"name": "wait_hours", "type": "decimal"},
    ]
    profile = next(step for step in detail["steps"] if step["stage"] == "profile")
    assert profile["details"]["time_coverage"]["start"] == "2026-10-01"
    assert all(step["finished_at"] for step in detail["steps"])


def test_uploads_never_appear_in_public_discovery(seller, sessions, store, settings, client):
    upload(seller, title="Terminal waits private")
    process_available(sessions, store, settings.pipeline_step_timeout_seconds)
    assert client.get("/api/catalog", params={"q": "terminal waits"}).json()["total"] == 0
    with sessions() as db:
        assert db.scalars(select(PipelineStep.status)).all()
