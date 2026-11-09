"""Sliver's platform fee (ADR 0005): recorded on each sale, settled with the seller off-chain.

The buyer still pays the full listed price straight to the seller with one standard x402
Payment; nothing here changes the 402 requirements, verification or the ledger re-check. When a
sale is delivered, the fee rate in force is snapshotted on the payment row with the fee and the
seller's net, so a later rate change never rewrites a past sale.

Integer math only. Rounding rule: the fee is rounded down to a whole drop and a whole cent
(`gross * bps // 10_000`), so rounding always favours the seller, and the net is the remainder,
so fee + net == gross exactly. Drops and USD cents are rounded independently.
"""

from dataclasses import dataclass

from ..models import Payment

BPS_DENOMINATOR = 10_000
DEFAULT_FEE_BPS = 1_000  # 10%
MAX_FEE_BPS = 5_000  # 50%


@dataclass(frozen=True)
class Split:
    gross: int
    fee: int
    net: int


def split(gross: int, bps: int) -> Split:
    """Sliver's fee and the seller's net for one amount (drops or USD minor units)."""
    if gross < 0:
        raise ValueError("gross must not be negative")
    if not 0 <= bps <= MAX_FEE_BPS:
        raise ValueError(f"fee must be between 0 and {MAX_FEE_BPS} basis points")
    fee = gross * bps // BPS_DENOMINATOR
    return Split(gross=gross, fee=fee, net=gross - fee)


def record_fee(payment: Payment, bps: int) -> None:
    """Snapshot the fee on a payment that is being delivered. A recorded fee is never replaced.

    Everything is computed before any attribute is set, so an error leaves the row untouched.
    """
    if payment.platform_fee_bps is not None:
        return
    usd = split(payment.price_minor, bps)
    # Drops are a digit string for XRP; any other asset keeps only the USD figures.
    amount = payment.amount
    in_drops = payment.asset == "XRP" and amount.isascii() and amount.isdigit()
    drops = split(int(amount), bps) if in_drops else None
    payment.platform_fee_bps = bps
    payment.platform_fee_minor, payment.seller_net_minor = usd.fee, usd.net
    if drops is not None:
        payment.platform_fee_drops, payment.seller_net_drops = drops.fee, drops.net
