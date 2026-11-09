import base64
import hashlib
import json

import pytest
from xrpl.models import IssuedCurrencyAmount, Memo
from xrpl.models.transactions import Payment, Transaction
from xrpl.wallet import Wallet

from sliver_x402 import (
    PaymentRejected,
    build_payment,
    check_payment,
    check_rpc_url,
    decode_payment_response,
    encode_payment_signature,
    invoice_id_field,
    last_ledger_bound,
    parse_payment_required,
    select_requirement,
    sign_offline,
)

BUYER = Wallet.create()
SELLER = Wallet.create()
OTHER = Wallet.create()


def challenge(**overrides) -> dict:
    accepted = {
        "scheme": "exact",
        "network": "xrpl:1",
        "asset": "XRP",
        "amount": "600000",
        "payTo": SELLER.address,
        "maxTimeoutSeconds": 600,
        "extra": {"invoiceId": "a" * 32, "sourceTag": 804681468, "areFeesSponsored": False},
    }
    accepted.update(overrides)
    return {
        "x402Version": 2,
        "resource": {"url": "http://127.0.0.1:8000/api/resources/x/data", "mimeType": "text/csv"},
        "accepts": [accepted],
    }


def header(body: dict) -> str:
    return base64.b64encode(json.dumps(body).encode()).decode()


def requirement(**overrides):
    required = parse_payment_required(header(challenge(**overrides)))
    return select_requirement(required, amount_drops=600000, pay_to=SELLER.address)


def test_header_and_body_parse_the_same():
    body = challenge()
    assert parse_payment_required(header(body)) == parse_payment_required(body)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"amount": "600001"}, "differs from the expected 600000"),
        ({"amount": "600000.5"}, "positive integer number of drops"),
        ({"amount": 600000}, "positive integer number of drops"),
        ({"payTo": OTHER.address}, "differs from the expected"),
        ({"network": "xrpl:0"}, "network must be xrpl:1"),
        ({"asset": "RLUSD"}, "only XRP"),
        ({"scheme": "upto"}, "scheme must be exact"),
        ({"maxTimeoutSeconds": 86400}, "maxTimeoutSeconds"),
        ({"extra": {"sourceTag": 1}}, "invoiceId"),
        ({"extra": {"invoiceId": "a", "sourceTag": -1}}, "sourceTag"),
        ({"extra": {"invoiceId": "a", "areFeesSponsored": True}}, "sponsored"),
    ],
)
def test_requirements_that_differ_from_expectations_are_rejected(overrides, reason):
    with pytest.raises(PaymentRejected, match=reason):
        requirement(**overrides)


def test_only_testnet_can_be_expected():
    required = parse_payment_required(challenge(network="xrpl:0"))
    with pytest.raises(PaymentRejected, match="Testnet"):
        select_requirement(required, amount_drops=600000, pay_to=SELLER.address, network="xrpl:0")


@pytest.mark.parametrize("body", ["not base64!", header({"x402Version": 1}), header({"x402Version": 2})])
def test_malformed_challenges_are_rejected(body):
    with pytest.raises(PaymentRejected):
        parse_payment_required(body)


def test_signed_payment_carries_exactly_the_scheme_fields():
    accepted = requirement()
    signed = sign_offline(accepted, BUYER, sequence=7, fee_drops=12, validated_ledger=1000)
    fields = Transaction.from_blob(signed.blob()).to_xrpl()
    assert fields["TransactionType"] == "Payment"
    assert fields["Account"] == BUYER.address
    assert fields["Destination"] == SELLER.address
    assert fields["Amount"] == "600000"
    assert fields["InvoiceID"] == hashlib.sha256(b"a" * 32).hexdigest().upper()
    assert fields["SourceTag"] == 804681468
    assert fields["LastLedgerSequence"] == 1000 + 120 + 2 == last_ledger_bound(1000, 600)
    assert fields["Fee"] == "12"
    for forbidden in ("Memos", "SendMax", "Paths", "DeliverMin", "DestinationTag"):
        assert forbidden not in fields
    assert not fields.get("Flags", 0) & 0x00020000


def test_destination_tag_is_carried_when_required():
    accepted = requirement(extra={"invoiceId": "b", "sourceTag": 1, "destinationTag": 42})
    signed = sign_offline(accepted, BUYER, sequence=1, fee_drops=10, validated_ledger=5)
    assert Transaction.from_blob(signed.blob()).to_xrpl()["DestinationTag"] == 42


def test_fee_above_the_cap_is_refused():
    with pytest.raises(PaymentRejected, match="fee"):
        sign_offline(requirement(), BUYER, sequence=1, fee_drops=5000, validated_ledger=5, max_fee_drops=1000)


def payment(accepted, **changes):
    fields = {
        "account": BUYER.address,
        "destination": accepted.pay_to,
        "amount": "600000",
        "invoice_id": invoice_id_field(accepted.invoice_id),
        "source_tag": accepted.source_tag,
        "last_ledger_sequence": 1100,
        "sequence": 1,
        "fee": "12",
    }
    fields.update(changes)
    return Payment(**fields)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"memos": [Memo(memo_data="AB")]}, "forbids"),
        ({"send_max": IssuedCurrencyAmount(currency="USD", issuer=OTHER.address, value="1")}, "forbids"),
        ({"deliver_min": "1"}, "forbids"),
        ({"flags": 0x00020000}, "partial"),
        ({"amount": "600001"}, "Amount"),
        ({"destination": OTHER.address}, "Destination"),
        ({"invoice_id": "0" * 64}, "InvoiceID"),
        ({"source_tag": 1}, "SourceTag"),
        ({"last_ledger_sequence": 5000}, "LastLedgerSequence"),
        ({"last_ledger_sequence": 999}, "LastLedgerSequence"),
        ({"account": OTHER.address}, "Account"),
    ],
)
def test_check_payment_rejects_anything_but_the_exact_payment(changes, reason):
    accepted = requirement()
    with pytest.raises(PaymentRejected, match=reason):
        check_payment(
            payment(accepted, **changes),
            accepted,
            account=BUYER.address,
            validated_ledger=1000,
            max_fee_drops=1000,
        )


def test_built_payment_passes_its_own_check():
    accepted = requirement()
    tx = build_payment(accepted, BUYER.address, validated_ledger=1000, sequence=3, fee="10")
    check_payment(tx, accepted, account=BUYER.address, validated_ledger=1000, max_fee_drops=10)


def test_payment_signature_echoes_the_requirement_unchanged():
    body = challenge()
    required = parse_payment_required(body)
    accepted = select_requirement(required, amount_drops=600000, pay_to=SELLER.address)
    signed = sign_offline(accepted, BUYER, sequence=1, fee_drops=12, validated_ledger=10)
    envelope = json.loads(base64.b64decode(encode_payment_signature(required, accepted, signed.blob())))
    assert envelope == {
        "x402Version": 2,
        "resource": body["resource"],
        "accepted": body["accepts"][0],
        "payload": {"signedTxBlob": signed.blob(), "invoiceId": "a" * 32},
    }


def test_payment_response_decodes():
    settlement = {"success": True, "transaction": "AB" * 32, "network": "xrpl:1", "payer": BUYER.address}
    assert decode_payment_response(header(settlement)) == settlement
    with pytest.raises(ValueError):
        decode_payment_response(header({"transaction": "x"}))


def test_only_testnet_rpc_endpoints_are_allowed():
    assert check_rpc_url("https://testnet.xrpl-labs.com/")
    with pytest.raises(PaymentRejected):
        check_rpc_url("https://xrplcluster.com/")
