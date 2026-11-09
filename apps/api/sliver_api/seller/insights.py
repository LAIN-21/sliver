"""A seller's insights: unmet buyer demand and their own earnings with transaction links (#15, #17).

Earnings are the seller's delivered purchases. Buyers paid the seller directly on the XRP
Ledger, so every line links to its transaction on the Testnet explorer; Sliver never held the
funds. The page follows the public activity stream from `cursor` and reloads this view when one
of `resource_ids` is delivered.

Each sale shows its gross (what the buyer paid the seller), Sliver's platform fee as recorded on
the sale (ADR 0005) and the seller's net. Fees are settled off-chain, so every recorded fee is
still owed to Sliver. Sales delivered before fees existed carry no fee: their net is the gross.
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


def amounts(usd_minor: int, drops: int | str | None) -> dict:
    return {"usd_minor": int(usd_minor), "xrp_drops": None if drops is None else str(int(drops))}


def gross_drops(payment: Payment) -> str | None:
    amount = payment.amount
    return amount if payment.asset == "XRP" and amount.isascii() and amount.isdigit() else None


def sale_split(payment: Payment) -> tuple[dict | None, dict]:
    """The recorded fee (None if no fee was recorded) and the seller's net for one sale."""
    if payment.platform_fee_bps is None:
        return None, amounts(payment.price_minor, gross_drops(payment))
    fee = {"bps": payment.platform_fee_bps, **amounts(payment.platform_fee_minor, payment.platform_fee_drops)}
    return fee, amounts(payment.seller_net_minor, payment.seller_net_drops)


def insights(db: Session, seller: User, platform_fee_bps: int) -> dict:
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
    no_fee = Payment.platform_fee_bps.is_(None)
    # A sale without a recorded fee (or without drop figures) nets its full gross.
    net_drops_each = case((Payment.seller_net_drops.is_(None), xrp_drops), else_=Payment.seller_net_drops)
    (count, usd_minor, drops, fee_minor, fee_drops, net_minor, net_drops, without_fee) = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(Payment.price_minor), 0),
            func.coalesce(func.sum(xrp_drops), 0),
            func.coalesce(func.sum(Payment.platform_fee_minor), 0),
            func.coalesce(func.sum(Payment.platform_fee_drops), 0),
            func.coalesce(func.sum(func.coalesce(Payment.seller_net_minor, Payment.price_minor)), 0),
            func.coalesce(func.sum(net_drops_each), 0),
            func.count().filter(no_fee),
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
        "platform_fee": {"bps": platform_fee_bps, "settlement": "off_chain"},
        "earnings": {
            "purchases": count,
            # Gross: what buyers paid the seller on-chain.
            "usd_minor": int(usd_minor),
            "xrp_drops": str(int(drops)),
            "platform_fee": amounts(fee_minor, fee_drops),
            "net": amounts(net_minor, net_drops),
            # Settled off-chain later; nothing is settled yet, so every recorded fee is owed.
            "fee_owed": amounts(fee_minor, fee_drops),
            "purchases_without_fee": without_fee,
            "items": [sale_item(payment, title) for payment, title in rows],
        },
        "demand": {"days": DEMAND_DAYS, "items": demand},
    }


def sale_item(payment: Payment, title: str) -> dict:
    fee, net = sale_split(payment)
    return {
        "payment_id": payment.id,
        "resource": {"id": payment.resource_id, "title": title},
        "amount": {"value": payment.amount, "asset": payment.asset, "usd_minor": payment.price_minor},
        "platform_fee": fee,
        "net": net,
        "network": payment.network,
        "payer": payment.payer,
        "settled_at": iso(payment.settled_at),
        "transaction": {
            "hash": payment.tx_hash,
            "ledger_index": payment.ledger_index,
            "explorer_url": explorer_url(payment.tx_hash),
        },
    }
