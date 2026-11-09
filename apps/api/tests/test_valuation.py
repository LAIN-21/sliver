"""Explainable valuation and publication (#15): the pure formula, the explanation, sample rows,
publish authorization, catalog exposure, purchase through x402 and the seller's insights.

Offline like the rest of the suite: the conftest removes ANTHROPIC_API_KEY, so explanations use
the template unless a test injects a fake engine.
"""

import json
from dataclasses import replace

import pytest
import test_payments as harness
from accounts import make_user, sign_in
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_ai_review import CLEAN, RATES, run
from test_seller import upload

from sliver_api import ai, valuation
from sliver_api.main import create_app
from sliver_api.models import Resource, User
from sliver_api.seller import pricing
from sliver_api.valuation import Comparable, DemandMatch, ValuationInputs

BASE = ValuationInputs(
    category="freight-rates",
    row_count=300,
    quality_score=90,
    comparables=(Comparable(600, 312), Comparable(150, 52), Comparable(150, 52), Comparable(200, 60)),
)


# --- the pure formula ---------------------------------------------------------------------


def test_the_same_inputs_always_give_the_same_price():
    first, second = valuation.value(BASE), valuation.value(replace(BASE))
    assert first == second
    assert json.dumps(first.to_json(), sort_keys=True) == json.dumps(second.to_json(), sort_keys=True)
    # Order of comparables and demand matches does not matter either.
    shuffled = replace(
        BASE,
        comparables=tuple(reversed(BASE.comparables)),
        demand=(DemandMatch("b", 1), DemandMatch("a", 2)),
    )
    reordered = replace(
        shuffled, comparables=BASE.comparables, demand=(DemandMatch("a", 2), DemandMatch("b", 1))
    )
    assert valuation.value(shuffled) == valuation.value(reordered)


def test_every_factor_is_in_the_breakdown_and_multiplies_out_to_the_price():
    result = valuation.value(BASE)
    body = result.to_json()
    assert [factor["name"] for factor in body["factors"]] == list(valuation.FACTOR_ORDER)
    assert all(factor["inputs"] and factor["reason"] for factor in body["factors"])
    assert body["base"] == {
        "price_minor": 175,  # median of 150, 150, 200, 600
        "source": "comparables",
        "inputs": {"category": "freight-rates", "comparables": 4, "median_rows": 56},
    }
    product = body["base"]["price_minor"]
    for factor in body["factors"]:
        product *= factor["factor"]
    assert result.suggested_price_minor == valuation.whole(product)
    low, high = body["range"]["low_price_minor"], body["range"]["high_price_minor"]
    assert low < result.suggested_price_minor < high


def test_matching_unmet_demand_raises_the_price():
    plain = valuation.value(BASE).suggested_price_minor
    one = valuation.value(replace(BASE, demand=(DemandMatch("spot rates", 1),))).suggested_price_minor
    many = valuation.value(replace(BASE, demand=(DemandMatch("spot rates", 4),))).suggested_price_minor
    capped = valuation.value(replace(BASE, demand=(DemandMatch("spot rates", 99),)))
    assert plain < one < many < capped.suggested_price_minor
    assert capped.factors[2].factor == 1 + valuation.DEMAND_CAP


def test_overlap_with_catalog_data_lowers_the_price():
    prices = [
        valuation.value(replace(BASE, max_overlap=share)).suggested_price_minor for share in (0, 0.3, 0.6, 1)
    ]
    assert prices == sorted(prices, reverse=True) and len(set(prices)) == 4


def test_public_availability_lowers_the_price_and_is_neutral_when_research_did_not_run():
    price = {
        verdict: valuation.value(replace(BASE, public_availability=verdict)).suggested_price_minor
        for verdict in (None, "unknown", "no", "partly", "yes")
    }
    assert price[None] == price["unknown"] == price["no"]
    assert price["no"] > price["partly"] > price["yes"]


def test_quality_and_coverage_move_the_price():
    assert (
        valuation.value(replace(BASE, quality_score=40)).suggested_price_minor
        < valuation.value(BASE).suggested_price_minor
    )
    assert (
        valuation.value(replace(BASE, row_count=30)).suggested_price_minor
        < valuation.value(BASE).suggested_price_minor
    )


