"""The only serializer allowed to describe purchase activity to the public.

An explicit allow-list like `catalog/public.py`: invoice ids, payment requirements, headers,
signed blobs and failure internals never leave the server. Titles appear only while the
Resource is published.
"""

from ..catalog.public import iso
from ..models import ActivityEvent
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
