"""AI review, packaging, the leak guard, the acceptance decision and the reviewer queue (#14).

Everything here runs offline: the conftest removes ANTHROPIC_API_KEY, so stages use the
deterministic fallback unless a test injects a fake engine. `Claude` itself is exercised
against a stub SDK client, never the network.
"""

import hashlib
import json
import logging
from datetime import datetime
from types import SimpleNamespace

import pytest
from accounts import make_user, sign_in
from sqlalchemy import select
from test_pipeline import examples_folder
from test_seller import upload

from sliver_api import ai
from sliver_api.config import PipelineSettings
from sliver_api.models import Dataset, Resource
from sliver_api.pipeline import package
from sliver_api.pipeline.context import StageContext
from sliver_api.pipeline.jobs import process_available
from sliver_api.pipeline.leakguard import LeakGuard, is_categorical
from sliver_api.pipeline.profile import profile_column
from sliver_api.pipeline.table import read_table
from sliver_api.storage import ObjectExistsError

TIMEOUT = 300
DEMO_FILES = (
    "sg-berth-waiting-times.csv",
    "asia-route-eta-delays.csv",
    "container-spot-rates.csv",
    "customs-clearance-times.csv",
)
LANES = ["SGSIN-CNSHA", "SGSIN-HKHKG", "SGSIN-IDJKT"]
# 30 rows: lane is a category (3 values), price is a raw number, contact holds personal data.
RATES = "week_start,lane,usd_price,contact\n" + "".join(
    f"2026-{7 + n % 3:02d}-{1 + n:02d},{LANES[n % 3]},{1100 + 17 * n},ops{n}@example.com\n" for n in range(30)
)
CLEAN = "week_start,lane,usd_price\n" + "".join(
    f"2026-{7 + n % 3:02d}-{1 + n:02d},{LANES[n % 3]},{1100 + 17 * n}\n" for n in range(30)
)


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


def detail(client, dataset_id):
    return client.get(f"/api/seller/datasets/{dataset_id}").json()


def step(body, stage):
    return next(item for item in body["steps"] if item["stage"] == stage)


def run(sessions, store):
    process_available(sessions, store, TIMEOUT)


class FakeEngine:
    model = "claude-test"

    def __init__(self, review=None, research=None, search_urls=()):
        self.outputs = {ai.REVIEW_PROMPT: review, ai.RESEARCH_PROMPT: research}
        self.search_urls = list(search_urls)
        self.calls: list[tuple[str, dict, bool]] = []

    def ask(self, prompt, payload, web_search=False):
        self.calls.append((prompt.name, payload, web_search))
        output = self.outputs[prompt.name]
        if isinstance(output, Exception):
            raise output
        return ai.Answer(output, self.model, "req_test", self.search_urls)


def proposal(**overrides) -> dict:
    review = {
        "category": "Freight Rates",
        "tags": ["freight", "spot rate", "singapore"],
        "title": "Weekly container spot rates out of Singapore",
        "description": "Weekly spot prices per container for three lanes from Singapore.",
        "quality_concerns": [],
        "sensitivity_concerns": [],
        "slice": {"column": "lane", "period": "value"},
    }
    review.update(overrides)
    return review


@pytest.fixture
def fake(monkeypatch):
    def install(engine: FakeEngine) -> FakeEngine:
        monkeypatch.setattr(ai, "engine", lambda _settings: engine)
        return engine

    return install


# --- fallback path over the demo datasets -------------------------------------------------