def test_prices_stay_within_the_database_bounds():
    tiny = valuation.value(
        replace(BASE, comparables=(), category="general", quality_score=0, row_count=1, max_overlap=1)
    )
    huge = valuation.value(
        replace(BASE, comparables=(Comparable(90_000_000, 1), Comparable(90_000_000, 1)), row_count=10_000)
    )
    assert tiny.suggested_price_minor >= valuation.MIN_PRICE_MINOR
    assert tiny.low_price_minor >= valuation.MIN_PRICE_MINOR
    assert huge.suggested_price_minor == huge.high_price_minor == valuation.MAX_PRICE_MINOR


def test_too_few_comparables_fall_back_to_the_category_base():
    result = valuation.value(replace(BASE, comparables=(Comparable(999, 10),)))
    assert result.base_source == "category"
    assert result.base_price_minor == valuation.CATEGORY_BASE_MINOR["freight-rates"]
    assert (
        valuation.value(replace(BASE, category="unheard-of", comparables=())).base_price_minor
        == valuation.DEFAULT_BASE_MINOR
    )


def test_demand_matches_searches_whose_terms_the_listing_covers():
    demand = [
        {"query": "singapore spot rates", "unmet_searches": 3},
        {"query": "spot rates for lanes", "unmet_searches": 1},
        {"query": "helicopter leasing prices", "unmet_searches": 5},
        {"query": "the data", "unmet_searches": 2},
    ]
    listing = "Spot rates week_start lane usd_price freight-rates"
    assert valuation.matching_demand(listing, demand) == (
        DemandMatch("singapore spot rates", 3),
        DemandMatch("spot rates for lanes", 1),
    )


def test_max_overlap_reads_duplicate_comparisons_and_findings():
    class Step:
        status = "passed"

        def __init__(self, result):
            self.result = result

    steps = {
        "duplicates": Step(
            {"details": {"comparisons": [{"columns": 1.0, "rows": 0.2}]},
             "findings": [{"code": "row_overlap", "severity": "low", "message": "m", "row_overlap": 0.64}]}
        )
    }  # fmt: skip
    assert pricing.max_overlap(steps) == 0.64
    assert pricing.max_overlap({}) == 0.0


# --- seller endpoints ---------------------------------------------------------------------


@pytest.fixture
def seller(make_client, sessions):
    make_user(sessions, "seller@example.test")
    client = make_client()
    sign_in(client, "seller@example.test")
    return client


@pytest.fixture
def reviewer(make_client, sessions):
    make_user(sessions, "reviewer@example.test", role="reviewer")
    client = make_client()
    sign_in(client, "reviewer@example.test")
    return client


def accepted(seller, sessions, store, body: str = CLEAN, title: str = "Spot rates") -> str:
    dataset_id = upload(seller, body=body.encode(), title=title).json()["id"]
    run(sessions, store)
    assert seller.get(f"/api/seller/datasets/{dataset_id}").json()["status"] == "accepted"
    return dataset_id


def report(client, dataset_id):
    response = client.get(f"/api/seller/datasets/{dataset_id}/valuation")
    assert response.status_code == 200, response.text
    return response.json()


def publish(client, dataset_id, **body):
    return client.post(f"/api/seller/datasets/{dataset_id}/publish", json=body)


def full_price(body) -> int:
    return body["slivers"][0]["valuation"]["suggested_price_minor"]


def test_the_report_shows_every_factor_and_is_deterministic(seller, sessions, store):
    dataset_id = accepted(seller, sessions, store)
    first, second = report(seller, dataset_id), report(seller, dataset_id)
    assert first == second
    assert first["publishable"] is True and first["status"] == "accepted"
    assert [sliver["label"] for sliver in first["slivers"]] == ["Full dataset", *harness_lanes()]
    for sliver in first["slivers"]:
        factors = sliver["valuation"]["factors"]
        assert [factor["name"] for factor in factors] == list(valuation.FACTOR_ORDER)
        assert (
            valuation.MIN_PRICE_MINOR
            <= sliver["valuation"]["suggested_price_minor"]
            <= valuation.MAX_PRICE_MINOR
        )
    assert first["explanation"]["source"] == "template" and first["explanation"]["reason"] == "no_api_key"
    assert "$" in first["explanation"]["text"]
    # Nothing is published by looking at the report.
    assert {r["status"] for r in seller.get(f"/api/seller/datasets/{dataset_id}").json()["resources"]} == {
        "draft"
    }


