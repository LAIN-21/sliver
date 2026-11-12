"""Buyer-defined custom slices (#39): quote, dedupe, price, refuse, keep unlisted, sell with x402."""

import hashlib
import json
from datetime import date, timedelta

import pytest
import test_payments as harness
from accounts import make_user, sign_in, sign_in_agreed_seller
from conftest import PLATFORM_ADDRESS
from fastapi.testclient import TestClient
from sqlalchemy import select

from sliver_api import valuation
from sliver_api.config import Settings
from sliver_api.main import create_app
from sliver_api.models import ActivityEvent, Dataset, Payment, PipelineStep, Resource, User
from sliver_api.ratelimit import Budget, TokenBuckets, budget_for
from sliver_api.seed import seed
from sliver_api.slices import custom

SELLER_EMAIL = "seller@example.test"
TERMINALS = ("Tuas", "Keppel")
START = date(2026, 9, 1)
DAYS = 61  # September and October 2026
FULL_PRICE = 1200
SLICE_PRICE = 450


def berth_rows() -> list[str]:
    rows = []
    for offset in range(DAYS):
        day = START + timedelta(days=offset)
        for number, terminal in enumerate(TERMINALS):
            wait = f"{(offset * 7 + number * 3) % 50 / 10 + 1:.2f}"
            berth = ("A", "B", "C")[offset % 3]
            agent = ("ops@tuas.example", "ops@keppel.example")[number]
            rows.append(f"{day.isoformat()},{terminal},{berth},{wait},{agent}")
    return rows


def write_fixture(folder) -> None:
    header = "date,terminal,berth_class,avg_wait_hours,agent_email"
    (folder / "berths.csv").write_text("\n".join([header, *berth_rows()]) + "\n")
    (folder / "manifest.toml").write_text(
        f"""
[[sellers]]
key = "a"
email = "{SELLER_EMAIL}"
display_name = "Harbour Data"

[[datasets]]
file = "berths.csv"
seller = "a"
title = "Singapore berth waiting times"
description = "Daily berth waiting hours at Singapore container terminals."
category = "port-operations"
tags = ["port", "berth"]
time_column = "date"
slice_by = "date"
slice_period = "month"
price_minor = {FULL_PRICE}
slice_price_minor = {SLICE_PRICE}

[datasets.provenance]
source = "Test fixture"
method = "Generated"
collected_at = "2026-11-01"
"""
    )


@pytest.fixture(autouse=True)
def fresh_parent_cache():
    custom.prepared_parents.clear()
    yield
    custom.prepared_parents.clear()


@pytest.fixture
def listed(tmp_path, sessions, store):
    """The seeded dataset: {"full": id, "September 2026": id, "October 2026": id}."""
    make_user(sessions, SELLER_EMAIL)
    write_fixture(tmp_path)
    seed(sessions, store, tmp_path)
    with sessions() as db:
        db.scalar(select(User).where(User.email == SELLER_EMAIL)).xrpl_address = harness.SELLER.address
        db.commit()
        ids = {}
        for resource in db.scalars(select(Resource)):
            ids["full" if resource.slice_filter is None else resource.coverage["slice"]["value"]] = (
                resource.id
            )
    return ids


def quote(client, resource_id, **params):
    if isinstance(params.get("where"), dict):
        params["where"] = json.dumps(params["where"])
    return client.get(f"/api/resources/{resource_id}/slices", params=params)


def error(response) -> dict:
    return response.json()["error"]


FIRST_TEN_TUAS = {"time_start": "2026-09-01", "time_end": "2026-09-10", "where": {"terminal": "Tuas"}}


# --- quoting --------------------------------------------------------------------------------


