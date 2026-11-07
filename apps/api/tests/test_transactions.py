"""Transaction boundary regressions with isolated SQLite and private memory bytes."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from urllib.error import URLError

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from sliver_api import payments
from sliver_api.config import Settings
from sliver_api.main import COOKIE, create_app
from sliver_api.models import LoginSession, Quote, Resource, utcnow
from sliver_api.security import token_hash
from sliver_api.seed import DEMO_ACCOUNTS, seed_accounts
from sliver_api.storage import MemoryStore
from test_api import CSV, ORIGIN, PASSWORD, client_for, draft, setup, upload  # noqa: F401

PAYER = "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh"
PAY_TO = "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe"
TX = "A" * 64


def buyer(app, host="127.0.0.1"):
    client = TestClient(app, base_url="http://127.0.0.1", client=(host, 46123))
    token = client.get("/api/session").json()["csrf_token"]
    client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": token})
    return client


def approved(app):
    seller = client_for(app)
    dataset, resource = draft(seller)
    assert seller.post(f"/api/resources/{resource['id']}/submit").status_code == 200
    reviewer = client_for(app, "reviewer@sliver.local")
    assert reviewer.post(f"/api/resources/{resource['id']}/review",
                         json={"decision": "approve", "reason": "Synthetic fixture reviewed"}).status_code == 200
    return dataset, resource


@pytest.fixture
def simulated(setup):
    _, engine, store = setup
    app = create_app(Settings(database_url="sqlite://", payment_mode="simulated"), engine=engine, store=store)
    dataset, resource = approved(app)
    return app, engine, store, dataset, resource


@pytest.fixture
def testnet(setup):
    _, engine, store = setup
    app = create_app(Settings(database_url="sqlite://", payment_mode="xrpl-testnet", xrpl_pay_to=PAY_TO),
                     engine=engine, store=store)
    dataset, resource = approved(app)
    return app, engine, store, dataset, resource


def quote_for(client, resource, real=False):
    response = client.post("/api/quotes", json={"resource_id": resource["id"],
                           **({"buyer_address": PAYER} if real else {})})
    assert response.status_code == 201, response.text
    return response.json()


def valid_result(quote):
    return {"validated": True, "hash": TX, "tx_json": {
        "TransactionType": "Payment", "Account": PAYER, "Destination": PAY_TO,
        "Amount": quote["amount_drops"], "Flags": 0,
        "Memos": [{"Memo": {"MemoData": quote["id"].encode().hex()}}],
    }, "meta": {"TransactionResult": "tesSUCCESS", "delivered_amount": quote["amount_drops"]}}


def test_default_disabled_and_invalid_configuration(setup):
    app, _, _ = setup
    client = buyer(app)
    assert client.get("/api/marketplace").json()["mode"] == "disabled"
    assert client.post("/api/quotes", json={"resource_id": "unknown"}).status_code == 503
    for args in ({"payment_mode": "mainnet"}, {"xrpl_rpc_url": "http://127.0.0.1/internal"},
                 {"payment_mode": "xrpl-testnet", "xrpl_pay_to": "bad"},
                 {"testnet_drops_per_usd": 0}, {"quote_ttl_seconds": 600}):
        with pytest.raises(ValueError):
            Settings(database_url="sqlite://", **args)


def test_catalog_search_price_pagination_and_privacy(simulated):
    app, _, _, dataset, _ = simulated
    public = TestClient(app)
    found = public.get("/api/catalog", params={"q": "PORT", "max_price_minor": 250}).json()
    assert found["total"] == 1
    assert found["items"][0]["sha256"] == dataset["sha256"]
    assert found["items"][0]["size_bytes"] == len(CSV)
    for params in ({"q": "unmatched"}, {"q": "%"}, {"max_price_minor": 249}, {"offset": 1}):
        assert public.get("/api/catalog", params=params).json()["items"] == []
    for params in ({"limit": 101}, {"limit": 0}, {"offset": -1}, {"q": "x" * 201}, {"q": "x\0"}):
        assert public.get("/api/catalog", params=params).status_code == 422
    assert b"PRIVATE_ROW" not in public.get("/api/catalog").content


def test_session_owned_simulated_receipt_and_exact_bytes_survive_reload(simulated):
    app, _, _, dataset, resource = simulated
    client = buyer(app)
    quote = quote_for(client, resource)
    assert quote["sha256"] == dataset["sha256"]
    assert quote["mode"] == "simulated" and quote["network"] == "simulation"
    assert quote["download_url"] is None and quote["amount_drops"] is None
    assert "owner_session" not in str(quote) and "object_key" not in quote
    url = f"/api/quotes/{quote['id']}"
    unpaid = client.get(url + "/download")
    assert unpaid.status_code == 402 and unpaid.json()["detail"]["requirements"]["id"] == quote["id"]
    paid = client.post(url + "/confirm", json={})
    assert paid.status_code == 200
    assert paid.json()["receipt_id"].startswith("SIM-")
    assert paid.json()["transaction_hash"] is None
    assert client.post(url + "/confirm").json() == paid.json()
    assert client.get(url).json() == paid.json()
    downloaded = client.get(paid.json()["download_url"])
    assert downloaded.content == CSV
    assert hashlib.sha256(downloaded.content).hexdigest() == quote["sha256"]
    assert downloaded.headers["cache-control"] == "no-store"


def test_quote_access_requires_current_owning_session_and_never_creates_one(simulated):
    app, _, _, _, resource = simulated
    client = buyer(app)
    quote = quote_for(client, resource)
    outsider = buyer(app)
    anonymous = TestClient(app)
    url = f"/api/quotes/{quote['id']}"
    for visitor in (outsider, anonymous):
        for suffix in ("", "/download"):
            denied = visitor.get(url + suffix)
            assert denied.status_code == 404 and "set-cookie" not in denied.headers
        assert visitor.post(url + "/confirm", json={}).status_code in {403, 404}
    assert COOKIE not in anonymous.cookies
    assert client.post(url + "/confirm", json={}).status_code == 200
    assert client.delete("/api/session").status_code == 204
    assert client.get(url + "/download").status_code == 404


def test_quotes_require_approved_resource_csrf_and_loopback(simulated):
    app, _, _, _, resource = simulated
    no_session = TestClient(app)
    assert no_session.post("/api/quotes", json={"resource_id": resource["id"]}).status_code == 403
    remote = buyer(app, host="203.0.113.1")
    assert remote.post("/api/quotes", json={"resource_id": resource["id"]},
                       headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
    client = buyer(app)
    _, unapproved = draft(client_for(app))
    assert client.post("/api/quotes", json={"resource_id": unapproved["id"]}).status_code == 404
    quote = quote_for(client, resource)
    url = f"/api/quotes/{quote['id']}/confirm"
    assert client.post(url, json={}, headers={"Origin": "https://attacker.invalid"}).status_code == 403
    assert client.post(url, json={}, headers={"X-CSRF-Token": "bad"}).status_code == 403
    assert client.post(url, json={"transaction_hash": TX}).status_code == 422
    assert client.get(f"/api/quotes/{quote['id']}").json()["status"] == "quoted"


def test_expired_new_attempt_refused_but_paid_delivery_recoverable(simulated):
    app, engine, _, _, resource = simulated
    client = buyer(app)
    expired = quote_for(client, resource)
    paid = quote_for(client, resource)
    assert client.post(f"/api/quotes/{paid['id']}/confirm", json={}).status_code == 200
    with Session(engine) as db:
        for qid in (expired["id"], paid["id"]):
            db.get(Quote, qid).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.post(f"/api/quotes/{expired['id']}/confirm", json={}).status_code == 410
    assert client.get(f"/api/quotes/{expired['id']}/download").status_code == 402
    assert client.post(f"/api/quotes/{paid['id']}/confirm", json={}).status_code == 200
    assert client.get(f"/api/quotes/{paid['id']}/download").content == CSV


def test_snapshot_survives_offer_changes_and_tampered_content_fails_closed(simulated):
    app, engine, store, dataset, resource = simulated
    client = buyer(app)
    quote = quote_for(client, resource)
    replacement = upload(client_for(app), CSV.replace(b",4", b",9")).json()
    with Session(engine) as db:
        offer = db.get(Resource, resource["id"])
        offer.price_minor = 900
        offer.title = "Changed metadata"
        offer.dataset_id = replacement["id"]
        db.commit()
    assert client.post(f"/api/quotes/{quote['id']}/confirm", json={}).json()["price_minor"] == 250
    assert client.get(f"/api/quotes/{quote['id']}/download").content == CSV
    key = next(key for key in store.objects if dataset["id"] in key)
    store.objects[key] = CSV + b"changed"
    assert client.get(f"/api/quotes/{quote['id']}/download").status_code == 503
    store.objects[key] = CSV
    with Session(engine) as db:
        db.get(Quote, quote["id"]).size_bytes += 1
        db.commit()
    assert client.get(f"/api/quotes/{quote['id']}/download").status_code == 503


def test_expired_purchase_session_cannot_recover_quote_via_new_session(simulated):
    app, engine, _, _, resource = simulated
    client = buyer(app)
    quote = quote_for(client, resource)
    url = f"/api/quotes/{quote['id']}"
    assert client.post(url + "/confirm", json={}).status_code == 200
    with Session(engine) as db:
        db.get(LoginSession, token_hash(client.cookies[COOKIE])).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get(url + "/download").status_code == 404
    assert client.get("/api/session").status_code == 200
    assert client.get(url).status_code == 404


def test_testnet_payer_validated_and_simulation_cannot_bypass(testnet):
    app, _, _, _, resource = testnet
    client = buyer(app)
    for address in (None, "r" + "a" * 30, "x" * 36, PAY_TO[:-1] + "x"):
        body = {"resource_id": resource["id"]}
        if address is not None:
            body["buyer_address"] = address
        assert client.post("/api/quotes", json=body).status_code == 422
    quote = quote_for(client, resource, True)
    assert quote["buyer_address"] == PAYER and quote["amount_drops"] == "2500000"
    assert quote["pay_to"] == PAY_TO and quote["network"] == "xrpl:1"
    url = f"/api/quotes/{quote['id']}/confirm"
    assert client.post(url, json={}).status_code == 422
    assert client.post(url, json={"simulate": True}).status_code == 422
    assert client.post(url, json={"transaction_hash": "SIM-example"}).status_code == 422


def test_testnet_verified_payment_is_idempotent_and_private(testnet, monkeypatch):
    app, _, _, _, resource = testnet
    client = buyer(app)
    quote = quote_for(client, resource, True)
    monkeypatch.setattr(payments, "fetch_transaction", lambda *_: valid_result(quote))
    url = f"/api/quotes/{quote['id']}"
    response = client.post(url + "/confirm", json={"transaction_hash": TX.lower()})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "paid"
    assert response.json()["receipt_id"].startswith("TESTNET-")
    assert response.json()["transaction_hash"] == TX
    assert client.post(url + "/confirm", json={"transaction_hash": TX}).json() == response.json()
    assert client.get(url + "/download").content == CSV
    assert client.post(url + "/confirm", json={"transaction_hash": "B" * 64}).status_code == 409


@pytest.mark.parametrize("mutation", ["payer", "destination", "amount", "issued_currency", "partial",
                                    "result", "type", "hash", "memo", "meta_missing", "flags_type"])
def test_validated_wrong_proof_never_grants_delivery(testnet, monkeypatch, mutation):
    app, _, _, _, resource = testnet
    client = buyer(app)
    quote = quote_for(client, resource, True)
    result = deepcopy(valid_result(quote))
    tx, meta = result["tx_json"], result["meta"]
    if mutation == "payer": tx["Account"] = PAY_TO
    elif mutation == "destination": tx["Destination"] = PAYER
    elif mutation == "amount": meta["delivered_amount"] = "1"
    elif mutation == "issued_currency": meta["delivered_amount"] = {"currency": "USD", "value": "2500000"}
    elif mutation == "partial": tx["Flags"] = 0x00020000
    elif mutation == "result": meta["TransactionResult"] = "tecPATH_DRY"
    elif mutation == "type": tx["TransactionType"] = "AccountSet"
    elif mutation == "hash": result["hash"] = "B" * 64
    elif mutation == "memo": tx["Memos"] = [{"Memo": {"MemoData": "wrong"}}]
    elif mutation == "meta_missing": result["meta"] = None
    elif mutation == "flags_type": tx["Flags"] = "131072"
    monkeypatch.setattr(payments, "fetch_transaction", lambda *_: result)
    url = f"/api/quotes/{quote['id']}"
    assert client.post(url + "/confirm", json={"transaction_hash": TX}).status_code == 422
    assert client.get(url).json()["status"] == "failed"
    assert client.get(url + "/download").status_code == 402
    assert client.post(url + "/confirm", json={"transaction_hash": "B" * 64}).status_code == 409


@pytest.mark.parametrize("pending", ["unvalidated", "not_found", "network"])
def test_unknown_outcome_retains_hash_and_reconciles_after_expiry(testnet, monkeypatch, pending):
    app, engine, _, _, resource = testnet
    client = buyer(app)
    quote = quote_for(client, resource, True)
    result = valid_result(quote)
    result["validated"] = False
    def fetch(*_):
        if pending == "network":
            raise URLError("offline")
        return {"error": "txnNotFound"} if pending == "not_found" else result
    monkeypatch.setattr(payments, "fetch_transaction", fetch)
    url = f"/api/quotes/{quote['id']}"
    first = client.post(url + "/confirm", json={"transaction_hash": TX})
    assert first.status_code == 202 and first.json()["status"] == "pending"
    assert first.json()["transaction_hash"] == TX
    with Session(engine) as db:
        db.get(Quote, quote["id"]).expires_at = utcnow() - timedelta(seconds=2)
        db.commit()
    assert client.post(url + "/confirm", json={"transaction_hash": "B" * 64}).status_code == 409
    assert client.get(url + "/download").status_code == 402
    monkeypatch.setattr(payments, "fetch_transaction", lambda *_: valid_result(quote))
    assert client.post(url + "/confirm", json={"transaction_hash": TX}).json()["status"] == "paid"


def test_same_proof_cannot_be_replayed_for_second_quote(testnet, monkeypatch):
    app, _, _, _, resource = testnet
    client = buyer(app)
    first, second = [quote_for(client, resource, True) for _ in range(2)]
    monkeypatch.setattr(payments, "fetch_transaction", lambda *_: valid_result(first))
    assert client.post(f"/api/quotes/{first['id']}/confirm", json={"transaction_hash": TX}).status_code == 200
    replay = client.post(f"/api/quotes/{second['id']}/confirm", json={"transaction_hash": TX})
    assert replay.status_code == 422 and replay.json()["detail"]["code"] == "invalid_payment_proof"
    assert client.get(f"/api/quotes/{second['id']}/download").status_code == 402


@pytest.mark.parametrize("attacker_outcome", ["pending", "failed"])
def test_public_hash_preemption_cannot_block_rightful_buyer(testnet, monkeypatch, attacker_outcome):
    """An unrelated session may retain an attempted hash, but cannot reserve settlement."""
    app, engine, _, _, resource = testnet
    attacker, victim = buyer(app), buyer(app)
    attack_quote = quote_for(attacker, resource, True)
    rightful_quote = quote_for(victim, resource, True)
    result = valid_result(rightful_quote)
    if attacker_outcome == "pending":
        monkeypatch.setattr(payments, "fetch_transaction", lambda *_: {"validated": False})
    else:
        monkeypatch.setattr(payments, "fetch_transaction", lambda *_: result)
    attack_url = f"/api/quotes/{attack_quote['id']}"
    attack = attacker.post(attack_url + "/confirm", json={"transaction_hash": TX})
    assert attack.status_code == (202 if attacker_outcome == "pending" else 422)
    with Session(engine) as db:
        retained = db.get(Quote, attack_quote["id"])
        assert retained.transaction_hash == TX and retained.settled_transaction_hash is None
    # The victim succeeds even if the attacker never polls its pending quote.
    monkeypatch.setattr(payments, "fetch_transaction", lambda *_: result)
    rightful = victim.post(f"/api/quotes/{rightful_quote['id']}/confirm", json={"transaction_hash": TX})
    assert rightful.status_code == 200 and rightful.json()["status"] == "paid"
    assert victim.get(rightful.json()["download_url"]).content == CSV
    if attacker_outcome == "pending":
        assert attacker.post(attack_url + "/confirm", json={"transaction_hash": TX}).status_code == 422
    assert attacker.get(attack_url + "/download").status_code == 402
    with Session(engine) as db:
        settled = list(db.scalars(select(Quote).where(Quote.settled_transaction_hash == TX)))
        assert len(settled) == 1 and settled[0].id == rightful_quote["id"]


def test_settlement_unique_constraint_rolls_back_duplicate_paid_transition(testnet, monkeypatch):
    """Even a faulty verifier cannot bypass the database's unique settlement guard."""
    app, engine, _, _, resource = testnet
    client = buyer(app)
    first, second = [quote_for(client, resource, True) for _ in range(2)]
    monkeypatch.setattr("sliver_api.main.verify_testnet_payment", lambda *_: "paid")
    assert client.post(f"/api/quotes/{first['id']}/confirm", json={"transaction_hash": TX}).status_code == 200
    duplicate = client.post(f"/api/quotes/{second['id']}/confirm", json={"transaction_hash": TX})
    assert duplicate.status_code == 409 and duplicate.json()["detail"]["code"] == "payment_proof_used"
    assert client.get(f"/api/quotes/{second['id']}/download").status_code == 402
    with Session(engine) as db:
        original, denied = db.get(Quote, first["id"]), db.get(Quote, second["id"])
        assert original.status == "paid" and original.settled_transaction_hash == TX
        assert denied.status == "pending" and denied.settled_transaction_hash is None
        assert denied.receipt_id is None and denied.paid_at is None


