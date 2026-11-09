import base64
import hashlib
import json
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import PLATFORM_ADDRESS
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from x402_xrpl.client.presigned_payment_payer import build_payment_header_for_signed_blob
from x402_xrpl.types import PaymentRequirements, PaymentVerifyResponse, SettlementResponse
from xrpl.models import Payment as XrplPayment
from xrpl.transaction import sign
from xrpl.wallet import Wallet

from sliver_api.config import Settings
from sliver_api.main import create_app
from sliver_api.models import Payment, Resource, User
from sliver_api.payments.ledger_check import TF_PARTIAL_PAYMENT, settlement_problem
from sliver_api.payments.x402 import drops_for, invoice_id_field, transaction_hash
from sliver_api.seed import seed

FIXTURES = Path(__file__).parent / "fixtures" / "catalog"
SELLER = Wallet.create()
BUYER = Wallet.create()


class StubFacilitator:
    def __init__(self):
        self.valid, self.invalid_reason = True, None
        self.settle_success, self.settle_error, self.settle_tx = True, None, None
        self.settle_raises = False
        self.verified, self.settled = [], []

    def verify(self, header, requirements):
        self.verified.append(header)
        return PaymentVerifyResponse(
            is_valid=self.valid, invalid_reason=self.invalid_reason, payer=BUYER.address
        )

    def settle(self, header, requirements):
        self.settled.append(header)
        if self.settle_raises:
            raise TimeoutError("facilitator timed out")
        payload = json.loads(base64.b64decode(header))
        tx = (
            self.settle_tx
            if self.settle_tx is not None
            else transaction_hash(payload["payload"]["signedTxBlob"])
        )
        return SettlementResponse(
            success=self.settle_success,
            transaction=tx if self.settle_success or self.settle_tx else "",
            network="xrpl:1",
            payer=BUYER.address,
            error_reason=self.settle_error,
        )


class StubLedger:
    """Answers `tx` lookups from the signed blobs the test submitted, optionally tampered."""

    def __init__(self):
        self.transactions: dict[str, dict] = {}
        self.validated = True
        self.overrides: dict = {}

    def record(self, signed, delivered: str):
        tx_json = signed.to_xrpl()
        self.transactions[signed.get_hash()] = {"tx_json": tx_json, "delivered": delivered}

    def transaction(self, tx_hash):
        found = self.transactions.get(tx_hash)
        if found is None:
            return None
        tx_json = {**found["tx_json"], **self.overrides.get("tx_json", {})}
        meta = {"TransactionResult": "tesSUCCESS", "delivered_amount": found["delivered"]}
        meta.update(self.overrides.get("meta", {}))
        return {
            "validated": self.validated,
            "tx_json": tx_json,
            "meta": meta,
            "ledger_index": 123,
            "hash": tx_hash,
        }


@pytest.fixture
def facilitator():
    return StubFacilitator()


@pytest.fixture
def ledger():
    return StubLedger()


@pytest.fixture
def market(settings, engine, store, sessions, facilitator, ledger):
    seed(sessions, store, FIXTURES)
    with sessions() as db:
        db.scalar(select(User)).xrpl_address = SELLER.address
        db.commit()
        sliver = db.scalar(select(Resource).where(Resource.title.endswith("October 2026")))
        resource_id = sliver.id
    app = create_app(settings, engine=engine, store=store, facilitator=facilitator, ledger=ledger)
    app.state.purchases.sleep = lambda _seconds: None
    app.state.purchases.ledger_attempts = 2
    with TestClient(app) as client:
        yield client, resource_id


def challenge(client, resource_id):
    response = client.get(f"/api/resources/{resource_id}/data")
    assert response.status_code == 402, response.text
    return response


def sign_payment(requirements: dict, *, amount=None, sequence=1, invoice=None):
    accepted = PaymentRequirements.from_dict(requirements)
    invoice_id = accepted.invoice_id()
    tx = XrplPayment(
        account=BUYER.address,
        destination=accepted.pay_to,
        amount=amount or accepted.amount,
        sequence=sequence,
        fee="12",
        last_ledger_sequence=10_000,
        invoice_id=invoice_id_field(invoice or invoice_id),
        source_tag=accepted.extra["sourceTag"],
    )
    signed = sign(tx, BUYER)
    header = build_payment_header_for_signed_blob(
        req=accepted, signed_tx_blob=signed.blob(), invoice_id=invoice_id
    )
    return signed, header


def pay(client, resource_id, ledger, *, delivered=None, **sign_options):
    accepted = challenge(client, resource_id).json()["accepts"][0]
    signed, header = sign_payment(accepted, **sign_options)
    ledger.record(signed, delivered or accepted["amount"])
    return (
        client.get(f"/api/resources/{resource_id}/data", headers={"PAYMENT-SIGNATURE": header}),
        signed,
        header,
    )