def test_a_quote_cuts_exactly_the_requested_rows(listed, client, store, sessions):
    response = quote(client, listed["full"], **FIRST_TEN_TUAS)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created"] is True and body["row_count"] == 10
    assert body["parent"] == {"id": listed["full"], "title": "Singapore berth waiting times"}
    assert body["filter"] == {
        "time": {"column": "date", "start": "2026-09-01", "end": "2026-09-10"},
        "where": {"terminal": "Tuas"},
    }
    assert body["coverage"] == {
        "time": {"column": "date", "start": "2026-09-01", "end": "2026-09-10"},
        "slice": {"column": "terminal", "value": "Tuas"},
    }
    assert body["purchase"] == {
        "method": "GET",
        "path": f"/api/resources/{body['id']}/data",
        "protocol": "x402",
    }
    assert response.headers["cache-control"] == "no-store"
    assert body["column_count"] == 5 and [column["name"] for column in body["columns"]] == [
        "date",
        "terminal",
        "berth_class",
        "avg_wait_hours",
        "agent_email",
    ]
    assert body["seller"] == {"name": "seller"}  # the account make_user created first
    assert body["payment"] == {
        "network": "xrpl:1",
        "asset": "XRP",
        "amount_drops": "392000",
        "drops_per_usd": 400_000,
    }
    assert body["validity"] == {"expires_at": None, "price_fixed": True, "invoice_timeout_seconds": 600}

    with sessions() as db:
        resource = db.get(Resource, body["id"])
        stored = store.get(resource.object_key)
        assert resource.parent_id == listed["full"] and resource.status == "published"
        assert resource.owner_id == db.get(Resource, listed["full"]).owner_id
    lines = stored.decode().splitlines()
    assert lines[0] == "date,terminal,berth_class,avg_wait_hours,agent_email"
    assert [line.split(",")[:2] for line in lines[1:]] == [
        [(START + timedelta(days=offset)).isoformat(), "Tuas"] for offset in range(10)
    ]
    assert body["content"] == {
        "sha256": hashlib.sha256(stored).hexdigest(),
        "size_bytes": len(stored),
        "format": "text/csv",
    }


def test_a_quote_reveals_counts_coverage_price_and_hash_never_row_values(listed, client):
    body = quote(client, listed["full"], **FIRST_TEN_TUAS).json()
    assert set(body) == {
        "id", "created", "parent", "filter", "row_count", "columns", "column_count", "coverage", "price",
        "payment", "validity", "price_breakdown", "seller", "content", "purchase",
    }  # fmt: skip
    text = json.dumps(body)
    for row in berth_rows()[:20]:
        _day, _terminal, berth, wait, agent = row.split(",")
        assert wait not in text and agent not in text
    assert "filterable" not in text and "agent_email" in text  # column names are public; values never


def test_identical_requests_return_the_same_resource(listed, client, sessions):
    first = quote(client, listed["full"], **FIRST_TEN_TUAS).json()
    again = quote(client, listed["full"], **FIRST_TEN_TUAS)
    assert again.status_code == 200 and again.json()["created"] is False
    assert again.json()["id"] == first["id"] and again.json()["content"] == first["content"]
    # A differently written filter that selects the same bytes shares the Resource too.
    widened = quote(
        client, listed["full"], time_start="2026-08-15", time_end="2026-09-10", where={"terminal": "Tuas"}
    )
    assert widened.status_code == 200 and widened.json()["id"] == first["id"]
    with sessions() as db:
        customs = db.scalars(select(Resource).where(Resource.parent_id == listed["full"])).all()
    assert len(customs) == 1


def test_month_bounds_expand_to_whole_months(listed, client):
    body = quote(client, listed["full"], time_start="2026-10", where={"terminal": "Keppel"}).json()
    assert body["row_count"] == 31
    assert body["filter"]["time"] == {"column": "date", "start": "2026-10-01", "end": None}


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({}, "empty_filter"),
        ({"where": {"unknown": "x"}}, "not_filterable"),
        ({"where": {"agent_email": "ops@tuas.example"}}, "not_filterable"),  # privacy-flagged
        ({"where": {"avg_wait_hours": "2.00"}}, "not_filterable"),  # not a category
        ({"where": {"date": "2026-09-01"}}, "not_filterable"),  # time goes through the range
        ({"where": {"terminal": ""}}, "invalid_value"),
        ({"where": '["Tuas"]'}, "invalid_where"),
        ({"where": "{not json"}, "invalid_where"),
        ({"where": {"terminal": "Tuas", "berth_class": "A", "x": "1", "y": "2"}}, "too_many_conditions"),
        ({"time_start": "2026-13-01"}, "invalid_time"),
        ({"time_start": "Sept 2026"}, "invalid_time"),
        ({"time_start": "2026-10-01", "time_end": "2026-09-01"}, "invalid_time"),
    ],
)
def test_filters_are_validated_against_the_profiled_schema(listed, client, params, code):
    response = quote(client, listed["full"], **params)
    assert response.status_code == 422, response.text
    assert error(response)["code"] == code
    if code != "invalid_where":
        assert error(response)["filterable"] == {
            "time": {"column": "date", "start": "2026-09-01", "end": "2026-10-31"},
            "where": ["terminal", "berth_class"],
            "min_rows": custom.MIN_ROWS,
        }


