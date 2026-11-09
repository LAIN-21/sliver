import hashlib
import threading
from pathlib import Path

import httpx
import pytest
from xrpl.wallet import Wallet

from sliver_mcp.buyer import Refused, agent_note
from sliver_mcp.store import iso, now

CHEAP = "11111111-1111-4111-8111-111111111111"  # $1.50, delivers bytes matching its SHA-256
CUSTOMS = "22222222-2222-4222-8222-222222222222"  # $3.00, delivered bytes do not match
BERTH = "33333333-3333-4333-8333-333333333333"  # $12.00


def refused(buyer, *args, **kwargs) -> str:
    with pytest.raises(Refused) as caught:
        buyer.buy(*args, **kwargs)
    return caught.value.code


def test_purchase_saves_verified_file_and_returns_transaction(buyer, stub, config):
    result = buyer.buy(CHEAP, budget_usd=5)
    assert result["status"] == "delivered" and result["sha256_verified"] is True
    assert Path(result["file"]).read_bytes() == stub.data[CHEAP]
    assert result["sha256"] == hashlib.sha256(stub.data[CHEAP]).hexdigest()
    (payment,) = stub.payments
    assert result["tx_hash"] and result["explorer_url"].endswith(result["tx_hash"])
    assert result["receipt"]["transaction"]["hash"] == result["tx_hash"]
    assert payment["Amount"] == "600000" and payment["Destination"] == stub.pay_to
    assert result["amount_xrp"] == 0.6 and result["price_usd"] == 1.5
    assert result["spent_last_24h_usd"] == 1.5
    assert buyer.store.purchases()[0]["status"] == "delivered"
    assert buyer.store.payee(f"{config.api_url}|platform") == stub.pay_to


def test_refuses_without_a_budget_before_any_request(buyer, stub, signer):
    assert refused(buyer, CHEAP, budget_usd=None) == "no_budget"
    assert refused(buyer, CHEAP, budget_usd=0) == "no_budget"
    assert signer.signed == 0 and not stub.invoices


def test_refuses_over_budget(buyer, signer):
    assert refused(buyer, CHEAP, budget_usd=1.49) == "over_budget"
    assert signer.signed == 0


def test_refuses_over_the_per_purchase_cap(buyer, signer):
    assert refused(buyer, BERTH, budget_usd=50) == "over_purchase_cap"
    assert signer.signed == 0


def test_refuses_over_the_daily_cap(buyer, signer):
    for index in range(13):  # 13 x $1.50 = $19.50 of the $20.00 cap
        buyer.store.save_purchase(
            {"id": str(index), "created_at": iso(now()), "status": "delivered", "price_minor": 150}
        )
    assert refused(buyer, CHEAP, budget_usd=5) == "over_daily_cap"
    assert signer.signed == 0


def test_spend_older_than_a_day_does_not_count(buyer):
    buyer.store.save_purchase(
        {"id": "old", "created_at": "2020-01-01T00:00:00Z", "status": "delivered", "price_minor": 2000}
    )
    assert buyer.buy(CHEAP, budget_usd=5)["status"] == "delivered"


def test_refuses_a_payee_that_differs_from_the_pinned_platform(buyer, stub, signer):
    buyer.buy(CHEAP, budget_usd=5)
    stub.pay_to = Wallet.create().address
    assert refused(buyer, CHEAP, budget_usd=5) == "challenge_rejected"
    assert signer.signed == 1


def test_one_platform_payee_serves_every_seller(buyer, stub, config):
    buyer.store.pin_payee(f"{config.api_url}|Harbour Analytics (demo seller)", Wallet.create().address)
    stub.listings[CHEAP]["seller"] = {"name": "Another seller"}
    assert buyer.buy(CHEAP, budget_usd=5)["status"] == "delivered"  # an old per-seller pin is ignored
    stub.listings[CHEAP]["seller"] = {"name": "Harbour Analytics (demo seller)"}
    assert buyer.buy(CHEAP, budget_usd=5)["status"] == "delivered"
    assert {payment["Destination"] for payment in stub.payments} == {stub.pay_to}


def test_refuses_an_amount_that_differs_from_the_listing_price(buyer, stub, signer):
    stub.drops_per_usd = 800_000
    assert refused(buyer, CHEAP, budget_usd=5) == "challenge_rejected"
    assert signer.signed == 0


def test_refuses_any_network_but_testnet(buyer, stub, signer):
    stub.network = "xrpl:0"
    assert refused(buyer, CHEAP, budget_usd=5) == "challenge_rejected"
    assert signer.signed == 0


def test_refuses_while_another_purchase_is_in_flight(buyer, signer):
    holding, release = threading.Event(), threading.Event()

    def hold():
        with buyer.store.one_purchase():
            holding.set()
            release.wait(5)

    thread = threading.Thread(target=hold)
    thread.start()
    holding.wait(5)
    try:
        assert refused(buyer, CHEAP, budget_usd=5) == "purchase_in_flight"
    finally:
        release.set()
        thread.join()
    assert signer.signed == 0


def test_retries_the_same_payment_while_settlement_is_pending(buyer, stub, signer):
    stub.pending_responses = 2
    result = buyer.buy(CHEAP, budget_usd=5)
    assert result["status"] == "delivered"
    assert signer.signed == 1 and len(stub.payments) == 3
    assert len({payment["InvoiceID"] for payment in stub.payments}) == 1