def test_demo_datasets_get_metadata_and_slices_from_the_fallback(seller, sessions, store):
    folder = examples_folder()
    if folder is None:
        pytest.skip("example datasets are not available in this environment")
    ids = {
        name: upload(seller, body=(folder / name).read_bytes(), title=name).json()["id"]
        for name in DEMO_FILES
    }
    run(sessions, store)
    expected = {
        "sg-berth-waiting-times.csv": ("port-operations", "terminal"),
        "asia-route-eta-delays.csv": ("shipping-schedules", "route"),
        "container-spot-rates.csv": ("freight-rates", "lane"),
        "customs-clearance-times.csv": ("customs", None),
    }
    for name, dataset_id in ids.items():
        body = detail(seller, dataset_id)
        review = step(body, "ai_review")
        assert review["status"] == "passed", review["findings"]
        assert review["details"]["engine"] == "fallback"
        assert review["details"]["fallback_reason"] == "no_api_key"
        listing = review["details"]["listing"]
        category, column = expected[name]
        assert listing["category"] == category
        assert listing["tags"] and listing["title"] and listing["description"]
        assert review["details"]["slice"]["column"] == (column or review["details"]["slice"]["column"])
        assert review["details"]["slice"]["column"], name
        assert step(body, "research")["status"] == "skipped"
        assert step(body, "package")["status"] == "passed"
        assert len(body["resources"]) > 2, name
        assert body["status"] == "accepted", step(body, "decide")["details"]


def test_the_fallback_is_deterministic(make_client, sessions, store):
    results = []
    for email in ("one@example.test", "two@example.test"):
        make_user(sessions, email)
        client = make_client()
        sign_in(client, email)
        dataset_id = upload(client, body=CLEAN.encode(), title="Spot rates").json()["id"]
        run(sessions, store)
        body = detail(client, dataset_id)
        results.append(
            (step(body, "ai_review")["details"], [(r["title"], r["sha256"]) for r in body["resources"]])
        )
    assert results[0] == results[1]


# --- packaging ----------------------------------------------------------------------------


def test_each_sliver_is_its_own_immutable_object_with_its_own_sha256(seller, sessions, store):
    dataset_id = upload(seller, body=CLEAN.encode(), title="Spot rates").json()["id"]
    run(sessions, store)
    with sessions() as db:
        resources = db.scalars(select(Resource).where(Resource.dataset_id == dataset_id)).all()
    assert len(resources) == 4  # the full dataset and one sliver per lane
    assert len({resource.object_key for resource in resources}) == 4
    assert len({resource.sha256 for resource in resources}) == 4
    full = next(resource for resource in resources if resource.slice_filter is None)
    assert full.row_count == 30
    assert sum(resource.row_count for resource in resources if resource.slice_filter) == 30
    for resource in resources:
        body = store.get(resource.object_key)
        assert hashlib.sha256(body).hexdigest() == resource.sha256 and len(body) == resource.size_bytes
        assert resource.status == "draft" and resource.published_at is None
        assert resource.price_minor == package.PLACEHOLDER_PRICE_MINOR
        with pytest.raises(ObjectExistsError):
            store.put(resource.object_key, b"tampered")
    sliver = next(resource for resource in resources if resource.slice_filter)
    table = read_table(store.get(sliver.object_key))
    assert {row[1] for row in table.rows} == {sliver.slice_filter["value"]}
    assert sliver.coverage["slice"] == {"column": "lane", "value": sliver.slice_filter["value"]}
    assert sliver.title.endswith(f": {sliver.slice_filter['value']}")


def test_month_slices_for_a_date_column(seller, sessions, store, fake):
    fake(FakeEngine(review=proposal(slice={"column": "week_start", "period": "month"})))
    dataset_id = upload(seller, body=CLEAN.encode(), title="Spot rates").json()["id"]
    run(sessions, store)
    body = detail(seller, dataset_id)
    assert step(body, "ai_review")["details"]["slice"] == {
        "column": "week_start",
        "period": "month",
        "source": "claude",
    }
    labels = sorted(r["slice"]["value"] for r in body["resources"] if r["slice"])
    assert labels == ["2026-07", "2026-08", "2026-09"]