def test_columns_flagged_by_the_privacy_stage_are_never_filterable(listed, client, sessions):
    with sessions() as db:
        dataset = db.scalar(select(Dataset))
        finding = {"code": "email", "severity": "medium", "message": "m", "column": "berth_class"}
        db.add(PipelineStep(dataset_id=dataset.id, stage="privacy", position=3, status="warning",
                            result={"findings": [finding]}))  # fmt: skip
        db.commit()
    response = quote(client, listed["full"], where={"berth_class": "A"})
    assert error(response)["code"] == "not_filterable"
    assert error(response)["filterable"]["where"] == ["terminal"]


def test_tiny_results_are_refused(listed, client):
    response = quote(client, listed["full"], time_start="2026-09-01", time_end="2026-09-02",
                     where={"terminal": "Tuas"})  # fmt: skip
    assert response.status_code == 422 and error(response)["code"] == "too_few_rows"
    nothing = quote(client, listed["full"], where={"terminal": "Nowhere"})
    assert error(nothing)["code"] == "too_few_rows"


def test_results_equal_to_the_full_dataset_or_a_sliver_point_to_them(listed, client, sessions):
    whole = quote(client, listed["full"], time_start="2026")
    assert whole.status_code == 409
    assert error(whole)["code"] == "equals_full_dataset" and error(whole)["resource_id"] == listed["full"]
    september = quote(client, listed["full"], time_start="2026-09", time_end="2026-09")
    assert september.status_code == 409 and error(september)["code"] == "equals_sliver"
    assert error(september)["resource_id"] == listed["September 2026"]
    with sessions() as db:
        assert db.scalar(select(Resource).where(Resource.parent_id.is_not(None))) is None


def test_custom_slices_are_cut_from_the_full_dataset_only(listed, client):
    sliver = quote(client, listed["September 2026"], where={"terminal": "Tuas"})
    assert sliver.status_code == 409 and error(sliver) == {
        "code": "use_full_dataset",
        "message": "Custom slices are cut from the full dataset.",
        "full_dataset_id": listed["full"],
    }
    derived = quote(client, listed["full"], **FIRST_TEN_TUAS).json()["id"]
    again = quote(client, derived, where={"berth_class": "A"})
    assert again.status_code == 409 and error(again)["full_dataset_id"] == listed["full"]
    assert quote(client, "missing", where={"terminal": "Tuas"}).status_code == 404


def test_the_seller_toggle_and_publication_gate_quotes(listed, client, sessions):
    with sessions() as db:
        db.scalar(select(Dataset)).allow_custom_slices = False
        db.commit()
    response = quote(client, listed["full"], **FIRST_TEN_TUAS)
    assert response.status_code == 409 and error(response)["code"] == "custom_slices_disabled"
    assert client.get(f"/api/catalog/{listed['full']}").json()["custom_slices"] == {"available": False}
    with sessions() as db:
        dataset = db.scalar(select(Dataset))
        dataset.allow_custom_slices, dataset.status = True, "accepted"
        db.commit()
    assert error(quote(client, listed["full"], **FIRST_TEN_TUAS))["code"] == "not_published"