def test_file_sqlite_bounded_concurrent_confirmation_is_one_receipt(tmp_path):
    """Separate connections exercise conditional updates, rather than one StaticPool connection."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'concurrency.db').as_posix()}",
                           connect_args={"check_same_thread": False, "timeout": 20})
    seed_accounts(engine, {key: PASSWORD for _email, _role, key in DEMO_ACCOUNTS})
    app = create_app(Settings(database_url="sqlite://", payment_mode="simulated"), engine=engine, store=MemoryStore())
    try:
        _, resource = approved(app)
        client = buyer(app)
        quote = quote_for(client, resource)
        cookies, headers = dict(client.cookies), dict(client.headers)
        def confirm(_):
            with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 46000), cookies=cookies) as concurrent:
                response = concurrent.post(f"/api/quotes/{quote['id']}/confirm", json={}, headers=headers)
                return response.status_code, response.json()
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(confirm, range(32)))
        assert {status for status, _ in results} == {200}
        assert len({item["receipt_id"] for _, item in results}) == 1
        assert {item["status"] for _, item in results} == {"paid"}
        with Session(engine) as db:
            assert len(list(db.scalars(select(Quote).where(Quote.status == "paid")))) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("race", ["different_hashes_one_quote", "one_hash_different_quotes"])
def test_concurrent_testnet_attempt_is_immutable_but_only_settlement_is_unique(tmp_path, monkeypatch, race):
    engine = create_engine(f"sqlite:///{(tmp_path / 'proof-race.db').as_posix()}",
                           connect_args={"check_same_thread": False, "timeout": 20})
    seed_accounts(engine, {key: PASSWORD for _email, _role, key in DEMO_ACCOUNTS})
    app = create_app(Settings(database_url="sqlite://", payment_mode="xrpl-testnet", xrpl_pay_to=PAY_TO),
                     engine=engine, store=MemoryStore())
    try:
        _, resource = approved(app)
        client = buyer(app)
        quotes = [quote_for(client, resource, True) for _ in range(8 if race == "one_hash_different_quotes" else 1)]
        monkeypatch.setattr(payments, "fetch_transaction", lambda *_:
                            valid_result(quotes[0]) if len(quotes) > 1 else {"validated": False})
        cookies, headers = dict(client.cookies), dict(client.headers)
        def confirm(index):
            quote = quotes[index] if len(quotes) > 1 else quotes[0]
            proof = TX if len(quotes) > 1 else f"{index + 1:064X}"
            with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 46000), cookies=cookies) as concurrent:
                response = concurrent.post(f"/api/quotes/{quote['id']}/confirm",
                                           json={"transaction_hash": proof}, headers=headers)
                return response.status_code
        with ThreadPoolExecutor(max_workers=8) as executor:
            statuses = list(executor.map(confirm, range(8)))
        with Session(engine) as db:
            attempts = list(db.scalars(select(Quote).where(Quote.transaction_hash.is_not(None))))
            settled = list(db.scalars(select(Quote).where(Quote.settled_transaction_hash.is_not(None))))
            if len(quotes) > 1:
                assert statuses.count(200) == 1 and statuses.count(422) == 7
                assert len(attempts) == 8 and len(settled) == 1
                assert settled[0].id == quotes[0]["id"]
            else:
                assert statuses.count(202) == 1 and statuses.count(409) == 7
                assert len(attempts) == 1 and attempts[0].status == "pending" and settled == []
                assert attempts[0].paid_at is None and attempts[0].receipt_id is None
    finally:
        engine.dispose()