def test_invalid_slice_proposals_fall_back_to_the_rule(seller, sessions, store, fake):
    # usd_price has 30 distinct values: slicing by it would publish raw prices as labels.
    fake(FakeEngine(review=proposal(slice={"column": "usd_price", "period": "value"})))
    dataset_id = upload(seller, body=CLEAN.encode(), title="Spot rates").json()["id"]
    run(sessions, store)
    choice = step(detail(seller, dataset_id), "ai_review")["details"]["slice"]
    assert choice == {"column": "lane", "period": "value", "source": "rule"}


# --- the leak guard -----------------------------------------------------------------------


def guard_for(csv_text: str, flagged=frozenset()) -> LeakGuard:
    table = read_table(csv_text.encode())
    profile = [profile_column(name, table.column(index)) for index, name in enumerate(table.header)]
    return LeakGuard(table, profile, set(flagged), allowed={"30"})


def test_leak_guard_blocks_raw_non_categorical_values():
    guard = guard_for(RATES, flagged={"contact"})
    assert guard.leaks("Prices such as 1117 USD per box.") == ["usd_price"]
    assert guard.leaks("Reach OPS3@example.com for access") == ["contact"]
    assert guard.leaks("Spot (1134), and more") == ["usd_price"]


def test_leak_guard_allows_categories_dates_column_names_and_public_counts():
    guard = guard_for(RATES, flagged={"contact"})
    text = "30 weekly usd_price rows for SGSIN-CNSHA and SGSIN-HKHKG from 2026-07-01 to 2026-09-30."
    assert guard.leaks(text) == []
    assert guard.leaks("Prices around 11170 or 111") == []  # whole values only


def test_categorical_columns_exclude_flagged_long_and_high_cardinality_columns():
    table = read_table(RATES.encode())
    profile = {name: profile_column(name, table.column(index)) for index, name in enumerate(table.header)}
    assert is_categorical(profile["lane"], 30, set())
    assert not is_categorical(profile["lane"], 30, {"lane"})
    assert not is_categorical(profile["usd_price"], 30, set())
    assert not is_categorical(profile["week_start"], 30, set())


def test_leaking_proposals_are_replaced_and_findings_never_echo_values(seller, sessions, store, fake):
    fake(
        FakeEngine(
            review=proposal(
                title="Spot rates (1134 USD and more)",
                description="Includes contacts such as ops1@example.com.",
                tags=["freight", "1151"],
                sensitivity_concerns=[
                    {
                        "column": "contact",
                        "severity": "high",
                        "message": "Emails like ops2@example.com appear.",
                    }
                ],
            )
        )
    )
    dataset_id = upload(seller, body=RATES.encode(), title="Spot rates").json()["id"]
    run(sessions, store)
    body = detail(seller, dataset_id)
    review = step(body, "ai_review")
    listing = review["details"]["listing"]
    assert listing["title"] == "Spot rates"  # the seller's own title
    assert listing["tags"] == ["freight"]
    assert review["details"]["listing_sources"]["title"] == "seller"
    leaks = [item for item in review["findings"] if item["code"] == "public_text_leak"]
    assert {item["field"] for item in leaks} == {"title", "description", "tags"}
    # Hashes and ids may contain digit runs, so check the texts rather than the whole body.
    public = [
        {key: r[key] for key in ("title", "description", "category", "tags")} for r in body["resources"]
    ]
    text = json.dumps([review["findings"], review["details"]["listing"], public])
    for value in ("1134", "1151", "ops1@example.com", "ops2@example.com"):
        assert value not in text
    assert "@example.com" not in json.dumps(body)
    concern = next(item for item in review["findings"] if item["code"] == "ai_sensitivity_concern")
    assert concern["severity"] == "medium" and concern["model_severity"] == "high"
    assert "details withheld" in concern["message"]
    assert body["status"] == "review"  # personal data and the model's concern need a human