def test_unpaid_request_gets_an_x402_v2_challenge(market, settings):
    client, resource_id = market
    response = challenge(client, resource_id)
    body = response.json()
    assert json.loads(base64.b64decode(response.headers["PAYMENT-REQUIRED"])) == body
    assert body["x402Version"] == 2
    assert body["resource"]["url"].endswith(f"/api/resources/{resource_id}/data")
    (accepted,) = body["accepts"]
    assert accepted["scheme"] == "exact" and accepted["network"] == "xrpl:1" and accepted["asset"] == "XRP"
    assert accepted["payTo"] == PLATFORM_ADDRESS
    assert accepted["amount"] == drops_for(450, settings.drops_per_usd) == "1800000"
    assert accepted["extra"]["sourceTag"] == 804681468 and accepted["extra"]["areFeesSponsored"] is False
    assert len(accepted["extra"]["invoiceId"]) == 32


def test_valid_payment_delivers_exact_bytes_with_receipt(market, store, sessions, facilitator, ledger):
    client, resource_id = market
    response, signed, _ = pay(client, resource_id, ledger)
    assert response.status_code == 200, response.text
    with sessions() as db:
        sliver = db.get(Resource, resource_id)
    assert response.content == store.get(sliver.object_key)
    assert hashlib.sha256(response.content).hexdigest() == sliver.sha256
    settlement = json.loads(base64.b64decode(response.headers["PAYMENT-RESPONSE"]))
    assert settlement == {
        "success": True,
        "transaction": signed.get_hash(),
        "network": "xrpl:1",
        "payer": BUYER.address,
    }
    receipt = client.get(f"/api/receipts/{response.headers['X-Sliver-Receipt']}").json()
    assert receipt["transaction"]["hash"] == signed.get_hash()
    assert (
        receipt["transaction"]["explorer_url"] == f"https://testnet.xrpl.org/transactions/{signed.get_hash()}"
    )
    assert receipt["pay_to"] == PLATFORM_ADDRESS and receipt["amount"]["usd_minor"] == 450
    assert len(facilitator.settled) == 1


def test_replaying_the_same_payment_redelivers_without_settling_again(market, facilitator, ledger):
    client, resource_id = market
    first, _, header = pay(client, resource_id, ledger)
    again = client.get(f"/api/resources/{resource_id}/data", headers={"PAYMENT-SIGNATURE": header})
    assert again.status_code == 200 and again.content == first.content
    assert len(facilitator.settled) == 1


def test_another_transaction_for_a_paid_invoice_is_rejected(market, ledger):
    client, resource_id = market
    first, _, header = pay(client, resource_id, ledger)
    accepted = json.loads(base64.b64decode(header))["accepted"]
    _, rival = sign_payment(accepted, sequence=2)
    response = client.get(f"/api/resources/{resource_id}/data", headers={"PAYMENT-SIGNATURE": rival})
    assert response.status_code == 409 and response.json()["error"]["code"] == "invoice_already_paid"


def test_one_transaction_cannot_pay_two_invoices(market, ledger):
    client, resource_id = market
    first, signed, _ = pay(client, resource_id, ledger)
    assert first.status_code == 200
    second = PaymentRequirements.from_dict(challenge(client, resource_id).json()["accepts"][0])
    # Present the already-settled transaction as payment for a new invoice.
    header = build_payment_header_for_signed_blob(
        req=second, signed_tx_blob=signed.blob(), invoice_id=second.invoice_id()
    )
    response = client.get(f"/api/resources/{resource_id}/data", headers={"PAYMENT-SIGNATURE": header})
    assert response.status_code == 409 and response.json()["error"]["code"] == "transaction_already_used"


def test_failed_verification_returns_a_fresh_challenge_and_no_data(market, facilitator, ledger):
    client, resource_id = market
    facilitator.valid, facilitator.invalid_reason = False, "amount_mismatch"
    response, _, _ = pay(client, resource_id, ledger)
    assert response.status_code == 402
    assert response.json()["error"] == "payment_invalid:amount_mismatch"
    assert facilitator.settled == []


def test_settlement_rejected_before_submission_allows_a_retry(market, sessions, facilitator, ledger):
    client, resource_id = market
    facilitator.settle_success, facilitator.settle_error = False, "insufficient_funds"
    response, _, header = pay(client, resource_id, ledger)
    assert response.status_code == 402 and response.json()["error"] == "settle_failed:insufficient_funds"
    invoice = json.loads(base64.b64decode(header))["accepted"]["extra"]["invoiceId"]
    with sessions() as db:
        payment = db.scalar(select(Payment).where(Payment.invoice_id == invoice))
    assert (payment.status, payment.tx_hash) == ("required", None)