def test_the_payment_path_not_the_quote_decides_whether_a_slice_can_be_paid(listed, client, sessions):
    with sessions() as db:
        db.scalar(select(User).where(User.email == SELLER_EMAIL)).xrpl_address = None
        db.commit()
    derived = quote(client, listed["full"], **FIRST_TEN_TUAS)
    assert derived.status_code == 201
    # Whatever the unchanged x402 path answers for the parent, it answers for the custom slice.
    parent = client.get(f"/api/resources/{listed['full']}/data")
    custom_slice = client.get(f"/api/resources/{derived.json()['id']}/data")
    assert custom_slice.status_code == parent.status_code
    assert custom_slice.json()["error"]["code"] == parent.json()["error"]["code"]


def test_a_tampered_source_object_is_never_cut(listed, client, sessions, store):
    with sessions() as db:
        key = db.get(Resource, listed["full"]).object_key
    store.objects[key] = store.objects[key] + b"2026-11-01,Tuas,A,1.00,x\n"
    response = quote(client, listed["full"], **FIRST_TEN_TUAS)
    assert response.status_code == 503 and error(response)["code"] == "integrity_check_failed"


def test_stored_custom_slices_are_capped_per_parent(listed, client, monkeypatch):
    monkeypatch.setattr(custom, "MAX_PER_PARENT", 1)
    first = quote(client, listed["full"], **FIRST_TEN_TUAS)
    assert first.status_code == 201
    second = quote(client, listed["full"], where={"terminal": "Keppel"})
    assert second.status_code == 409 and error(second)["code"] == "custom_slice_limit"
    # Existing slices are still found.
    assert quote(client, listed["full"], **FIRST_TEN_TUAS).status_code == 200


def age(sessions, resource_id: str, hours: float) -> None:
    with sessions() as db:
        db.get(Resource, resource_id).created_at = custom.utcnow() - timedelta(hours=hours)
        db.commit()


def test_a_full_parent_replaces_its_oldest_never_invoiced_slice(listed, client, store, sessions, monkeypatch):
    monkeypatch.setattr(custom, "MAX_PER_PARENT", 2)
    first = quote(client, listed["full"], **FIRST_TEN_TUAS).json()["id"]
    second = quote(client, listed["full"], where={"terminal": "Keppel"}).json()["id"]
    age(sessions, first, 3)
    age(sessions, second, 2)
    # A buyer asked to pay for the older one: an invoice protects it.
    assert client.get(f"/api/resources/{first}/data").status_code == 402
    with sessions() as db:
        second_key = db.get(Resource, second).object_key
    third = quote(client, listed["full"], where={"berth_class": "A"})
    assert third.status_code == 201, third.text
    with sessions() as db:
        assert db.get(Resource, second) is None and db.get(Resource, first) is not None
        assert {r.id for r in db.scalars(select(Resource).where(Resource.parent_id == listed["full"]))} == {
            first,
            third.json()["id"],
        }
    assert second_key not in store.objects  # the replaced object is deleted after the commit
    # Nothing old and uninvoiced is left: recent and invoiced slices are never replaced.
    refused = quote(client, listed["full"], where={"berth_class": "B"})
    assert refused.status_code == 409 and error(refused)["code"] == "custom_slice_limit"
    # The replaced filter can be quoted again later; it gets a new Resource and object.
    age(sessions, third.json()["id"], 2)
    again = quote(client, listed["full"], where={"terminal": "Keppel"})
    assert again.status_code == 201 and again.json()["id"] != second


def test_repeated_quotes_reuse_the_parsed_parent(listed, client, store, monkeypatch):
    reads = []
    original = store.get
    monkeypatch.setattr(store, "get", lambda key: reads.append(key) or original(key))
    quote(client, listed["full"], **FIRST_TEN_TUAS)
    quote(client, listed["full"], **FIRST_TEN_TUAS)
    quote(client, listed["full"], where={"terminal": "Keppel"})
    assert len(reads) == 1  # one read and scan of the parent for three quotes
    cache = custom.ParentCache(2)
    for number in range(3):
        cache.put((number,), custom.prepared_parents.items[next(iter(custom.prepared_parents.items))])
    assert list(cache.items) == [(1,), (2,)]  # bounded, least recently used first out


# --- rate limit -----------------------------------------------------------------------------