def harness_lanes() -> list[str]:
    return ["SGSIN-CNSHA", "SGSIN-HKHKG", "SGSIN-IDJKT"]


def test_unmet_searches_that_match_raise_the_suggestion(seller, sessions, store, client):
    dataset_id = accepted(seller, sessions, store)
    before = full_price(report(seller, dataset_id))
    for _ in range(3):
        assert client.get("/api/catalog", params={"q": "spot rates lane"}).json()["total"] == 0
    client.get("/api/catalog", params={"q": "helicopter leasing"})  # does not match
    after = report(seller, dataset_id)
    demand = after["slivers"][0]["valuation"]["factors"][2]
    assert demand["inputs"]["unmet_searches"] == 3
    assert demand["inputs"]["matched_queries"] == [{"query": "spot rates lane", "unmet_searches": 3}]
    assert full_price(after) > before


def test_overlap_with_a_published_dataset_lowers_the_suggestion(make_client, seller, sessions, store):
    original = accepted(seller, sessions, store)
    assert publish(seller, original).status_code == 200
    make_user(sessions, "other@example.test")
    other = make_client()
    sign_in(other, "other@example.test")
    unique = accepted(
        other, sessions, store, body=CLEAN.replace("2026-", "2025-").replace(",11", ",21"), title="Rates"
    )
    # Two thirds of the rows also appear in the published dataset.
    lines = CLEAN.splitlines()
    copied = (
        "\n".join([lines[0], *lines[1:21], *(line.replace("2026-", "2024-") for line in lines[21:])]) + "\n"
    )
    overlapping = accepted(other, sessions, store, body=copied, title="Rates copy")
    unique_body, overlap_body = report(other, unique), report(other, overlapping)
    uniqueness = overlap_body["slivers"][0]["valuation"]["factors"][1]
    assert uniqueness["factor"] < 1 and uniqueness["inputs"]["max_row_overlap"] >= 0.5
    assert unique_body["slivers"][0]["valuation"]["factors"][1]["factor"] == 1
    assert full_price(overlap_body) < full_price(unique_body)


def test_accepting_or_overriding_the_price_publishes_to_the_catalog(seller, sessions, store, client):
    dataset_id = accepted(seller, sessions, store)
    body = report(seller, dataset_id)
    full, first_slice = body["slivers"][0], body["slivers"][1]
    response = publish(seller, dataset_id, prices={first_slice["id"]: 4321})
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["status"] == "published"
    assert {resource["status"] for resource in detail["resources"]} == {"published"}

    listed = client.get(f"/api/catalog/{full['id']}").json()
    assert listed["price"]["amount_minor"] == full["valuation"]["suggested_price_minor"]
    assert client.get(f"/api/catalog/{first_slice['id']}").json()["price"]["amount_minor"] == 4321
    assert client.get("/api/catalog", params={"q": "spot rates"}).json()["total"] == len(body["slivers"])

    snapshot = report(seller, dataset_id)
    assert snapshot["publishable"] is False and snapshot["status"] == "published"
    by_id = {sliver["id"]: sliver for sliver in snapshot["slivers"]}
    assert by_id[full["id"]]["accepted_suggestion"] is True
    assert by_id[first_slice["id"]]["accepted_suggestion"] is False
    assert by_id[first_slice["id"]]["price_minor"] == 4321
    assert by_id[full["id"]]["valuation"] == full["valuation"]
    # Repricing after publication is out of scope.
    assert publish(seller, dataset_id).status_code == 409


