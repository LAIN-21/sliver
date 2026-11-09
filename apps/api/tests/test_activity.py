import asyncio
import base64
import json

import test_payments as harness
from conftest import PLATFORM_ADDRESS
from sqlalchemy import select, text
from test_payments import BUYER, challenge, pay
from x402_xrpl.client.presigned_payment_payer import build_payment_header_for_signed_blob
from x402_xrpl.types import PaymentRequirements

from sliver_api.activity import routes as activity_routes
from sliver_api.activity.log import ActivityLog, sanitize_note
from sliver_api.models import ActivityEvent
from sliver_api.payments.service import ledger_close_time

# The purchase harness (stub facilitator and ledger) from the payment tests.
facilitator, ledger, market = harness.facilitator, harness.ledger, harness.market

DATA = "/api/resources/{}/data"
HAPPY_PATH = [
    "payment_required",
    "signature_received",
    "verified",
    "integrity_checked",
    "settlement_submitted",
    "settled",
    "ledger_validated",
    "delivered",
]


def events(sessions, payment_id=None):
    with sessions() as db:
        query = select(ActivityEvent).order_by(ActivityEvent.id)
        if payment_id:
            query = query.where(ActivityEvent.payment_id == payment_id)
        return db.scalars(query).all()


def test_a_purchase_records_every_step_in_order(market, sessions, ledger):
    client, resource_id = market
    response, signed, _ = pay(client, resource_id, ledger)
    assert response.status_code == 200
    payment_id = response.headers["X-Sliver-Receipt"]
    steps = events(sessions, payment_id)
    assert [event.type for event in steps] == HAPPY_PATH
    assert all(event.pay_to == PLATFORM_ADDRESS and event.amount == "1800000" for event in steps)
    assert all(event.price_minor == 450 and event.resource_id == resource_id for event in steps)
    by_type = {event.type: event for event in steps}
    # The transaction hash appears only once it is submitted for settlement.
    assert [event.tx_hash for event in steps[:4]] == [None] * 4
    assert {event.tx_hash for event in steps[4:]} == {signed.get_hash()}
    assert by_type["verified"].payer == BUYER.address and by_type["delivered"].payer == BUYER.address
    assert by_type["ledger_validated"].ledger_index == 123 and by_type["delivered"].ledger_index == 123
    assert by_type["integrity_checked"].detail is not None and len(by_type["integrity_checked"].detail) == 64
    assert by_type["delivered"].detail is None


def test_activity_never_stores_payment_secrets(market, sessions, ledger):
    client, resource_id = market
    response, signed, header = pay(client, resource_id, ledger)
    assert response.status_code == 200
    invoice = json.loads(base64.b64decode(header))["accepted"]["extra"]["invoiceId"]
    with sessions() as db:
        dump = " ".join(str(row) for row in db.execute(text("SELECT * FROM activity_events")).all())
    for secret in (header, signed.blob(), invoice, BUYER.seed, BUYER.private_key):
        assert secret not in dump
    feed = client.get("/api/activity").text
    for secret in (header, signed.blob(), invoice):
        assert secret not in feed


def test_rejected_verification_is_recorded_with_its_reason(market, sessions, facilitator, ledger):
    client, resource_id = market
    facilitator.valid, facilitator.invalid_reason = False, "amount_mismatch"
    response, _, _ = pay(client, resource_id, ledger)
    assert response.status_code == 402
    first, second = dict.fromkeys(event.payment_id for event in events(sessions))
    assert [(e.type, e.detail) for e in events(sessions, first)] == [
        ("payment_required", None),
        ("signature_received", None),
        ("rejected", "payment_invalid:amount_mismatch"),
    ]
    # The fresh 402 is its own invoice and says why it was issued.
    assert [(e.type, e.detail) for e in events(sessions, second)] == [
        ("payment_required", "payment_invalid:amount_mismatch")
    ]


def test_reusing_a_settled_transaction_is_recorded_as_rejected(market, sessions, ledger):
    client, resource_id = market
    first, signed, _ = pay(client, resource_id, ledger)
    second = PaymentRequirements.from_dict(challenge(client, resource_id).json()["accepts"][0])
    header = build_payment_header_for_signed_blob(
        req=second, signed_tx_blob=signed.blob(), invoice_id=second.invoice_id()
    )
    response = client.get(DATA.format(resource_id), headers={"PAYMENT-SIGNATURE": header})
    assert response.status_code == 409
    last = events(sessions)[-1]
    assert (last.type, last.detail, last.tx_hash) == ("rejected", "transaction_already_used", None)
    assert last.payment_id != first.headers["X-Sliver-Receipt"]


