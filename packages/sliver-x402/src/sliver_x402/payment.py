"""Build, check and sign the XRPL Payment for an `exact` requirement.

The transaction follows the official XRPL exact scheme and the t54 facilitator: Amount in drops
exactly as required, Destination = payTo, InvoiceID = SHA-256(invoiceId), SourceTag from
`extra.sourceTag`, a LastLedgerSequence bounded by maxTimeoutSeconds, a capped fee, and no
Memos, SendMax, DeliverMin, Paths or partial-payment flag. Every field of the autofilled
transaction is checked against an allow-list before the key signs it.
"""

import hashlib
import math
from typing import Any

from xrpl.clients import JsonRpcClient
from xrpl.ledger import get_latest_validated_ledger_sequence
from xrpl.models.transactions import Payment
from xrpl.transaction import autofill, sign
from xrpl.wallet import Wallet

from .wire import PaymentRejected, Requirement

TESTNET_RPC_URLS = (
    "https://s.altnet.rippletest.net:51234/",
    "https://clio.altnet.rippletest.net:51234/",
    "https://testnet.xrpl-labs.com/",
)
DEFAULT_MAX_FEE_DROPS = 1_000
LEDGER_CLOSE_SECONDS = 5
TF_PARTIAL_PAYMENT = 0x00020000
ALLOWED_FIELDS = frozenset(
    {
        "TransactionType",
        "Account",
        "Destination",
        "Amount",
        "Fee",
        "Sequence",
        "LastLedgerSequence",
        "InvoiceID",
        "SourceTag",
        "DestinationTag",
        "Flags",
        "NetworkID",
        "SigningPubKey",
        "TxnSignature",
    }
)


def invoice_id_field(invoice_id: str) -> str:
    """Payment.InvoiceID binding of the XRPL exact scheme: SHA-256(invoiceId), upper-case hex."""
    return hashlib.sha256(invoice_id.encode()).hexdigest().upper()


def last_ledger_bound(validated_ledger: int, max_timeout_seconds: int) -> int:
    """Highest LastLedgerSequence the scheme allows: validated + ceil(timeout / 5) + 2."""
    return validated_ledger + math.ceil(max_timeout_seconds / LEDGER_CLOSE_SECONDS) + 2


def check_rpc_url(rpc_url: str) -> str:
    if rpc_url not in TESTNET_RPC_URLS:
        raise PaymentRejected(f"XRPL RPC must be one of the Testnet endpoints {list(TESTNET_RPC_URLS)}")
    return rpc_url


def build_payment(
    requirement: Requirement, account: str, *, validated_ledger: int, **autofilled: Any
) -> Payment:
    """The unsigned Payment. `autofilled` may carry `sequence` and `fee` for offline signing."""
    return Payment(
        account=account,
        destination=requirement.pay_to,
        amount=str(requirement.amount_drops),
        invoice_id=invoice_id_field(requirement.invoice_id),
        source_tag=requirement.source_tag,
        destination_tag=requirement.destination_tag,
        last_ledger_sequence=last_ledger_bound(validated_ledger, requirement.max_timeout_seconds),
        **autofilled,
    )


def check_payment(
    tx: Payment, requirement: Requirement, *, account: str, validated_ledger: int, max_fee_drops: int
) -> None:
    """Raise PaymentRejected unless `tx` is exactly the Payment the requirement asks for."""
    fields = tx.to_xrpl()
    unexpected = sorted(set(fields) - ALLOWED_FIELDS)
    if unexpected:
        raise PaymentRejected(f"transaction carries fields the scheme forbids: {unexpected}")
    expected = {
        "TransactionType": "Payment",
        "Account": account,
        "Destination": requirement.pay_to,
        "Amount": str(requirement.amount_drops),
        "InvoiceID": invoice_id_field(requirement.invoice_id),
    }
    for key, value in expected.items():
        if fields.get(key) != value:
            raise PaymentRejected(f"{key} is {fields.get(key)!r}, expected {value!r}")
    for key, value in (
        ("SourceTag", requirement.source_tag),
        ("DestinationTag", requirement.destination_tag),
    ):
        if fields.get(key) != value:
            raise PaymentRejected(f"{key} is {fields.get(key)!r}, expected {value!r}")
    if int(fields.get("Flags") or 0) & TF_PARTIAL_PAYMENT:
        raise PaymentRejected("partial payments are not allowed")
    last = fields.get("LastLedgerSequence")
    bound = last_ledger_bound(validated_ledger, requirement.max_timeout_seconds)
    if type(last) is not int or not validated_ledger < last <= bound:
        raise PaymentRejected(f"LastLedgerSequence must be above {validated_ledger} and at most {bound}")
    fee = fields.get("Fee")
    if not isinstance(fee, str) or not fee.isdigit() or int(fee) > max_fee_drops:
        raise PaymentRejected(f"fee {fee!r} drops exceeds the cap of {max_fee_drops} drops")


def sign_payment(
    requirement: Requirement,
    wallet: Wallet,
    client: JsonRpcClient,
    *,
    max_fee_drops: int = DEFAULT_MAX_FEE_DROPS,
) -> Payment:
    """Autofill Sequence and Fee from the ledger, check every field, then sign locally."""
    validated = get_latest_validated_ledger_sequence(client)
    filled = autofill(build_payment(requirement, wallet.address, validated_ledger=validated), client)
    check_payment(
        filled, requirement, account=wallet.address, validated_ledger=validated, max_fee_drops=max_fee_drops
    )
    return sign(filled, wallet)


def sign_offline(
    requirement: Requirement,
    wallet: Wallet,
    *,
    sequence: int,
    fee_drops: int,
    validated_ledger: int,
    max_fee_drops: int = DEFAULT_MAX_FEE_DROPS,
) -> Payment:
    """Same checks as `sign_payment` without network access (tests, air-gapped signing)."""
    tx = build_payment(
        requirement, wallet.address, validated_ledger=validated_ledger, sequence=sequence, fee=str(fee_drops)
    )
    check_payment(
        tx,
        requirement,
        account=wallet.address,
        validated_ledger=validated_ledger,
        max_fee_drops=max_fee_drops,
    )
    return sign(tx, wallet)