def test_publishing_refuses_a_suggestion_that_changed_since_the_seller_saw_it(
    seller, sessions, store, client
):
    dataset_id = accepted(seller, sessions, store)
    seen = report(seller, dataset_id)
    suggested = {sliver["id"]: sliver["valuation"]["suggested_price_minor"] for sliver in seen["slivers"]}
    for _ in range(3):  # new unmet demand raises the suggestion meanwhile
        client.get("/api/catalog", params={"q": "spot rates lane"})
    stale = publish(seller, dataset_id, suggested=suggested)
    assert stale.status_code == 409 and "Reload" in stale.text
    with sessions() as db:
        assert {r.status for r in db.scalars(select(Resource).where(Resource.dataset_id == dataset_id))} == {
            "draft"
        }
    # An override needs no matching suggestion; the rest must match the current ones.
    current = report(seller, dataset_id)
    fresh = {sliver["id"]: sliver["valuation"]["suggested_price_minor"] for sliver in current["slivers"]}
    assert fresh != suggested
    overridden = current["slivers"][1]["id"]
    response = publish(seller, dataset_id, suggested={**fresh, overridden: 1}, prices={overridden: 777})
    assert response.status_code == 200, response.text
    assert client.get(f"/api/catalog/{overridden}").json()["price"]["amount_minor"] == 777


def test_only_the_owner_prices_and_publishes_accepted_datasets(
    seller, reviewer, make_client, sessions, store
):
    dataset_id = accepted(seller, sessions, store)
    make_user(sessions, "other@example.test")
    other = make_client()
    sign_in(other, "other@example.test")
    for client, status in ((other, 404), (reviewer, 403), (make_client(), 401)):
        assert client.get(f"/api/seller/datasets/{dataset_id}/valuation").status_code == status
        assert publish(client, dataset_id).status_code == status
    assert publish(make_client(origin="https://evil.example"), dataset_id).status_code == 403
    assert publish(seller, "missing").status_code == 404

    queued = upload(seller, body=RATES.encode(), title="Rates with contacts").json()["id"]
    run(sessions, store)
    assert seller.get(f"/api/seller/datasets/{queued}/valuation").status_code == 409
    assert publish(seller, queued).status_code == 409

    sliver_id = report(seller, dataset_id)["slivers"][0]["id"]
    assert publish(seller, dataset_id, prices={sliver_id: 0}).status_code == 422
    assert publish(seller, dataset_id, prices={sliver_id: valuation.MAX_PRICE_MINOR + 1}).status_code == 422
    assert publish(seller, dataset_id, prices={"not-a-sliver": 100}).status_code == 422
    assert publish(seller, dataset_id, suggested={"not-a-sliver": 100}).status_code == 422
    with sessions() as db:
        assert {r.status for r in db.scalars(select(Resource).where(Resource.dataset_id == dataset_id))} == {
            "draft"
        }


def test_reviewer_approved_datasets_can_be_published(seller, reviewer, sessions, store, client):
    queued = upload(seller, body=RATES.encode(), title="Rates with contacts").json()["id"]
    run(sessions, store)
    reviewer.post(f"/api/seller/datasets/{queued}/review", json={"decision": "approve", "reason": "Checked."})
    body = report(seller, queued)
    assert body["publishable"] is True
    assert publish(seller, queued).status_code == 200
    detail = seller.get(f"/api/seller/datasets/{queued}").json()
    assert detail["review"]["decision"] == "approved"
    # The reviewer still sees the dataset once it is published.
    assert reviewer.get(f"/api/seller/datasets/{queued}").status_code == 200
    listed = client.get(f"/api/catalog/{body['slivers'][0]['id']}").json()
    assert listed["sample_rows"] == [] and "@" not in json.dumps(listed)


# --- sample rows --------------------------------------------------------------------------

# Row 2 carries an email in `note`; rows 1 and 3 leave it empty.
NOTES = "week_start,lane,usd_price,note\n" + "".join(
    f"2026-{7 + n % 3:02d}-{1 + n:02d},{harness_lanes()[n % 3]},{1100 + 17 * n},"
    f"{'ops@example.com' if n == 1 else ''}\n"
    for n in range(30)
)