def test_a_replay_is_recorded_as_redelivery_without_settling(market, sessions, ledger):
    client, resource_id = market
    first, _, header = pay(client, resource_id, ledger)
    client.get(DATA.format(resource_id), headers={"PAYMENT-SIGNATURE": header})
    types = [(e.type, e.detail) for e in events(sessions, first.headers["X-Sliver-Receipt"])]
    assert types[-2:] == [("signature_received", None), ("delivered", "replay")]
    assert [t for t, _ in types].count("settled") == 1


def test_corrupted_data_records_a_failure_before_any_settlement(market, store, sessions, ledger):
    client, resource_id = market
    store.objects = {key: b"tampered" for key in store.objects}
    response, _, _ = pay(client, resource_id, ledger)
    assert response.status_code == 503
    assert [(e.type, e.detail) for e in events(sessions)][-2:] == [
        ("verified", None),
        ("failed", "integrity_check_failed"),
    ]


def test_pending_then_validated_on_retry(market, sessions, ledger):
    client, resource_id = market
    ledger.validated = False
    response, _, header = pay(client, resource_id, ledger)
    assert response.status_code == 409
    ledger.validated = True
    retry = client.get(DATA.format(resource_id), headers={"PAYMENT-SIGNATURE": header})
    assert retry.status_code == 200
    types = [e.type for e in events(sessions, retry.headers["X-Sliver-Receipt"])]
    assert types == [*HAPPY_PATH[:6], "pending", "signature_received", "ledger_validated", "delivered"]


def test_ledger_disagreement_shows_as_a_failed_purchase(market, sessions, ledger):
    client, resource_id = market
    response, _, _ = pay(client, resource_id, ledger, delivered="1")
    assert response.status_code == 502
    payment_id = events(sessions)[-1].payment_id
    timeline = client.get(f"/api/purchases/{payment_id}").json()
    assert timeline["status"] == "failed"
    assert timeline["failure_reason"] == "ledger_check:wrong_amount"
    assert timeline["events"][-1]["type"] == "failed"
    assert timeline["events"][-1]["detail"] == "ledger_check:wrong_amount"


def test_agent_note_is_sanitized_and_shown_on_the_timeline(market, sessions, ledger):
    client, resource_id = market
    override = chr(0x202E)  # right-to-left override, a classic spoofing character
    note = f"Need October berth waits\x07 for{override} a\t\troute plan " + "x" * 300
    response = client.get(DATA.format(resource_id), headers={"X-Sliver-Agent-Note": note.encode()})
    assert response.status_code == 402
    (event,) = events(sessions)
    assert event.agent_note.startswith("Need October berth waits for a route plan x")
    assert len(event.agent_note) == 200
    timeline = client.get(f"/api/purchases/{event.payment_id}").json()
    assert timeline["agent_note"] == event.agent_note
    assert timeline["status"] == "required"


def test_sanitize_note():
    assert sanitize_note(None) is None
    assert sanitize_note("  \t\x07 ") is None
    assert sanitize_note("a\tb\r\nc") == "a b c"
    assert sanitize_note("ok" + chr(0x200B) + chr(0x2066) + "fine") == "okfine"  # zero-width, isolate
    # Raw UTF-8 bytes arrive as latin-1 text in HTTP headers.
    assert sanitize_note("Daten für Häfen".encode().decode("latin-1")) == "Daten für Häfen"
    assert len(sanitize_note("é" * 500)) == 200


def test_recording_failures_never_break_a_purchase(market, ledger):
    client, resource_id = market

    def broken():
        raise ConnectionError("database unavailable")

    client.app.state.purchases.activity = ActivityLog(broken)
    response, _, _ = pay(client, resource_id, ledger)
    assert response.status_code == 200


def test_activity_feed_is_public_newest_first_and_filterable(market, ledger):
    client, resource_id = market
    response, signed, _ = pay(client, resource_id, ledger)
    body = client.get("/api/activity", params={"limit": 3}).json()
    assert [item["type"] for item in body["items"]] == ["delivered", "ledger_validated", "settled"]
    assert body["cursor"] == body["items"][0]["id"]
    delivered = body["items"][0]
    assert set(delivered) == {
        "id",
        "type",
        "at",
        "payment_id",
        "resource",
        "amount",
        "network",
        "pay_to",
        "payer",
        "transaction",
        "detail",
        "agent_note",
    }
    assert delivered["resource"]["title"].endswith("October 2026")
    assert delivered["amount"] == {"value": "1800000", "asset": "XRP", "usd_minor": 450}
    assert delivered["transaction"]["explorer_url"].endswith(signed.get_hash())
    only = client.get("/api/activity", params={"type": "delivered"}).json()["items"]
    assert [item["payment_id"] for item in only] == [response.headers["X-Sliver-Receipt"]]
    assert client.get("/api/activity", params={"type": "nope"}).status_code == 422
    assert client.get("/api/activity", params={"limit": 500}).status_code == 422