def test_bytes_that_fail_the_sha256_check_are_quarantined(buyer):
    result = buyer.buy(CUSTOMS, budget_usd=5)
    assert result["status"] == "delivered_unverified" and result["sha256_verified"] is False
    assert result["file"].endswith(".unverified") and "warning" in result


def test_failed_delivery_still_counts_toward_the_daily_cap(buyer, stub):
    stub.pending_responses = 99
    assert refused(buyer, CHEAP, budget_usd=5) == "payment_not_delivered"
    assert buyer.store.purchases()[0]["status"] == "failed"
    assert buyer.store.spent_minor() == 150


def test_rejects_path_like_resource_ids(buyer):
    assert refused(buyer, "../../etc", budget_usd=5) == "invalid_resource_id"


def test_state_files_are_owner_only(buyer, config):
    buyer.buy(CHEAP, budget_usd=5)
    assert config.home.stat().st_mode & 0o777 == 0o700
    for name in ("purchases.json", "payees.json"):
        assert (config.home / name).stat().st_mode & 0o777 == 0o600


def test_refuses_a_listing_for_a_different_resource_id(buyer, stub, signer):
    stub.listings[CHEAP]["id"] = CUSTOMS
    assert refused(buyer, CHEAP, budget_usd=5) == "bad_listing"
    assert signer.signed == 0


def test_a_non_json_challenge_is_refused_before_signing(buyer, stub, signer):
    stub.overrides["/api/resources/"] = httpx.Response(402, text="not json")
    assert refused(buyer, CHEAP, budget_usd=5) == "challenge_rejected"
    stub.overrides["/api/resources/"] = httpx.Response(500, json=["not", "an", "object"])
    assert refused(buyer, CHEAP, budget_usd=5) == "http_error"
    assert signer.signed == 0


def test_a_non_json_receipt_does_not_lose_the_delivery(buyer, stub):
    stub.overrides["/api/receipts/"] = httpx.Response(200, text="<html>")
    result = buyer.buy(CHEAP, budget_usd=5)
    assert result["status"] == "delivered" and result["receipt"] is None
    assert buyer.store.purchases()[0]["status"] == "delivered"


def test_a_save_failure_after_payment_reports_the_spend(buyer, tmp_path):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("x")
    with pytest.raises(Refused) as caught:
        buyer.buy(CHEAP, budget_usd=5, output_dir=str(blocked))
    assert caught.value.code == "save_failed"
    assert caught.value.paid["spent_usd"] == 1.5 and caught.value.paid["tx_hash"]
    assert buyer.store.purchases()[0]["status"] == "delivered_unsaved"
    assert buyer.store.spent_minor() == 150


def test_a_non_object_error_after_payment_is_recorded_as_failed(buyer, stub):
    stub.paid_response = httpx.Response(502, json=["upstream", "error"])
    with pytest.raises(Refused) as caught:
        buyer.buy(CHEAP, budget_usd=5)
    assert caught.value.code == "payment_not_delivered" and caught.value.paid["tx_hash"]
    assert "http_error" in caught.value.message
    assert buyer.store.purchases()[0]["status"] == "failed"
    assert buyer.store.spent_minor() == 150


def notes(stub) -> list[tuple[bool, str | None]]:
    """(paid?, X-Sliver-Agent-Note decoded from UTF-8) for every request to the data endpoint."""
    sent = []
    for request in stub.data_requests:
        raw = [value for key, value in request.headers.raw if key.lower() == b"x-sliver-agent-note"]
        sent.append(("PAYMENT-SIGNATURE" in request.headers, raw[0].decode("utf-8") if raw else None))
    return sent


def test_the_reason_is_sent_as_the_agent_note_on_the_challenge_and_the_payment(buyer, stub):
    reason = "Weekly SGSIN-CNSHA spot rates since September to quote a shipment"
    assert buyer.buy(CHEAP, budget_usd=5, reason=reason)["status"] == "delivered"
    assert notes(stub) == [(False, reason), (True, reason)]


def test_the_agent_note_rides_on_every_paid_retry(buyer, stub):
    stub.pending_responses = 2
    buyer.buy(CHEAP, budget_usd=5, reason="Port congestion check")
    assert notes(stub) == [(False, "Port congestion check")] + [(True, "Port congestion check")] * 3


def test_no_reason_means_no_agent_note_header(buyer, stub):
    buyer.buy(CHEAP, budget_usd=5)
    buyer.buy(CHEAP, budget_usd=5, reason=" \n\t ")
    assert notes(stub) == [(False, None), (True, None)] * 2


def test_the_agent_note_is_trimmed_to_200_characters_and_single_spaced(buyer, stub):
    reason = "  Rates\tfor a\r\nquote \u202e\x00" + "é" * 300
    buyer.buy(CHEAP, budget_usd=5, reason=reason)
    expected = ("Rates for a quote " + "é" * 300)[:200]
    assert notes(stub) == [(False, expected), (True, expected)]
    assert len(expected) == 200


def test_agent_note_cleaning():
    assert agent_note(None) is None and agent_note("") is None and agent_note("\u200b\x07 ") is None
    assert agent_note(" a \n b ") == "a b"
    assert agent_note("x" * 250) == "x" * 200
    assert agent_note("Données de fret 🚢") == "Données de fret 🚢"