def test_unknown_settlement_outcome_is_reconciled_on_retry(market, facilitator, ledger):
    client, resource_id = market
    facilitator.settle_raises = True
    response, _, header = pay(client, resource_id, ledger)
    assert response.status_code == 409 and response.json()["error"]["code"] == "settlement_status_unknown"
    facilitator.settle_raises = False
    retry = client.get(f"/api/resources/{resource_id}/data", headers={"PAYMENT-SIGNATURE": header})
    assert retry.status_code == 200
    assert len(facilitator.settled) == 1  # the retry reconciled from the ledger instead of settling again


def test_unvalidated_settlement_is_pending_until_the_ledger_confirms(market, facilitator, ledger):
    client, resource_id = market
    ledger.validated = False
    response, _, header = pay(client, resource_id, ledger)
    assert response.status_code == 409 and response.json()["error"]["code"] == "settlement_pending"
    ledger.validated = True
    retry = client.get(f"/api/resources/{resource_id}/data", headers={"PAYMENT-SIGNATURE": header})
    assert retry.status_code == 200 and len(facilitator.settled) == 1


def test_ledger_disagreement_fails_the_invoice_without_delivering(market, sessions, ledger):
    client, resource_id = market
    response, _, header = pay(client, resource_id, ledger, delivered="1")
    assert response.status_code == 502
    assert "wrong_amount" in response.json()["error"]["message"]
    invoice = json.loads(base64.b64decode(header))["accepted"]["extra"]["invoiceId"]
    with sessions() as db:
        payment = db.scalar(select(Payment).where(Payment.invoice_id == invoice))
    assert payment.status == "failed" and payment.failure_reason == "ledger_check:wrong_amount"


def test_corrupted_data_is_never_paid_for(market, store, sessions, facilitator, ledger):
    client, resource_id = market
    with sessions() as db:
        key = db.get(Resource, resource_id).object_key
    store.objects[key] = b"tampered"
    response, _, _ = pay(client, resource_id, ledger)
    assert response.status_code == 503 and response.json()["error"]["code"] == "integrity_check_failed"
    assert facilitator.settled == []


def test_tampered_requirements_are_rejected_before_verification(market, facilitator, ledger):
    client, resource_id = market
    accepted = challenge(client, resource_id).json()["accepts"][0]
    cheaper = {**accepted, "amount": "1"}
    _, header = sign_payment(cheaper)
    response = client.get(f"/api/resources/{resource_id}/data", headers={"PAYMENT-SIGNATURE": header})
    assert response.status_code == 402 and response.json()["error"] == "requirements_mismatch"
    assert facilitator.verified == []


def test_unknown_invoice_gets_a_fresh_challenge(market):
    client, resource_id = market
    accepted = challenge(client, resource_id).json()["accepts"][0]
    forged = {**accepted, "extra": {**accepted["extra"], "invoiceId": "0" * 32}}
    _, header = sign_payment(forged)
    response = client.get(f"/api/resources/{resource_id}/data", headers={"PAYMENT-SIGNATURE": header})
    assert response.status_code == 402 and response.json()["error"] == "unknown_invoice"


def test_expired_invoice_gets_a_fresh_challenge(market, sessions):
    client, resource_id = market
    accepted = challenge(client, resource_id).json()["accepts"][0]
    with sessions() as db:
        payment = db.scalar(select(Payment).where(Payment.invoice_id == accepted["extra"]["invoiceId"]))
        payment.expires_at -= timedelta(hours=1)
        db.commit()
    _, header = sign_payment(accepted)
    response = client.get(f"/api/resources/{resource_id}/data", headers={"PAYMENT-SIGNATURE": header})
    assert response.status_code == 402 and response.json()["error"] == "invoice_expired"


def test_garbage_payment_header_is_a_client_error(market):
    client, resource_id = market
    response = client.get(f"/api/resources/{resource_id}/data", headers={"PAYMENT-SIGNATURE": "not-base64!"})
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_payment"


def test_seller_without_an_address_cannot_sell(market, sessions):
    client, resource_id = market
    with sessions() as db:
        db.scalar(select(User)).xrpl_address = None
        db.commit()
    response = client.get(f"/api/resources/{resource_id}/data")
    assert response.status_code == 503 and response.json()["error"]["code"] == "seller_cannot_receive"