def test_rows_with_privacy_flagged_values_cannot_be_made_public(seller, reviewer, sessions, store, client):
    dataset_id = upload(seller, body=NOTES.encode(), title="Rates with notes").json()["id"]
    run(sessions, store)
    reviewer.post(
        f"/api/seller/datasets/{dataset_id}/review", json={"decision": "approve", "reason": "Checked."}
    )
    body = report(seller, dataset_id)
    candidates = {item["row"]: item for item in body["sample"]["candidates"]}
    assert candidates[1]["problem"] is None
    assert "note" in candidates[2]["problem"]
    # Flagged cells are redacted even in the owner's candidate list.
    assert candidates[2]["values"][3] == "[redacted]" and "@" not in json.dumps(candidates[2])
    response = publish(seller, dataset_id, sample_rows=[1, 2])
    assert response.status_code == 422
    assert "Row 2" in response.text and "@" not in response.text
    assert publish(seller, dataset_id, sample_rows=[99]).status_code == 422
    assert publish(seller, dataset_id, sample_rows=[1, 2, 3, 4, 5, 6]).status_code == 422  # at most five
    for item in body["slivers"]:
        assert client.get(f"/api/catalog/{item['id']}").status_code == 404  # still drafts
    assert publish(seller, dataset_id, sample_rows=[1, 3]).status_code == 200
    full = client.get(f"/api/catalog/{body['slivers'][0]['id']}").json()
    rows = NOTES.splitlines()
    assert full["sample_rows"] == [rows[1].split(","), rows[3].split(",")]


def test_sample_rows_are_private_unless_selected_and_follow_their_sliver(seller, sessions, store, client):
    dataset_id = accepted(seller, sessions, store)
    body = report(seller, dataset_id)
    publish(seller, dataset_id, sample_rows=[2, 1])
    rows = [line.split(",") for line in CLEAN.splitlines()[1:]]
    catalog = client.get("/api/catalog", params={"limit": 50}).json()["items"]
    by_title = {item["title"]: item for item in catalog}
    full = next(item for item in catalog if item["id"] == body["slivers"][0]["id"])
    assert full["sample_rows"] == [rows[0], rows[1]]
    for item in catalog:
        lane = (item["coverage"].get("slice") or {}).get("value")
        if lane:
            assert item["sample_rows"] == [row for row in rows[:2] if row[1] == lane]
    assert len(by_title) == len(body["slivers"])
    # No unselected row reaches public discovery.
    text = json.dumps(catalog)
    for row in rows[2:]:
        assert ",".join(row) not in text and json.dumps(row) not in text


def test_nothing_is_public_by_default(seller, sessions, store, client):
    dataset_id = accepted(seller, sessions, store)
    publish(seller, dataset_id)
    for item in client.get("/api/catalog").json()["items"]:
        assert item["sample_rows"] == []


# --- the explanation ----------------------------------------------------------------------


class ExplainEngine:
    model = "claude-test"

    def __init__(self, text):
        self.text = text
        self.payloads: list[dict] = []

    def ask(self, prompt, payload, web_search=False):
        assert prompt.name == ai.EXPLANATION_PROMPT
        self.payloads.append(payload)
        text = self.text(payload) if callable(self.text) else self.text
        return ai.Answer({"explanation": text}, self.model, "req_test")


def install(monkeypatch, engine):
    monkeypatch.setattr(ai, "engine", lambda _settings: engine)
    return engine


def test_claude_explains_only_the_computed_numbers(seller, sessions, store, monkeypatch):
    dataset_id = accepted(seller, sessions, store)  # the AI review used the fallback
    engine = install(
        monkeypatch,
        ExplainEngine(
            lambda p: f"Your dataset is priced at {p['full_dataset']['suggested_price']} from its base."
        ),
    )
    body = report(seller, dataset_id)
    assert body["explanation"]["source"] == "claude"
    assert body["explanation"]["text"].startswith("Your dataset is priced at $")
    (payload,) = engine.payloads
    # Aggregates and the breakdown only: no rows, no cell values, no search texts.
    text = json.dumps(payload)
    for line in CLEAN.splitlines()[1:]:
        for cell in line.split(","):
            if not cell.isdigit():
                assert cell not in text
    assert "matched_queries" not in text and "sample" not in text
    assert {item["name"] for item in payload["full_dataset"]["factors"]} == set(valuation.FACTOR_ORDER)

    # Publishing never calls Claude: it reuses the cached explanation of the same numbers.
    publish(seller, dataset_id)
    assert len(engine.payloads) == 1
    assert report(seller, dataset_id)["explanation"]["source"] == "claude"


def test_an_explanation_with_an_invented_number_falls_back_to_the_template(
    seller, sessions, store, monkeypatch
):
    dataset_id = accepted(seller, sessions, store)
    install(monkeypatch, ExplainEngine("Agents will pay $999.99 for this, 40% more than average."))
    body = report(seller, dataset_id)
    assert body["explanation"]["source"] == "template" and body["explanation"]["reason"] == "invented_number"
    assert "999" not in body["explanation"]["text"]


