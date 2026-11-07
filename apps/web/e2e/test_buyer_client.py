"""Offline external-buyer payment-safety regressions; no ledger or keys needed."""

import importlib.util
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import httpx


@pytest.mark.parametrize("expires_during", ["authorization_prompt", "sdk_autofill"])
def test_expiry_during_blocking_work_never_records_or_submits_payment(
    monkeypatch, tmp_path, expires_during
):
    path = Path(__file__).resolve().parents[3] / "examples" / "buyer_client.py"
    spec = importlib.util.spec_from_file_location("external_buyer_expiry", path)
    buyer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(buyer)
    start = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    current = [start]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current[0]

    monkeypatch.setattr(buyer, "datetime", Clock)
    calls = []

    def authorize(_prompt):
        if expires_during == "authorization_prompt":
            current[0] = start + timedelta(minutes=5)
        return "PAY TESTNET"

    def autofill_and_sign(*_args):
        calls.append("autofill_and_sign")
        if expires_during == "sdk_autofill":
            current[0] = start + timedelta(minutes=5)
        return SimpleNamespace(fee="12", get_hash=lambda: "A" * 64)

    def submit(*_args):
        calls.append("submit")

    # Stub only the public SDK boundary. These tests run with ordinary API test
    # dependencies, independent of optional xrpl-py installation or availability.
    sdk = {
        "xrpl": {},
        "xrpl.clients": {"JsonRpcClient": lambda _url: object()},
        "xrpl.models": {},
        "xrpl.models.transactions": {"Memo": lambda **kwargs: kwargs,
                                     "Payment": lambda **kwargs: kwargs},
        "xrpl.transaction": {"autofill_and_sign": autofill_and_sign, "submit": submit},
    }
    for name, attributes in sdk.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr("builtins.input", authorize)

    quote = {"id": "0123456789abcdef0123456789abcdef", "mode": "xrpl-testnet",
             "network": "xrpl:1", "amount_drops": "3000000", "buyer_address": "payer",
             "pay_to": "recipient", "memo": "0123456789abcdef0123456789abcdef",
             "expires_at": (start + timedelta(minutes=5)).isoformat()}
    recovery = tmp_path / "existing-recovery.json"
    original_bytes = b'{"quote":"preserve this recovery state"}'
    recovery.write_bytes(original_bytes)
    state = {"quote": dict(quote), "session_cookie": "private-existing-cookie"}
    expected_state = {"quote": dict(quote), "session_cookie": "private-existing-cookie"}
    args = SimpleNamespace(max_testnet_drops=10_000_000, max_fee_drops=100, state=recovery)

    with pytest.raises(buyer.BuyerError, match="Quote expired"):
        buyer.sign_once(quote, SimpleNamespace(classic_address="payer"), args, state, object(), {})

    assert "submit" not in calls
    assert calls == ([] if expires_during == "authorization_prompt" else ["autofill_and_sign"])
    assert state == expected_state
    assert "transaction_hash" not in state and "submission_started" not in state
    assert recovery.read_bytes() == original_bytes


