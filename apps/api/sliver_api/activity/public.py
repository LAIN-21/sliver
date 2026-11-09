"""The only serializer allowed to describe purchase activity to the public.

An explicit allow-list like `catalog/public.py`: invoice ids, payment requirements, headers,
signed blobs and failure internals never leave the server. Titles appear only while the
Resource is published.
"""

from ..catalog.public import iso
from ..models import ActivityEvent, Payment
from ..payments.x402 import explorer_url

UNLISTED = "Unlisted resource"


def public_event(event: ActivityEvent, title: str | None, resource_status: str | None) -> dict:
    return {
        "id": event.id,
        "type": event.type,
        "at": iso(event.created_at),
        "payment_id": event.payment_id,
        "resource": {
            "id": event.resource_id,
            "title": title if resource_status == "published" else UNLISTED,
        },
        "amount": {"value": event.amount, "asset": event.asset, "usd_minor": event.price_minor},
        "network": event.network,
        "pay_to": event.pay_to,
        "payer": event.payer,
        "transaction": (
            {
                "hash": event.tx_hash,
                "ledger_index": event.ledger_index,
                "ledger_closed_at": iso(event.ledger_closed_at),
                "explorer_url": explorer_url(event.tx_hash),
            }
            if event.tx_hash
            else None
        ),
        "detail": event.detail,
        "agent_note": event.agent_note,
    }


def public_fee(payment: Payment | None) -> dict | None:
    """How a delivered sale Sliver collected splits (ADR 0005), or None for any other purchase.

    Explicit allow-list: the rate, Sliver's fee and the seller's net, all derived from the public
    price. The buyer paid the full price to Sliver's platform wallet; Sliver pays the seller's net
    on its 15-day payout schedule. Payout status is the seller's business and is not shown.
    """
    if payment is None or payment.status != "delivered" or payment.platform_fee_bps is None:
        return None
    drops = payment.platform_fee_drops is not None
    return {
        "bps": payment.platform_fee_bps,
        "fee": {
            "usd_minor": payment.platform_fee_minor,
            "xrp_drops": str(payment.platform_fee_drops) if drops else None,
        },
        "seller_net": {
            "usd_minor": payment.seller_net_minor,
            "xrp_drops": str(payment.seller_net_drops) if drops else None,
        },
    }