def test_an_unavailable_model_never_blocks_publishing(seller, sessions, store, monkeypatch, client):
    dataset_id = accepted(seller, sessions, store)

    class Down:
        model = "claude-test"

        def ask(self, *_args, **_kwargs):
            raise ai.Unavailable("api_connection")

    install(monkeypatch, Down())
    body = report(seller, dataset_id)
    assert body["explanation"]["source"] == "template"
    assert publish(seller, dataset_id).status_code == 200
    assert client.get(f"/api/catalog/{body['slivers'][0]['id']}").status_code == 200


def test_validate_explanation_accepts_numbers_in_any_format_from_the_payload():
    payload = {
        "full_dataset": {"suggested_price": "$1,234.50", "factors": [{"factor": 0.85, "change_pct": -15}]}
    }
    ok = "Priced at $1,234.50: quality ×0.85 lowered it by 15%."
    assert pricing.validate_explanation({"explanation": ok}, payload) == ok
    with pytest.raises(ai.Unavailable):
        pricing.validate_explanation({"explanation": "Priced at $1,300."}, payload)
    with pytest.raises(ai.Unavailable):
        pricing.validate_explanation({"explanation": " "}, payload)


# --- buying a published sliver through the existing x402 path -----------------------------


@pytest.fixture
def market(settings, engine, store):
    facilitator, ledger = harness.StubFacilitator(), harness.StubLedger()
    app = create_app(settings, engine=engine, store=store, facilitator=facilitator, ledger=ledger)
    app.state.purchases.sleep = lambda _seconds: None
    app.state.purchases.ledger_attempts = 2
    with TestClient(app) as client:
        yield client, ledger


def test_a_published_sliver_is_bought_with_x402_and_shows_in_the_sellers_earnings(
    seller, make_client, sessions, store, market
):
    buyer, ledger = market
    with sessions() as db:
        db.scalar(
            select(User).where(User.email == "seller@example.test")
        ).xrpl_address = harness.SELLER.address
        db.commit()
    dataset_id = accepted(seller, sessions, store)
    sliver = report(seller, dataset_id)["slivers"][1]
    publish(seller, dataset_id, prices={sliver["id"]: 450})

    response, signed, _ = harness.pay(buyer, sliver["id"], ledger)
    assert response.status_code == 200, response.text
    with sessions() as db:
        assert response.content == store.get(db.get(Resource, sliver["id"]).object_key)

    earnings = seller.get("/api/seller/insights").json()
    assert earnings["earnings"]["purchases"] == 1 and earnings["earnings"]["usd_minor"] == 450
    (item,) = earnings["earnings"]["items"]
    assert item["transaction"]["hash"] == signed.get_hash()
    assert item["transaction"]["explorer_url"] == f"https://testnet.xrpl.org/transactions/{signed.get_hash()}"
    assert item["payment_id"] == response.headers["X-Sliver-Receipt"]
    assert sliver["id"] in earnings["resource_ids"] and earnings["cursor"] > 0

    # Another seller sees none of it.
    make_user(sessions, "other@example.test")
    other = make_client()
    sign_in(other, "other@example.test")
    theirs = other.get("/api/seller/insights").json()
    assert theirs["earnings"] == {"purchases": 0, "usd_minor": 0, "xrp_drops": "0", "items": []}
    assert sliver["id"] not in theirs["resource_ids"]


def test_insights_list_unmet_demand_with_matching_listings(
    seller, reviewer, sessions, store, client, make_client
):
    dataset_id = accepted(seller, sessions, store)
    client.get("/api/catalog", params={"q": "spot rates lane"})
    client.get("/api/catalog", params={"q": "helicopter leasing"})
    body = seller.get("/api/seller/insights").json()
    by_query = {item["query"]: item for item in body["demand"]["items"]}
    assert set(by_query) == {"spot rates lane", "helicopter leasing"}
    assert by_query["helicopter leasing"]["matches"] == []
    assert by_query["spot rates lane"]["matches"][0]["status"] == "draft"
    assert dataset_id  # the matches are the seller's own slivers only
    assert reviewer.get("/api/seller/insights").status_code == 403
    assert make_client().get("/api/seller/insights").status_code == 401
