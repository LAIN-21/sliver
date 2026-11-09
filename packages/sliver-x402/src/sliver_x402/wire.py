"""x402 v2 wire format for the XRPL `exact` scheme: headers in, requirements checked, headers out.

Everything a server sends is untrusted. `select_requirement` only returns a requirement that
matches what the caller already expects to pay (amount, payee, network); anything else is
rejected before a key signs anything.
"""

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Any

X402_VERSION = 2
TESTNET = "xrpl:1"
EXPLORER_TX_URL = "https://testnet.xrpl.org/transactions/{}"
MAX_TIMEOUT_SECONDS = 3600
MAX_UINT32 = 2**32 - 1
MAX_XRP_DROPS = 100_000_000_000 * 1_000_000
CLASSIC_ADDRESS = re.compile(r"^r[1-9A-HJ-NP-Za-km-z]{24,34}$")
DROPS = re.compile(r"^[1-9][0-9]{0,17}$")


class PaymentRejected(ValueError):
    """A 402 challenge was refused before signing. Nothing was signed or sent."""


@dataclass(frozen=True)
class PaymentRequired:
    """A decoded `PAYMENT-REQUIRED` challenge."""

    resource: dict[str, Any]
    accepts: list[dict[str, Any]]
    error: str | None = None


@dataclass(frozen=True)
class Requirement:
    """One accepted `exact` XRPL requirement, validated. `raw` is echoed back unchanged."""

    raw: dict[str, Any]
    amount_drops: int
    pay_to: str
    network: str
    max_timeout_seconds: int
    invoice_id: str
    source_tag: int | None
    destination_tag: int | None


def b64_json(value: str, what: str) -> Any:
    try:
        return json.loads(base64.b64decode(value, validate=True))
    except (binascii.Error, ValueError, TypeError) as error:
        raise ValueError(f"{what} is not base64 JSON") from error


def encode_b64_json(body: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(body, separators=(",", ":"), sort_keys=True).encode()).decode()


def parse_payment_required(body: Any) -> PaymentRequired:
    """Parse a 402 body (dict) or a `PAYMENT-REQUIRED` header (base64 JSON string)."""
    if isinstance(body, str):
        try:
            body = b64_json(body, "PAYMENT-REQUIRED")
        except ValueError as error:
            raise PaymentRejected(str(error)) from None
    if not isinstance(body, dict):
        raise PaymentRejected("PAYMENT-REQUIRED is not a JSON object")
    if body.get("x402Version") != X402_VERSION:
        raise PaymentRejected("Only x402Version 2 is supported")
    resource, accepts = body.get("resource"), body.get("accepts")
    if not isinstance(resource, dict) or not isinstance(resource.get("url"), str):
        raise PaymentRejected("PAYMENT-REQUIRED has no resource.url")
    if not isinstance(accepts, list) or not accepts:
        raise PaymentRejected("PAYMENT-REQUIRED has no accepted payment requirements")
    error = body.get("error")
    return PaymentRequired(
        resource=resource,
        accepts=[item for item in accepts if isinstance(item, dict)],
        error=error if isinstance(error, str) else None,
    )


def optional_uint32(extra: dict[str, Any], key: str) -> int | None:
    value = extra.get(key)
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= MAX_UINT32:
        raise PaymentRejected(f"extra.{key} must be a 32-bit unsigned integer")
    return value


def check_requirement(
    raw: dict[str, Any], *, amount_drops: int, pay_to: str, network: str = TESTNET
) -> Requirement:
    """Validate one requirement against the caller's expectations, or raise PaymentRejected."""
    if network != TESTNET:
        raise PaymentRejected("Only XRPL Testnet (xrpl:1) is supported")
    if raw.get("scheme") != "exact":
        raise PaymentRejected("scheme must be exact")
    if raw.get("network") != network:
        raise PaymentRejected(f"network must be {network}, got {raw.get('network')!r}")
    if raw.get("asset") != "XRP":
        raise PaymentRejected("only XRP is supported")
    amount = raw.get("amount")
    if not isinstance(amount, str) or not DROPS.match(amount) or int(amount) > MAX_XRP_DROPS:
        raise PaymentRejected("amount must be a positive integer number of drops")
    if int(amount) != amount_drops:
        raise PaymentRejected(f"amount {amount} drops differs from the expected {amount_drops} drops")
    payee = raw.get("payTo")
    if not isinstance(payee, str) or not CLASSIC_ADDRESS.match(payee):
        raise PaymentRejected("payTo must be a classic XRPL address")
    if payee != pay_to:
        raise PaymentRejected(f"payTo {payee} differs from the expected {pay_to}")
    timeout = raw.get("maxTimeoutSeconds")
    if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise PaymentRejected(f"maxTimeoutSeconds must be between 1 and {MAX_TIMEOUT_SECONDS}")
    extra = raw.get("extra")
    if not isinstance(extra, dict):
        raise PaymentRejected("extra is required")
    invoice_id = extra.get("invoiceId")
    if not isinstance(invoice_id, str) or not 1 <= len(invoice_id) <= 128:
        raise PaymentRejected("extra.invoiceId is required")
    if extra.get("areFeesSponsored") is True:
        raise PaymentRejected("sponsored fees are not supported")
    return Requirement(
        raw=raw,
        amount_drops=amount_drops,
        pay_to=payee,
        network=network,
        max_timeout_seconds=timeout,
        invoice_id=invoice_id,
        source_tag=optional_uint32(extra, "sourceTag"),
        destination_tag=optional_uint32(extra, "destinationTag"),
    )


def select_requirement(
    required: PaymentRequired, *, amount_drops: int, pay_to: str, network: str = TESTNET
) -> Requirement:
    """The first accepted requirement that matches the expectations; otherwise PaymentRejected."""
    reasons = []
    for raw in required.accepts:
        try:
            return check_requirement(raw, amount_drops=amount_drops, pay_to=pay_to, network=network)
        except PaymentRejected as error:
            reasons.append(str(error))
    raise PaymentRejected("; ".join(reasons) or "no payment requirement offered")


def encode_payment_signature(required: PaymentRequired, requirement: Requirement, signed_tx_blob: str) -> str:
    """`PAYMENT-SIGNATURE` header: the accepted requirement unchanged plus the signed blob."""
    return encode_b64_json(
        {
            "x402Version": X402_VERSION,
            "resource": required.resource,
            "accepted": requirement.raw,
            "payload": {"signedTxBlob": signed_tx_blob, "invoiceId": requirement.invoice_id},
        }
    )


def decode_payment_response(header: str) -> dict[str, Any]:
    """Decode `PAYMENT-RESPONSE` (settlement result). Raises ValueError."""
    body = b64_json(header, "PAYMENT-RESPONSE")
    if not isinstance(body, dict) or not isinstance(body.get("success"), bool):
        raise ValueError("PAYMENT-RESPONSE is not a settlement response")
    return body


def explorer_url(tx_hash: str) -> str:
    return EXPLORER_TX_URL.format(tx_hash)