def test_unpublished_resources_cannot_be_bought(market, sessions):
    client, resource_id = market
    with sessions() as db:
        db.get(Resource, resource_id).status = "draft"
        db.commit()
    assert client.get(f"/api/resources/{resource_id}/data").status_code == 404


def test_x402_directory_lists_paid_endpoints(market):
    client, resource_id = market
    items = client.get("/.well-known/x402").json()["items"]
    assert len(items) == 6
    october = next(item for item in items if item["url"].endswith(f"/api/resources/{resource_id}/data"))
    assert october["price"] == {
        "scheme": "exact",
        "network": "xrpl:1",
        "asset": "XRP",
        "amount": "1800000",
        "usdMinor": 450,
    }


def test_drops_round_up():
    assert drops_for(1, 400_000) == "4000"
    assert drops_for(1, 333_333) == "3334"


def valid_result(**changes):
    tx = {
        "TransactionType": "Payment",
        "Destination": "rDest",
        "Flags": 0,
        "InvoiceID": invoice_id_field("inv"),
    }
    meta = {"TransactionResult": "tesSUCCESS", "delivered_amount": "100"}
    result = {"validated": True, "tx_json": tx, "meta": meta}
    for key, value in changes.items():
        target = meta if key in meta else tx
        target[key] = value
    return result


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({}, None),
        ({"TransactionType": "OfferCreate"}, "not_a_payment"),
        ({"TransactionResult": "tecPATH_DRY"}, "failed_on_ledger:tecPATH_DRY"),
        ({"Flags": TF_PARTIAL_PAYMENT}, "partial_payment"),
        ({"Destination": "rOther"}, "wrong_destination"),
        ({"delivered_amount": "99"}, "wrong_amount"),
        ({"delivered_amount": {"currency": "USD", "value": "100", "issuer": "r"}}, "wrong_amount"),
        ({"InvoiceID": invoice_id_field("other")}, "invoice_binding_mismatch"),
    ],
)
def test_ledger_check_matrix(changes, problem):
    result = valid_result(**changes)
    assert settlement_problem(result, pay_to="rDest", amount_drops="100", invoice_id="inv") == problem


def test_ledger_check_requires_validation():
    result = valid_result()
    result["validated"] = False
    assert settlement_problem(result, pay_to="rDest", amount_drops="100", invoice_id="inv") == "not_validated"
    assert (
        settlement_problem(None, pay_to="rDest", amount_drops="100", invoice_id="inv")
        == "transaction_not_found"
    )


BASE = {
    "database_url": "postgresql+psycopg://u:p@db/sliver",
    "s3_endpoint_url": "http://127.0.0.1:9000",
    "s3_access_key_id": "k",
    "s3_secret_access_key": "s",
}


def test_mainnet_and_unknown_rpc_endpoints_are_refused():
    with pytest.raises(ValidationError):
        Settings(xrpl_network="xrpl:0", **BASE)
    with pytest.raises(ValidationError):
        Settings(xrpl_rpc_url="https://xrplcluster.com/", **BASE)
    with pytest.raises(ValidationError):
        Settings(xrpl_rpc_url="http://s.altnet.rippletest.net:51234/", **BASE)


def test_malformed_accepted_field_is_a_client_error(market):
    client, resource_id = market
    header = base64.b64encode(
        json.dumps({"x402Version": 2, "accepted": "oops", "payload": {"signedTxBlob": "00"}}).encode()
    ).decode()
    response = client.get(f"/api/resources/{resource_id}/data", headers={"PAYMENT-SIGNATURE": header})
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_payment"


def test_ledger_lookup_errors_after_settlement_are_retryable(market, facilitator, ledger):
    client, resource_id = market
    lookup = ledger.transaction

    def broken(_tx_hash):
        raise ConnectionError("rpc down")

    ledger.transaction = broken
    response, _, header = pay(client, resource_id, ledger)
    assert response.status_code == 409 and response.json()["error"]["code"] == "settlement_pending"
    ledger.transaction = lookup
    retry = client.get(f"/api/resources/{resource_id}/data", headers={"PAYMENT-SIGNATURE": header})
    assert retry.status_code == 200 and len(facilitator.settled) == 1


def test_expired_unpaid_invoices_are_purged(market, sessions):
    client, resource_id = market
    first = challenge(client, resource_id).json()["accepts"][0]["extra"]["invoiceId"]
    with sessions() as db:
        payment = db.scalar(select(Payment).where(Payment.invoice_id == first))
        payment.expires_at -= timedelta(hours=1)
        db.commit()
    challenge(client, resource_id)
    with sessions() as db:
        assert db.scalar(select(Payment).where(Payment.invoice_id == first)) is None
        assert len(db.scalars(select(Payment)).all()) == 1
