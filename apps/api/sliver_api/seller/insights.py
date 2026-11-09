"""A seller's insights: unmet buyer demand and their own earnings with transaction links (#15, #17).

Earnings are the seller's delivered purchases. Buyers paid the seller directly on the XRP
Ledger, so every line links to its transaction on the Testnet explorer; Sliver never held the
funds. The page follows the public activity stream from `cursor` and reloads this view when one
of `resource_ids` is delivered.
"""

from sqlalchemy import Numeric, and_, case, cast, func, select
from sqlalchemy.orm import Session

from .. import valuation
from ..catalog.public import iso
from ..catalog.search import unmet_demand
from ..models import ActivityEvent, Payment, Resource, User
from ..payments.x402 import explorer_url
from .pricing import listing_text

DEMAND_DAYS = 30
DEMAND_LIMIT = 20
MAX_PURCHASES = 100
MAX_MATCHES = 3


def insights(db: Session, seller: User) -> dict:
    # Read before the purchases, so a delivery committed in between is seen twice, never missed.
    cursor = db.scalar(select(func.max(ActivityEvent.id))) or 0
    resources = db.scalars(
        select(Resource)
        .where(Resource.owner_id == seller.id, Resource.status != "rejected")
        .order_by(Resource.id)
    ).all()
    delivered = (Payment.status == "delivered", Resource.owner_id == seller.id)
    rows = db.execute(
        select(Payment, Resource.title)
        .join(Resource, Payment.resource_id == Resource.id)
        .where(*delivered)
        .order_by(Payment.settled_at.desc().nulls_last(), Payment.id)
        .limit(MAX_PURCHASES)
    ).all()
    # XRP amounts are drop strings; anything else (another asset, a malformed value) counts as 0.
    xrp_drops = case(
        (and_(Payment.asset == "XRP", Payment.amount.op("~")("^[0-9]+$")), cast(Payment.amount, Numeric)),
        else_=0,
    )
    count, usd_minor, drops = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(Payment.price_minor), 0),
            func.coalesce(func.sum(xrp_drops), 0),
        )
        .select_from(Payment)
        .join(Resource, Payment.resource_id == Resource.id)
        .where(*delivered)
    ).one()

    demand = []
    for item in unmet_demand(db, DEMAND_DAYS, DEMAND_LIMIT):
        matches = [
            {"id": resource.id, "title": resource.title, "status": resource.status}
            for resource in resources
            if valuation.matching_demand(listing_text(resource), [item])
        ]
        demand.append({**item, "matches": matches[:MAX_MATCHES]})

    return {
        "cursor": cursor,
        "resource_ids": [resource.id for resource in resources],
        "payout_address": seller.xrpl_address,
        "earnings": {
            "purchases": count,
            "usd_minor": int(usd_minor),
            "xrp_drops": str(int(drops)),
            "items": [
                {
                    "payment_id": payment.id,
                    "resource": {"id": payment.resource_id, "title": title},
                    "amount": {
                        "value": payment.amount,
                        "asset": payment.asset,
                        "usd_minor": payment.price_minor,
                    },
                    "network": payment.network,
                    "payer": payment.payer,
                    "settled_at": iso(payment.settled_at),
                    "transaction": {
                        "hash": payment.tx_hash,
                        "ledger_index": payment.ledger_index,
                        "explorer_url": explorer_url(payment.tx_hash),
                    },
                }
                for payment, title in rows
            ],
        },
        "demand": {"days": DEMAND_DAYS, "items": demand},
    }
