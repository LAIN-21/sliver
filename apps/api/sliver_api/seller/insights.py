"""A seller's insights: unmet buyer demand, earnings and the balance Sliver owes them (#15, #17).

Buyers pay Sliver's platform wallet (ADR 0005). Each sale Sliver collected records its gross,
Sliver's platform fee and the seller's net; the nets not yet paid out are the seller's balance,
paid on the 15-day schedule in `payouts.py`. Sales paid straight to the seller before ADR 0005
carry no fee and are not owed: the seller already received them. Every line links to its
transaction on the Testnet explorer. The page follows the public activity stream from `cursor`
and reloads this view when one of `resource_ids` is delivered.
"""

from datetime import date

from sqlalchemy import Numeric, and_, case, cast, func, select
from sqlalchemy.orm import Session

from .. import valuation
from ..catalog.public import iso
from ..catalog.search import unmet_demand
from ..models import ActivityEvent, Payment, Resource, User
from ..payments.x402 import explorer_url
from .payouts import SCHEDULE, next_payout_date
from .pricing import listing_text

DEMAND_DAYS = 30
DEMAND_LIMIT = 20
MAX_PURCHASES = 100
MAX_MATCHES = 3
MAX_PAYOUTS = 50


def amounts(usd_minor: int, drops: int | str | None) -> dict:
    return {"usd_minor": int(usd_minor), "xrp_drops": None if drops is None else str(int(drops))}


def gross_drops(payment: Payment) -> str | None:
    amount = payment.amount
    return amount if payment.asset == "XRP" and amount.isascii() and amount.isdigit() else None


def sale_split(payment: Payment) -> tuple[dict | None, dict, dict]:
    """The fee Sliver kept (None if it did not collect the sale), the seller's net and its payout."""
    if payment.platform_fee_bps is None:
        return (
            None,
            amounts(payment.price_minor, gross_drops(payment)),
            {"status": "direct", "paid_out_at": None},
        )
    fee = {"bps": payment.platform_fee_bps, **amounts(payment.platform_fee_minor, payment.platform_fee_drops)}
    payout = {
        "status": "paid" if payment.seller_paid_out_at else "owed",
        "paid_out_at": iso(payment.seller_paid_out_at),
    }
    return fee, amounts(payment.seller_net_minor, payment.seller_net_drops), payout


def insights(db: Session, seller: User, platform_fee_bps: int, today: date) -> dict:
    # Read before the purchases, so a delivery committed in between is seen twice, never missed.
    cursor = db.scalar(select(func.max(ActivityEvent.id))) or 0
    resources = db.scalars(
        select(Resource)
        .where(Resource.owner_id == seller.id, Resource.status != "rejected")
        .order_by(Resource.id)
    ).all()
    delivered = (Payment.status == "delivered", Resource.owner_id == seller.id)
    rows = db.execute(
        select(Payment, Resource.title, Resource.parent_id)
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
    direct = Payment.platform_fee_bps.is_(None)
    owed = and_(Payment.platform_fee_bps.is_not(None), Payment.seller_paid_out_at.is_(None))
    # A sale paid straight to the seller (or without drop figures) nets its full gross.
    net_drops_each = case((Payment.seller_net_drops.is_(None), xrp_drops), else_=Payment.seller_net_drops)
    totals = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(Payment.price_minor), 0),
            func.coalesce(func.sum(xrp_drops), 0),
            func.coalesce(func.sum(Payment.platform_fee_minor), 0),
            func.coalesce(func.sum(Payment.platform_fee_drops), 0),
            func.coalesce(func.sum(func.coalesce(Payment.seller_net_minor, Payment.price_minor)), 0),
            func.coalesce(func.sum(net_drops_each), 0),
            func.count().filter(direct),
            func.count().filter(owed),
            func.coalesce(func.sum(Payment.seller_net_minor).filter(owed), 0),
            func.coalesce(func.sum(Payment.seller_net_drops).filter(owed), 0),
        )
        .select_from(Payment)
        .join(Resource, Payment.resource_id == Resource.id)
        .where(*delivered)
    ).one()
    (count, usd_minor, drops, fee_minor, fee_drops, net_minor, net_drops) = totals[:7]
    (direct_count, owed_count, owed_minor, owed_drops) = totals[7:]
    payouts = db.execute(
        select(
            Payment.seller_paid_out_at,
            func.count(),
            func.sum(Payment.seller_net_minor),
            func.coalesce(func.sum(Payment.seller_net_drops), 0),
        )
        .join(Resource, Payment.resource_id == Resource.id)
        .where(*delivered, Payment.seller_paid_out_at.is_not(None))
        .group_by(Payment.seller_paid_out_at)
        .order_by(Payment.seller_paid_out_at.desc())
        .limit(MAX_PAYOUTS)
    ).all()

    demand = []
    for item in unmet_demand(db, DEMAND_DAYS, DEMAND_LIMIT):
        matches = [
            {"id": resource.id, "title": resource.title, "status": resource.status}
            for resource in resources
            if resource.parent_id is None  # custom slices answer one buyer, not open demand
            and valuation.matching_demand(listing_text(resource), [item])
        ]
        demand.append({**item, "matches": matches[:MAX_MATCHES]})

    return {
        "cursor": cursor,
        "resource_ids": [resource.id for resource in resources],
        "payout_address": seller.xrpl_address,
        "platform_fee": {"bps": platform_fee_bps},
        "balance": {
            # The nets of sales Sliver collected and has not paid out yet.
            "owed": amounts(owed_minor, owed_drops),
            "sales_owed": owed_count,
            "next_payout_date": next_payout_date(today).isoformat(),
            "schedule": SCHEDULE,
            "payouts": [
                {"paid_out_at": iso(at), "sales": sales, **amounts(minor, paid_drops)}
                for at, sales, minor, paid_drops in payouts
            ],
        },
        "earnings": {
            "purchases": count,
            # Gross: what buyers paid for the seller's slivers.
            "usd_minor": int(usd_minor),
            "xrp_drops": str(int(drops)),
            "platform_fee": amounts(fee_minor, fee_drops),
            "net": amounts(net_minor, net_drops),
            # Paid straight to the seller before ADR 0005: no fee, nothing owed.
            "direct_purchases": direct_count,
            "items": [sale_item(payment, title, parent_id) for payment, title, parent_id in rows],
        },
        "demand": {"days": DEMAND_DAYS, "items": demand},
    }


def sale_item(payment: Payment, title: str, parent_id: str | None = None) -> dict:
    fee, net, payout = sale_split(payment)
    return {
        "payment_id": payment.id,
        # A buyer-defined custom slice (#39) names the listing it was cut from.
        "resource": {"id": payment.resource_id, "title": title, "custom_slice_of": parent_id},
        "amount": {"value": payment.amount, "asset": payment.asset, "usd_minor": payment.price_minor},
        "platform_fee": fee,
        "net": net,
        "payout": payout,
        "network": payment.network,
        "pay_to": payment.pay_to,
        "payer": payment.payer,
        "settled_at": iso(payment.settled_at),
        "transaction": {
            "hash": payment.tx_hash,
            "ledger_index": payment.ledger_index,
            "explorer_url": explorer_url(payment.tx_hash),
        },
    }