def fake_context(dataset, data, store, details: dict) -> StageContext:
    context = StageContext(db=None, store=store, dataset=dataset, data=data)
    context.__dict__["earlier"] = {
        stage: SimpleNamespace(
            result={"details": value, "findings": []}, finished_at=datetime.now(), status="passed"
        )
        for stage, value in details.items()
    }
    return context


def test_package_refuses_public_text_that_leaks(store):
    data = CLEAN.encode()
    dataset = Dataset(id="d1", owner_id="u1", title="Spot rates", sha256=hashlib.sha256(data).hexdigest())
    listing = {"title": "Rates", "description": "One box cost 1117.", "category": "freight-rates", "tags": []}
    context = fake_context(dataset, data, store, {"ai_review": {"listing": listing, "slice": {}}})
    result = package.run(context)
    assert result.status == "failed"
    [item] = result.findings
    assert item["code"] == "public_text_leak" and item["columns"] == ["usd_price"]
    assert "1117" not in item["message"]
    assert result.records == [] and store.objects == {}


# --- what reaches the model ---------------------------------------------------------------


def test_only_schema_profile_and_twenty_redacted_rows_reach_the_model(seller, sessions, store, fake, caplog):
    caplog.set_level(logging.DEBUG)
    engine = fake(FakeEngine(review=proposal()))
    rows = "".join(
        f"2026-07-{1 + n % 28:02d},SGSIN-CNSHA,{2000 + n},S{1234560 + n % 9}D,+65 6123 {4000 + n}\n"
        for n in range(200)
    )
    body = ("week_start,lane,usd_price,nric,phone\n" + rows).encode()
    upload(seller, body=body, title="Rates with contacts")
    run(sessions, store)
    [(name, payload, web_search)] = engine.calls
    assert name == ai.REVIEW_PROMPT and web_search is False
    assert set(payload) == {
        "header",
        "row_count",
        "columns",
        "time_coverage",
        "redacted_columns",
        "sample_rows",
    }
    assert len(payload["sample_rows"]) == ai.MAX_SAMPLE_ROWS
    assert payload["redacted_columns"] == ["nric", "phone"]
    assert all(row[3] == row[4] == "[redacted]" for row in payload["sample_rows"])
    sent = json.dumps(payload)
    assert "S1234560D" not in sent and "6123" not in sent
    # Rows never reach the logs, whatever the level.
    assert "S1234560D" not in caplog.text and "2026-07-01,SGSIN" not in caplog.text


def test_results_are_cached_by_dataset_sha256(make_client, sessions, store, fake):
    engine = fake(FakeEngine(review=proposal()))
    for email in ("one@example.test", "two@example.test"):
        make_user(sessions, email)
        client = make_client()
        sign_in(client, email)
        dataset_id = upload(client, body=CLEAN.encode(), title="Spot rates").json()["id"]
        run(sessions, store)
    assert len(engine.calls) == 1
    review = step(detail(client, dataset_id), "ai_review")["details"]
    assert review["engine"] == "claude" and review["cached"] is True
    assert review["listing"]["category"] == "freight-rates"
    key = ai.cache_key(
        ai.load_prompt(ai.REVIEW_PROMPT), "claude-test", hashlib.sha256(CLEAN.encode()).hexdigest()
    )
    assert key in store.objects


def test_an_unavailable_model_falls_back_and_the_pipeline_finishes(seller, sessions, store, fake):
    fake(FakeEngine(review=ai.Unavailable("api_status_529")))
    dataset_id = upload(seller, body=CLEAN.encode(), title="Spot rates").json()["id"]
    run(sessions, store)
    body = detail(seller, dataset_id)
    review = step(body, "ai_review")
    assert (
        review["details"]["engine"] == "fallback" and review["details"]["fallback_reason"] == "api_status_529"
    )
    assert [item["code"] for item in review["findings"]] == ["ai_unavailable"]
    assert body["status"] == "accepted" and len(body["resources"]) == 4