def test_quotes_have_their_own_per_ip_budget(listed, settings, engine, store):
    limited = settings.model_copy(
        update={"sliver_rate_limit_enabled": True, "sliver_rate_limit_slice_quote_per_minute": 2}
    )
    app = create_app(limited, engine=engine, store=store, rate_buckets=TokenBuckets(clock=lambda: 1000.0))
    with (
        TestClient(app, client=("203.0.113.7", 50000)) as first,
        TestClient(app, client=("198.51.100.4", 50000)) as second,
    ):
        assert quote(first, listed["full"], **FIRST_TEN_TUAS).status_code == 201
        assert quote(first, listed["full"], **FIRST_TEN_TUAS).status_code == 200
        limited_response = quote(first, listed["full"], **FIRST_TEN_TUAS)
        assert limited_response.status_code == 429
        assert limited_response.headers["retry-after"] == "30"
        # Another client, and other routes, keep their own budgets.
        assert quote(second, listed["full"], **FIRST_TEN_TUAS).status_code == 200
        assert first.get(f"/api/catalog/{listed['full']}").status_code == 200


def test_the_quote_route_maps_to_the_slice_quote_budget():
    config = Settings(
        database_url="postgresql+psycopg://x@y/z", s3_endpoint_url="http://s3", s3_access_key_id="a",
        s3_secret_access_key="b", sliver_rate_limit_slice_quote_per_minute=7,
    ).rate_limits  # fmt: skip
    scope = {"method": "GET", "path": "/api/resources/abc/slices", "headers": []}
    assert budget_for(scope, config, "/upload") == Budget("slice_quote", 7)
    assert budget_for({**scope, "path": "/api/resources/abc/slices/x"}, config, "/upload") is None


# --- pricing --------------------------------------------------------------------------------


def test_the_quote_returns_a_deterministic_price_breakdown(listed, client):
    body = quote(client, listed["full"], **FIRST_TEN_TUAS).json()
    rows = DAYS * len(TERMINALS)
    assert body["price"] == {"amount_minor": 98, "currency": "USD"}  # 1200 / 122 × 10 = 98.36
    assert body["price_breakdown"] == {
        "price_minor": 98,
        "reference_price_minor": FULL_PRICE,
        "reference_rows": rows,
        "rows": 10,
        "rate_minor_per_row": "9.8361",
        "prorated_minor": 98,
        "floor_minor": valuation.CUSTOM_FLOOR_MINOR,
        "cap_minor": FULL_PRICE,
        "rule": "min(parent price, max(floor, parent price / parent rows × rows))",
    }


