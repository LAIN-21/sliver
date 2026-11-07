"""Offline external-buyer payment-safety regressions; no ledger or keys needed."""

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


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
        buyer.sign_once(quote, SimpleNamespace(classic_address="payer"), args, state, object())

    assert "submit" not in calls
    assert calls == ([] if expires_during == "authorization_prompt" else ["autofill_and_sign"])
    assert state == expected_state
    assert "transaction_hash" not in state and "submission_started" not in state
    assert recovery.read_bytes() == original_bytes
