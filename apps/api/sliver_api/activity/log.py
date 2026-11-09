"""Records purchase steps for the public activity feed and purchase timelines (issue #17).

Each event is written in its own short transaction, outside the purchase's session, so a step
shows up live while the purchase is still running and recording never changes payment
semantics. Recording is best effort: a failure is logged and the purchase carries on.
"""

import logging
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..models import ActivityEvent, Payment

logger = logging.getLogger(__name__)

EVENT_TYPES = (
    "payment_required",  # 402 issued with fresh payment requirements
    "signature_received",  # PAYMENT-SIGNATURE presented for this invoice
    "verified",  # facilitator verified the signed payment
    "rejected",  # the presented payment was refused (detail says why)
    "integrity_checked",  # stored object matches the listing's SHA-256
    "settlement_submitted",  # handed to the facilitator for submission
    "settled",  # facilitator reports the transaction applied
    "ledger_validated",  # Sliver's own ledger re-check passed
    "delivered",  # bytes released to the buyer (detail "replay" for a safe retry)
    "pending",  # outcome not known yet; the same payment may be retried
    "failed",  # a step failed (detail says why)
)

AGENT_NOTE_MAX = 200
# Serializes event writers so ids become visible in order; the stream cursor relies on it.
WRITE_LOCK_KEY = 0x5117E4  # arbitrary constant, unique to activity events


def sanitize_note(raw: str | None) -> str | None:
    """The agent's stated reason: printable text, single-spaced, at most 200 characters."""
    if not raw:
        return None
    try:  # HTTP headers arrive as latin-1; agents send UTF-8.
        raw = raw.encode("latin-1").decode("utf-8")
    except UnicodeError:
        pass
    # Drops control, format (including bidi overrides), private-use and unassigned characters.
    kept = "".join(
        " " if char.isspace() else char
        for char in raw
        if unicodedata.category(char)[0] != "C" or char.isspace()
    )
    note = " ".join(kept.split())[:AGENT_NOTE_MAX].strip()
    return note or None


def payment_facts(payment: Payment) -> dict:
    """What an event copies from its invoice row: public facts only."""
    return {
        "payment_id": payment.id,
        "resource_id": payment.resource_id,
        "amount": payment.amount,
        "asset": payment.asset,
        "price_minor": payment.price_minor,
        "network": payment.network,
        "pay_to": payment.pay_to,
        "payer": payment.payer,
        "tx_hash": payment.tx_hash,
    }


class ActivityLog:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    def record(self, event_type: str, payment: Payment | dict, **fields) -> None:
        """Append one step of `payment` (a row or its `payment_facts`); `fields` override them."""
        assert event_type in EVENT_TYPES, event_type
        facts = payment if isinstance(payment, dict) else payment_facts(payment)
        values = {**facts, **fields}
        if values.get("detail"):
            values["detail"] = values["detail"][:200]
        try:
            with self.sessions() as db:
                db.execute(select(func.pg_advisory_xact_lock(WRITE_LOCK_KEY)))
                db.add(ActivityEvent(type=event_type, **values))
                db.commit()
        except Exception:
            logger.warning(
                "could not record %s for payment %s", event_type, values["payment_id"], exc_info=True
            )