def test_invalid_model_output_falls_back(seller, sessions, store, fake):
    fake(FakeEngine(review={"category": "x"}))
    dataset_id = upload(seller, body=CLEAN.encode(), title="Spot rates").json()["id"]
    run(sessions, store)
    assert step(detail(seller, dataset_id), "ai_review")["details"]["fallback_reason"] == "invalid_output"


# --- research -----------------------------------------------------------------------------


def test_research_is_off_by_default(seller, sessions, store, fake):
    engine = fake(FakeEngine(review=proposal()))
    dataset_id = upload(seller, body=CLEAN.encode(), title="Spot rates").json()["id"]
    run(sessions, store)
    research = step(detail(seller, dataset_id), "research")
    assert research["status"] == "skipped" and research["details"] == {"enabled": False}
    assert [name for name, _, _ in engine.calls] == [ai.REVIEW_PROMPT]


def test_research_needs_an_api_key(seller, sessions, store, monkeypatch):
    monkeypatch.setenv("SLIVER_AI_RESEARCH", "true")
    dataset_id = upload(seller, body=CLEAN.encode(), title="Spot rates").json()["id"]
    run(sessions, store)
    research = step(detail(seller, dataset_id), "research")
    assert research["status"] == "skipped" and "ANTHROPIC_API_KEY" in research["summary"]


def test_research_reports_free_equivalents_with_returned_sources_only(
    seller, sessions, store, fake, monkeypatch
):
    monkeypatch.setenv("SLIVER_AI_RESEARCH", "true")
    real = "https://data.example.gov/freight-rates"
    engine = fake(
        FakeEngine(
            review=proposal(),
            research={
                "freely_available": "yes",
                "summary": "A port authority publishes the same weekly lane rates.",
                "sources": [
                    {"url": real, "title": "Open freight rates", "note": "Same lanes"},
                    {"url": "https://invented.example.com/", "title": "Made up", "note": "Not searched"},
                ],
            },
            search_urls=[real],
        )
    )
    dataset_id = upload(seller, body=CLEAN.encode(), title="Spot rates").json()["id"]
    run(sessions, store)
    body = detail(seller, dataset_id)
    research = step(body, "research")
    assert research["status"] == "warning"
    assert [source["url"] for source in research["details"]["sources"]] == [real]
    [item] = research["findings"]
    assert item["code"] == "free_equivalent" and item["sources"] == [real]
    name, payload, web_search = engine.calls[1]
    assert name == ai.RESEARCH_PROMPT and web_search is True
    assert set(payload) == {"listing", "columns", "time_coverage"}  # no rows
    deductions = step(body, "decide")["details"]["deductions"]
    assert {"stage": "research", "code": "free_equivalent"}.items() <= deductions[0].items()


# --- the acceptance decision --------------------------------------------------------------


def test_clean_datasets_are_accepted_and_ready_for_pricing(seller, sessions, store):
    dataset_id = upload(seller, body=CLEAN.encode(), title="Spot rates").json()["id"]
    run(sessions, store)
    body = detail(seller, dataset_id)
    decision = step(body, "decide")["details"]
    assert decision["decision"] == "accepted" and decision["blocking"] == []
    assert decision["quality_score"] >= decision["threshold"]
    assert body["status"] == "accepted"
    assert {resource["status"] for resource in body["resources"]} == {"draft"}


def test_blocking_findings_go_to_the_reviewer_queue(seller, sessions, store):
    dataset_id = upload(seller, body=RATES.encode(), title="Spot rates").json()["id"]
    run(sessions, store)
    body = detail(seller, dataset_id)
    decision = step(body, "decide")["details"]
    assert decision["decision"] == "review"
    assert {(item["stage"], item["code"]) for item in decision["blocking"]} == {("privacy", "email")}
    assert body["status"] == "review"
    assert {resource["status"] for resource in body["resources"]} == {"review"}
    # The contact column is personal data, so it is never a public slice or listed value.
    assert all("@" not in json.dumps(resource) for resource in body["resources"])