@pytest.mark.parametrize("parent_price", [1, 7, 10, 450, 1200, 99_999, valuation.MAX_PRICE_MINOR])
@pytest.mark.parametrize("parent_rows", [1, 5, 122, 10_000])
def test_custom_slice_prices_are_monotone_bounded_and_never_above_the_parent(parent_price, parent_rows):
    previous = 0
    for rows in range(1, parent_rows + 1, max(1, parent_rows // 200)):
        result = valuation.custom_slice_price(parent_price, parent_rows, rows)
        price = result["price_minor"]
        assert result == valuation.custom_slice_price(parent_price, parent_rows, rows)
        assert valuation.MIN_PRICE_MINOR <= price <= min(parent_price, valuation.MAX_PRICE_MINOR)
        assert price >= min(valuation.CUSTOM_FLOOR_MINOR, parent_price)
        assert price >= previous  # fewer rows never cost more
        previous = price
    assert valuation.custom_slice_price(parent_price, parent_rows, parent_rows)["price_minor"] == parent_price


def test_custom_slice_price_rejects_impossible_row_counts():
    for rows, parent_rows in ((0, 10), (11, 10), (1, 0)):
        with pytest.raises(ValueError):
            valuation.custom_slice_price(100, parent_rows, rows)


def test_the_sellers_override_is_the_reference_price(listed, client, sessions):
    with sessions() as db:
        db.get(Resource, listed["full"]).price_minor = 12_200
        db.commit()
    body = quote(client, listed["full"], **FIRST_TEN_TUAS).json()
    assert (
        body["price"]["amount_minor"] == 1000 and body["price_breakdown"]["reference_price_minor"] == 12_200
    )


# --- discovery ------------------------------------------------------------------------------


def test_custom_slices_are_unlisted_but_inspectable_by_id(listed, client):
    before = client.get("/api/catalog").json()
    categories = client.get("/api/catalog/categories").json()
    derived = quote(client, listed["full"], **FIRST_TEN_TUAS).json()["id"]

    after = client.get("/api/catalog").json()
    assert after["total"] == before["total"] == 3
    assert derived not in {item["id"] for item in after["items"]}
    assert client.get("/api/catalog", params={"q": "berth custom slice Tuas"}).json()["total"] == 3
    assert derived not in {
        item["id"] for item in client.get("/api/catalog", params={"q": "Tuas"}).json()["items"]
    }
    assert client.get("/api/catalog/categories").json() == categories

    listing = client.get(f"/api/catalog/{derived}").json()
    assert listing["derived_from"] == {
        "id": listed["full"],
        "filter": {
            "time": {"column": "date", "start": "2026-09-01", "end": "2026-09-10"},
            "where": {"terminal": "Tuas"},
        },
    }
    assert listing["custom_slices"] == {"available": False}
    assert listing["sample_rows"] == [] and listing["row_count"] == 10
    full = client.get(f"/api/catalog/{listed['full']}").json()
    assert full["custom_slices"] == {"available": True} and full["derived_from"] is None
    assert client.get(f"/api/catalog/{listed['October 2026']}").json()["custom_slices"] == {
        "available": False
    }


def test_custom_slices_never_anchor_the_valuation_of_other_datasets(listed, client, sessions):
    from sliver_api.seller import pricing

    quote(client, listed["full"], **FIRST_TEN_TUAS)
    with sessions() as db:
        other = Dataset(id="other", owner_id=db.scalar(select(User)).id, title="t", filename="f",
                        object_key="k", sha256="0" * 64, size_bytes=1, row_count=1, columns=[],
                        provenance={})  # fmt: skip
        found = pricing.comparables(db, other, "port-operations")
    assert sorted(item.price_minor for item in found) == [SLICE_PRICE, SLICE_PRICE, FULL_PRICE]


# --- buying ---------------------------------------------------------------------------------


@pytest.fixture
def market(settings, engine, store):
    facilitator, ledger = harness.StubFacilitator(), harness.StubLedger()
    app = create_app(settings, engine=engine, store=store, facilitator=facilitator, ledger=ledger)
    app.state.purchases.sleep = lambda _seconds: None
    app.state.purchases.ledger_attempts = 2
    with TestClient(app) as client:
        yield client, ledger


def test_a_custom_slice_is_bought_with_x402_and_counts_as_the_sellers_sale(
    listed, market, make_client, sessions, store
):
    buyer, ledger = market
    body = quote(buyer, listed["full"], **FIRST_TEN_TUAS).json()
    accepted = harness.challenge(buyer, body["id"]).json()["accepts"][0]
    # The payee is whatever the payment path issues for any sale of this seller's listings.
    assert accepted["payTo"] == harness.challenge(buyer, listed["full"]).json()["accepts"][0]["payTo"]
    assert accepted["amount"] == str(98 * 400_000 // 100)

    response, signed, _ = harness.pay(buyer, body["id"], ledger)
    assert response.status_code == 200, response.text
    assert hashlib.sha256(response.content).hexdigest() == body["content"]["sha256"]
    assert len(response.content) == body["content"]["size_bytes"]
    with sessions() as db:
        assert response.content == store.get(db.get(Resource, body["id"]).object_key)
        delivered = db.scalars(
            select(ActivityEvent.type).where(ActivityEvent.resource_id == body["id"])
        ).all()
    assert "delivered" in delivered

    seller = make_client()
    sign_in(seller, SELLER_EMAIL)
    earnings = seller.get("/api/seller/insights").json()
    (item,) = earnings["earnings"]["items"]
    assert item["resource"] == {"id": body["id"], "title": item["resource"]["title"],
                                "custom_slice_of": listed["full"]}  # fmt: skip
    assert item["transaction"]["hash"] == signed.get_hash() and item["amount"]["usd_minor"] == 98
    assert body["id"] in earnings["resource_ids"]
    # Collected by Sliver like any sale (ADR 0005): the fee is snapshotted and the net is owed.
    with sessions() as db:
        payment = db.scalar(
            select(Payment).where(Payment.resource_id == body["id"], Payment.status == "delivered")
        )
        assert payment.pay_to == PLATFORM_ADDRESS
        assert (payment.platform_fee_bps, payment.platform_fee_minor, payment.seller_net_minor) == (
            1_000,
            9,
            89,
        )
        assert (payment.platform_fee_drops, payment.seller_net_drops) == (39_200, 352_800)
    assert item["platform_fee"] == {"bps": 1_000, "usd_minor": 9, "xrp_drops": "39200"}
    assert item["net"] == {"usd_minor": 89, "xrp_drops": "352800"} and item["payout"]["status"] == "owed"
    assert earnings["balance"]["owed"] == {"usd_minor": 89, "xrp_drops": "352800"}
    assert earnings["balance"]["sales_owed"] == 1
    feed = buyer.get("/api/activity").json()
    assert any(event["resource"]["id"] == body["id"] for event in feed["items"])

    # The seller's report counts custom slices but keeps them out of the sliver list.
    with sessions() as db:
        dataset_id = db.scalar(select(Dataset.id))
    report = seller.get(f"/api/seller/datasets/{dataset_id}/valuation").json()
    assert report["custom_slices"] == {"allowed": True, "count": 1}
    assert body["id"] not in {sliver["id"] for sliver in report["slivers"]}
    detail = seller.get(f"/api/seller/datasets/{dataset_id}").json()
    assert detail["allow_custom_slices"] is True
    assert body["id"] not in {resource["id"] for resource in detail["resources"]}


# --- the seller's toggle at publication -----------------------------------------------------


@pytest.mark.parametrize("allow", [True, False])
def test_the_seller_chooses_at_publication_whether_custom_slices_are_offered(
    allow, make_client, sessions, store, client
):
    import test_valuation as flow

    make_user(sessions, "pricing@example.test")
    seller = make_client()
    sign_in_agreed_seller(seller, "pricing@example.test")
    dataset_id = flow.accepted(seller, sessions, store)
    before = flow.report(seller, dataset_id)
    assert before["custom_slices"] == {"allowed": True, "count": 0}  # on by default
    response = flow.publish(seller, dataset_id, allow_custom_slices=allow)
    assert response.status_code == 200, response.text
    assert response.json()["allow_custom_slices"] is allow
    assert flow.report(seller, dataset_id)["custom_slices"] == {"allowed": allow, "count": 0}
    full = before["slivers"][0]["id"]
    assert client.get(f"/api/catalog/{full}").json()["custom_slices"] == {"available": allow}
    with sessions() as db:
        db.scalar(
            select(User).where(User.email == "pricing@example.test")
        ).xrpl_address = harness.SELLER.address
        db.commit()
    refused = quote(client, full, time_start="2026")
    if allow:
        assert refused.status_code != 409 or error(refused)["code"] != "custom_slices_disabled"
    else:
        assert refused.status_code == 409 and error(refused)["code"] == "custom_slices_disabled"


def test_custom_slices_stay_out_of_the_x402_directory_but_are_bought_by_id(listed, market, sessions):
    buyer, ledger = market
    derived = quote(buyer, listed["full"], **FIRST_TEN_TUAS).json()["id"]
    directory = buyer.get("/.well-known/x402").json()["items"]
    urls = {item["url"].rsplit("/api/resources/", 1)[1] for item in directory}
    assert f"{derived}/data" not in urls
    assert {f"{listed[key]}/data" for key in ("full", "September 2026", "October 2026")} <= urls
    response, _signed, _ = harness.pay(buyer, derived, ledger)
    assert response.status_code == 200, response.text
    with sessions() as db:
        assert hashlib.sha256(response.content).hexdigest() == db.get(Resource, derived).sha256
