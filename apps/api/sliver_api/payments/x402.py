"""x402 v2 wire helpers for the XRPL `exact` scheme.

Requirements satisfy both the t54 facilitator (which requires `extra.sourceTag`) and the
official x402 XRPL spec (`extra.areFeesSponsored: false`, InvoiceID binding).
"""

import base64
import hashlib
import json
from typing import Any

from x402_xrpl.types import PaymentPayload, PaymentRequired, PaymentRequirements, ResourceInfo
from xrpl.models.transactions import Transaction

from ..config import Settings

X402_VERSION = 2
EXPLORER_TX_URL = "https://testnet.xrpl.org/transactions/{}"


def drops_for(price_minor: int, drops_per_usd: int) -> str:
    """USD cents to XRP drops at the configured demo rate, rounded up so sellers never get less."""
    return str(-(-price_minor * drops_per_usd // 100))


def build_requirements(
    settings: Settings, *, amount: str, pay_to: str, invoice_id: str
) -> PaymentRequirements:
    return PaymentRequirements(
        scheme="exact",
        network=settings.xrpl_network,
        amount=amount,
        asset="XRP",
        pay_to=pay_to,
        max_timeout_seconds=settings.payment_timeout_seconds,
        extra={
            "invoiceId": invoice_id,
            "sourceTag": settings.payment_source_tag,
            "areFeesSponsored": False,
        },
    )


def payment_required(
    *, url: str, description: str, requirements: PaymentRequirements, error: str | None = None
) -> dict[str, Any]:
    return PaymentRequired(
        x402_version=X402_VERSION,
        resource=ResourceInfo(url=url, description=description, mime_type="text/csv"),
        accepts=[requirements],
        error=error,
    ).to_dict()


def encode_header(body: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(body, separators=(",", ":"), sort_keys=True).encode()).decode()


def decode_payment_signature(header: str) -> PaymentPayload:
    """Parse PAYMENT-SIGNATURE. Raises ValueError on anything that is not a v2 XRPL payload."""
    try:
        envelope = json.loads(base64.b64decode(header, validate=True))
        payload = PaymentPayload.from_dict(envelope)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ValueError("PAYMENT-SIGNATURE is not a base64 JSON x402 payload") from error
    if payload.x402_version != X402_VERSION:
        raise ValueError("Only x402Version 2 is supported")
    blob = payload.payload.get("signedTxBlob")
    if not isinstance(blob, str) or not blob:
        raise ValueError("payload.signedTxBlob is required")
    return payload


def transaction_hash(signed_tx_blob: str) -> str:
    try:
        return Transaction.from_blob(signed_tx_blob).get_hash()
    except Exception as error:
        raise ValueError("signedTxBlob is not a valid signed XRPL transaction") from error


def invoice_id_field(invoice_id: str) -> str:
    """Payment.InvoiceID binding defined by the XRPL exact scheme: SHA-256(invoiceId)."""
    return hashlib.sha256(invoice_id.encode()).hexdigest().upper()


def explorer_url(tx_hash: str) -> str:
    return EXPLORER_TX_URL.format(tx_hash)