def test_low_quality_goes_to_the_reviewer_queue(seller, sessions, store, monkeypatch):
    monkeypatch.setenv("SLIVER_AUTO_ACCEPT_QUALITY", "101")
    dataset_id = upload(seller, body=CLEAN.encode(), title="Spot rates").json()["id"]
    run(sessions, store)
    decision = step(detail(seller, dataset_id), "decide")
    assert decision["details"]["decision"] == "review" and decision["details"]["blocking"] == []
    assert "below the threshold" in decision["summary"]


def test_quality_deductions_are_deterministic():
    from sliver_api.pipeline import decide

    assert decide.DEDUCTIONS == {"medium": 10, "low": 3}
    assert decide.blocking_reason("privacy", {"severity": "medium", "code": "email"})
    assert decide.blocking_reason("duplicates", {"severity": "high", "code": "exact_duplicate"})
    assert decide.blocking_reason("ai_review", {"severity": "medium", "code": "ai_sensitivity_concern"})
    assert not decide.blocking_reason("ai_review", {"severity": "medium", "code": "ai_quality_concern"})
    assert decide.blocking_reason("duplicates", {"severity": "medium", "code": "near_duplicate"})
    assert not decide.blocking_reason("duplicates", {"severity": "low", "code": "row_overlap"})


# --- the reviewer queue -------------------------------------------------------------------


def queued(seller, sessions, store) -> str:
    dataset_id = upload(seller, body=RATES.encode(), title="Spot rates").json()["id"]
    run(sessions, store)
    assert detail(seller, dataset_id)["status"] == "review"
    return dataset_id


def decide_on(client, dataset_id, decision="approve", reason="Checked the contact column with the seller."):
    return client.post(
        f"/api/seller/datasets/{dataset_id}/review", json={"decision": decision, "reason": reason}
    )


def test_reviewers_approve_with_a_reason(seller, reviewer, sessions, store):
    dataset_id = queued(seller, sessions, store)
    assert dataset_id in [item["id"] for item in reviewer.get("/api/seller/datasets").json()["items"]]
    response = decide_on(reviewer, dataset_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "accepted"
    assert body["review"]["decision"] == "approved" and body["review"]["reviewer"] == "reviewer"
    assert {resource["status"] for resource in body["resources"]} == {"draft"}
    assert detail(seller, dataset_id)["review"]["reason"] == "Checked the contact column with the seller."
    assert decide_on(reviewer, dataset_id).status_code == 409  # decided once


def test_reviewers_reject_with_a_reason_and_still_see_the_dataset(seller, reviewer, sessions, store):
    dataset_id = queued(seller, sessions, store)
    body = decide_on(reviewer, dataset_id, "reject", "Contains customer emails.").json()
    assert body["status"] == "rejected" and body["review"]["decision"] == "rejected"
    assert {resource["status"] for resource in body["resources"]} == {"rejected"}
    assert reviewer.get(f"/api/seller/datasets/{dataset_id}").status_code == 200
    assert detail(seller, dataset_id)["review"]["reason"] == "Contains customer emails."


def test_only_reviewers_decide_and_only_on_queued_datasets(seller, reviewer, sessions, store, make_client):
    dataset_id = queued(seller, sessions, store)
    assert decide_on(seller, dataset_id).status_code == 403
    assert decide_on(make_client(), dataset_id).status_code == 401
    assert decide_on(make_client(origin="https://evil.example"), dataset_id).status_code == 403
    assert decide_on(reviewer, dataset_id, reason=" ").status_code == 422
    assert decide_on(reviewer, dataset_id, decision="publish").status_code == 422
    accepted = upload(seller, body=CLEAN.encode(), title="Clean").json()["id"]
    queued_only = upload(seller, body=b"sensor,reading\nA,1\nB,2\n", title="Not run yet").json()["id"]
    assert decide_on(reviewer, queued_only).status_code == 404  # not visible to reviewers yet
    run(sessions, store)
    assert detail(seller, accepted)["status"] == "accepted"
    assert decide_on(reviewer, accepted).status_code == 409
    assert decide_on(reviewer, "missing").status_code == 404


def test_packaged_drafts_never_appear_in_public_discovery(seller, reviewer, sessions, store, client):
    dataset_id = queued(seller, sessions, store)
    clean = upload(seller, body=CLEAN.encode(), title="Clean").json()["id"]
    run(sessions, store)
    decide_on(reviewer, dataset_id)
    assert client.get("/api/catalog", params={"q": "spot rates"}).json()["total"] == 0
    for resource in detail(seller, clean)["resources"]:
        assert client.get(f"/api/catalog/{resource['id']}").status_code == 404


# --- the Claude client, against a stub SDK ------------------------------------------------


class StubMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, **request):
        self.requests.append(json.loads(json.dumps(request, default=str)))
        return self.responses.pop(0)