def test_purchase_timeline_survives_a_reload(market, ledger):
    client, resource_id = market
    ledger.overrides = {"tx_json": {"date": 100}}  # ledger close, seconds after 2000-01-01
    response, signed, _ = pay(client, resource_id, ledger)
    payment_id = response.headers["X-Sliver-Receipt"]
    timeline = client.get(f"/api/purchases/{payment_id}").json()
    assert timeline["status"] == "delivered" and timeline["payer"] == BUYER.address
    assert [event["type"] for event in timeline["events"]] == HAPPY_PATH
    assert timeline["transaction"]["hash"] == signed.get_hash()
    assert timeline["transaction"]["ledger_index"] == 123
    assert timeline["transaction"]["ledger_closed_at"] == "2000-01-01T00:01:40Z"
    assert client.get("/api/purchases/unknown").status_code == 404


def test_unlisted_resources_are_not_named(market, sessions, ledger):
    from sliver_api.models import Resource

    client, resource_id = market
    challenge(client, resource_id)
    with sessions() as db:
        db.get(Resource, resource_id).status = "draft"
        db.commit()
    (item,) = client.get("/api/activity").json()["items"]
    assert item["resource"] == {"id": resource_id, "title": "Unlisted resource"}


def collect(stream, count):
    async def run():
        items = []
        async for chunk in stream:
            items.append(chunk)
            if len(items) == count:
                break
        await stream.aclose()
        return items

    return asyncio.run(run())


def parse(chunk):
    fields = dict(line.split(": ", 1) for line in chunk.strip().splitlines())
    return fields.get("id"), fields["event"], json.loads(fields["data"])


def test_stream_sends_new_events_and_resumes_after_last_event_id(market, sessions, ledger):
    client, resource_id = market
    pay(client, resource_id, ledger)
    ids = [event.id for event in events(sessions)]

    async def connected():
        return False

    stream = activity_routes.event_stream(sessions, ids[3], None, connected, poll_seconds=0)
    retry, *chunks = collect(stream, 1 + len(ids) - 4)
    assert retry == "retry: 2000\n\n"
    parsed = [parse(chunk) for chunk in chunks]
    assert [int(event_id) for event_id, _, _ in parsed] == ids[4:]
    assert {name for _, name, _ in parsed} == {"activity"}
    assert parsed[-1][2]["type"] == "delivered"


def test_stream_sends_heartbeats_when_quiet(sessions):
    async def connected():
        return False

    stream = activity_routes.event_stream(sessions, 0, None, connected, poll_seconds=0, heartbeat_seconds=0)
    _, heartbeat = collect(stream, 2)
    event_id, name, data = parse(heartbeat)
    assert event_id is None and name == "heartbeat" and data["cursor"] == 0


def test_stream_endpoint_honours_last_event_id_and_purchase_filter(market, sessions, ledger, monkeypatch):
    client, resource_id = market
    response, _, _ = pay(client, resource_id, ledger)
    challenge(client, resource_id)  # another invoice, filtered out below
    payment_id = response.headers["X-Sliver-Receipt"]
    ids = [event.id for event in events(sessions, payment_id)]
    monkeypatch.setattr(activity_routes, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(activity_routes, "STREAM_SECONDS", 0.2)
    body = client.get(
        "/api/activity/stream",
        params={"payment_id": payment_id, "after": 0},
        headers={"Last-Event-ID": str(ids[5])},
    )
    assert body.headers["content-type"].startswith("text/event-stream")
    chunks = [chunk for chunk in body.text.split("\n\n") if chunk.startswith("id:")]
    assert [int(parse(chunk)[0]) for chunk in chunks] == ids[6:]


def test_ledger_close_time_reads_api_v2_and_v1_results():
    assert ledger_close_time({"close_time_iso": "2026-11-09T04:05:06Z"}).isoformat() == (
        "2026-11-09T04:05:06+00:00"
    )
    assert ledger_close_time({"tx_json": {"date": 0}}).isoformat() == "2000-01-01T00:00:00+00:00"
    assert ledger_close_time({"date": 86_400}).isoformat() == "2000-01-02T00:00:00+00:00"
    assert ledger_close_time({"tx_json": {}}) is None
    assert ledger_close_time({"date": 10**20}) is None