@pytest.fixture
def signing_case(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[3] / "examples" / "buyer_client.py"
    spec = importlib.util.spec_from_file_location("external_buyer_registration", path)
    buyer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(buyer)
    calls, saved = [], []
    proof = "A" * 64
    sdk = {
        "xrpl": {}, "xrpl.models": {},
        "xrpl.clients": {"JsonRpcClient": lambda _url: object()},
        "xrpl.models.transactions": {"Memo": lambda **kwargs: kwargs,
                                     "Payment": lambda **kwargs: kwargs},
        "xrpl.transaction": {
            "autofill_and_sign": lambda *_: SimpleNamespace(fee="12", get_hash=lambda: proof),
            "submit": lambda *_: calls.append("submit"),
        },
    }
    for name, attributes in sdk.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr("builtins.input", lambda _: "PAY TESTNET")

    def save(_path, state, _client):
        calls.append("save")
        saved.append(deepcopy(state))

    monkeypatch.setattr(buyer, "save_state", save)
    quote = {"id": "0123456789abcdef0123456789abcdef", "mode": "xrpl-testnet",
             "network": "xrpl:1", "amount_drops": "3000000", "buyer_address": "payer",
             "pay_to": "recipient", "memo": "0123456789abcdef0123456789abcdef",
             "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
             "status": "quoted", "transaction_hash": None}
    return SimpleNamespace(buyer=buyer, quote=quote, proof=proof, calls=calls, saved=saved,
                           state={"quote": dict(quote)}, wallet=SimpleNamespace(classic_address="payer"),
                           args=SimpleNamespace(max_testnet_drops=10_000_000, max_fee_drops=100,
                                                state=tmp_path / "recovery.json"),
                           client=object(), headers={"Origin": "http://127.0.0.1:5173",
                                                     "X-CSRF-Token": "synthetic-token"})


def invoke_signing(case):
    return case.buyer.sign_once(case.quote, case.wallet, case.args, case.state,
                               case.client, case.headers)


@pytest.mark.parametrize("status", ["pending", "paid"])
def test_signed_hash_is_saved_and_registered_before_any_submission(monkeypatch, signing_case, status):
    case = signing_case

    def register(client, method, path, **kwargs):
        case.calls.append("register")
        assert client is case.client and method == "POST"
        assert path == f"/api/quotes/{case.quote['id']}/confirm"
        assert kwargs == {"json": {"transaction_hash": case.proof}, "headers": case.headers}
        assert case.saved[-1]["transaction_hash"] == case.proof
        assert "submission_started" not in case.saved[-1]
        return {**case.quote, "transaction_hash": case.proof, "status": status}

    monkeypatch.setattr(case.buyer, "request_json", register)
    assert invoke_signing(case) == case.proof
    assert case.state["payment_attempt_registered"] is True
    assert case.state["quote"]["status"] == status
    if status == "paid":
        assert case.calls == ["save", "register", "save"]
        assert "submission_started" not in case.state
    else:
        assert case.calls == ["save", "register", "save", "save", "submit"]
        assert case.saved[-1]["submission_started"] is True
        assert case.saved[-1]["payment_attempt_registered"] is True


@pytest.mark.parametrize("failure", ["api_error", "unknown", "wrong_hash", "wrong_quote", "wrong_mode", "wrong_network", "quoted"])
def test_unconfirmed_registration_never_broadcasts(monkeypatch, signing_case, failure):
    case = signing_case

    def register(*_args, **_kwargs):
        if failure == "api_error":
            raise case.buyer.BuyerError("API refused registration")
        if failure == "unknown":
            raise httpx.ReadTimeout("Unknown registration outcome")
        response = {**case.quote, "transaction_hash": case.proof, "status": "pending"}
        response.update({"wrong_hash": {"transaction_hash": "B" * 64},
                         "wrong_quote": {"id": "another-quote"},
                         "wrong_mode": {"mode": "simulated"},
                         "wrong_network": {"network": "simulation"},
                         "quoted": {"status": "quoted"}}[failure])
        return response

    monkeypatch.setattr(case.buyer, "request_json", register)
    with pytest.raises((case.buyer.BuyerError, httpx.ReadTimeout)):
        invoke_signing(case)
    assert "submit" not in case.calls
    assert case.state["transaction_hash"] == case.proof
    assert case.saved[-1]["transaction_hash"] == case.proof
    assert "submission_started" not in case.state


def test_expiry_during_registration_preserves_attempt_without_broadcast(monkeypatch, signing_case):
    case = signing_case

    class ExpiredClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(case.quote["expires_at"])

    def register(*_args, **_kwargs):
        monkeypatch.setattr(case.buyer, "datetime", ExpiredClock)
        return {**case.quote, "transaction_hash": case.proof, "status": "pending"}

    monkeypatch.setattr(case.buyer, "request_json", register)
    with pytest.raises(case.buyer.BuyerError, match="Quote expired"):
        invoke_signing(case)
    assert "submit" not in case.calls and "submission_started" not in case.state
    assert case.state["payment_attempt_registered"] is True
    assert case.saved[-1]["quote"]["transaction_hash"] == case.proof


def test_registered_attempt_reconciles_after_submission_crosses_expiry(monkeypatch, signing_case):
    """Exercise real API persistence/expiry checks with only ledger signing/I/O stubbed."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from sliver_api import payments
    from sliver_api.config import Settings
    from sliver_api.main import create_app
    from sliver_api.models import Quote, utcnow
    from sliver_api.seed import DEMO_ACCOUNTS, seed_accounts
    from sliver_api.storage import MemoryStore

    # Reuse the normal seller/reviewer publication harness, including its API gate.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "api" / "tests"))
    from test_transactions import approved, buyer as api_buyer, quote_for, valid_result, PAY_TO, PAYER
    from test_api import PASSWORD, CSV

    case = signing_case
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    try:
        seed_accounts(engine, {key: PASSWORD for _, _, key in DEMO_ACCOUNTS})
        app = create_app(Settings(database_url="sqlite://", payment_mode="xrpl-testnet", xrpl_pay_to=PAY_TO),
                         engine=engine, store=MemoryStore())
        _, resource = approved(app)
        with api_buyer(app) as client:
            case.client = client
            case.headers = {key: client.headers[key] for key in ("Origin", "X-CSRF-Token")}
            case.quote = quote_for(client, resource, True)
            case.wallet = SimpleNamespace(classic_address=PAYER)
            case.state = {"quote": dict(case.quote)}
            submitted = []
            monkeypatch.setattr(payments, "fetch_transaction", lambda *_: {"error": "txnNotFound"})

            def submit(*_args):
                with Session(engine) as db:
                    attempt = db.get(Quote, case.quote["id"])
                    assert attempt.status == "pending" and attempt.transaction_hash == case.proof
                    assert attempt.settled_transaction_hash is None
                    attempt.expires_at = utcnow() - timedelta(seconds=1)
                    db.commit()
                submitted.append(case.proof)
                monkeypatch.setattr(payments, "fetch_transaction", lambda *_: valid_result(case.quote))

            monkeypatch.setattr(sys.modules["xrpl.transaction"], "submit", submit)
            assert invoke_signing(case) == case.proof
            assert submitted == [case.proof]
            response = client.post(f"/api/quotes/{case.quote['id']}/confirm",
                                   json={"transaction_hash": case.proof}, headers=case.headers)
            assert response.status_code == 200 and response.json()["status"] == "paid"
            assert client.get(response.json()["download_url"]).content == CSV
            assert client.post(f"/api/quotes/{case.quote['id']}/confirm",
                               json={"transaction_hash": case.proof}, headers=case.headers).json() == response.json()
    finally:
        engine.dispose()