def claude_with(responses, model="claude-opus-5-5") -> tuple[ai.Claude, StubMessages]:
    settings = PipelineSettings(anthropic_api_key="test-key", sliver_ai_model=model)
    claude = ai.Claude(settings)
    stub = StubMessages(responses)
    claude.client = SimpleNamespace(beta=SimpleNamespace(messages=stub))
    return claude, stub


def tool_use(name, value):
    return SimpleNamespace(type="tool_use", name=name, input=value)


def response(stop_reason, *content, model="claude-opus-5-5"):
    return SimpleNamespace(stop_reason=stop_reason, content=list(content), model=model)


def test_engine_is_none_without_a_key():
    assert ai.engine(PipelineSettings()) is None
    assert isinstance(ai.engine(PipelineSettings(anthropic_api_key="test-key")), ai.Claude)


def test_claude_requests_a_strict_tool_call_with_fallbacks():
    prompt = ai.load_prompt(ai.REVIEW_PROMPT)
    claude, stub = claude_with([response("tool_use", tool_use("submit_review", proposal()))])
    answer = claude.ask(prompt, {"header": ["a"]})
    assert answer.output == proposal()
    [request] = stub.requests
    assert request["model"] == "claude-opus-5-5"
    assert request["tools"][0]["name"] == "submit_review" and request["tools"][0]["strict"] is True
    assert request["fallbacks"] == "default" and request["betas"] == [ai.FALLBACK_BETA]
    assert "tool_choice" not in request and "thinking" not in request
    assert request["output_config"] == {"effort": "medium"}
    assert json.loads(request["messages"][0]["content"]) == {"header": ["a"]}


def test_claude_continues_paused_search_turns_and_collects_urls():
    prompt = ai.load_prompt(ai.RESEARCH_PROMPT)
    search = SimpleNamespace(
        type="web_search_tool_result", content=[SimpleNamespace(url="https://a.example/")]
    )
    answer_input = {"freely_available": "no", "summary": "None found.", "sources": []}
    claude, stub = claude_with(
        [response("pause_turn", search), response("tool_use", tool_use("submit_research", answer_input))],
        model="claude-haiku-5-5",
    )
    answer = claude.ask(prompt, {}, web_search=True)
    assert answer.search_urls == ["https://a.example/"]
    assert len(stub.requests) == 2 and stub.requests[0]["tools"][1]["type"] == "web_search_20260209"
    assert "fallbacks" not in stub.requests[0]  # only models that accept them


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (response("refusal"), "refusal"),
        (response("end_turn", SimpleNamespace(type="text", text="Here you go")), "no_tool_call"),
        (response("max_tokens"), "max_tokens"),
    ],
)
def test_claude_without_a_usable_tool_call_is_unavailable(reply, reason):
    claude, _ = claude_with([reply])
    with pytest.raises(ai.Unavailable, match=reason):
        claude.ask(ai.load_prompt(ai.REVIEW_PROMPT), {})
