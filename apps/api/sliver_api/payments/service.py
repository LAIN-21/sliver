"""Purchase flow for `GET /api/resources/{id}/data` (ADR 0004, destination per ADR 0005).

402 challenge -> PAYMENT-SIGNATURE -> facilitator verify -> stored-object integrity check ->
facilitator settle -> independent ledger re-check -> deliver. Sliver never signs and never holds
buyer keys. The buyer's presigned Payment goes to Sliver's platform wallet, and Sliver pays the
seller their net on the 15-day payout schedule.

Each step is also recorded as a public activity event (`activity/log.py`). Recording happens
outside the purchase's transaction and never changes what the purchase does.
"""

import hashlib
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from x402_xrpl.types import PaymentRequirements

from ..activity.log import ActivityLog, payment_facts
from ..config import Settings
from ..models import Payment, Resource, User, utcnow
from ..storage import ObjectStore
from .adapters import Facilitator, Ledger
from .fees import record_fee
from .ledger_check import settlement_problem
from .x402 import build_requirements, decode_payment_signature, drops_for, payment_required, transaction_hash

logger = logging.getLogger(__name__)

RIPPLE_EPOCH = 946_684_800  # 2000-01-01T00:00:00Z, the XRP Ledger's time origin


@dataclass
class Challenge:
    body: dict


@dataclass
class Delivery:
    data: bytes
    payment: Payment
    settlement: dict


class PurchaseError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class PurchaseService:
    def __init__(
        self,
        settings: Settings,
        store: ObjectStore,
        facilitator: Facilitator,
        ledger: Ledger,
        *,
        sleep: Callable[[float], None] = time.sleep,
        ledger_attempts: int = 10,
        activity: ActivityLog | None = None,
    ):
        self.settings, self.store, self.facilitator, self.ledger = settings, store, facilitator, ledger
        self.sleep, self.ledger_attempts, self.activity = sleep, ledger_attempts, activity

    def handle(
        self, db: Session, resource_id: str, header: str | None, url: str, agent_note: str | None = None
    ) -> Challenge | Delivery:
        """`agent_note` is the buyer agent's sanitized, public reason; it only labels the events."""
        resource = db.get(Resource, resource_id)
        if resource is None or resource.status != "published":
            raise PurchaseError(404, "not_found", "Resource not found.")
        seller = db.get(User, resource.owner_id)
        if seller is None or not seller.xrpl_address:
            # Sliver pays sellers their net every 15 days, so a seller needs a payout address to sell.
            raise PurchaseError(503, "seller_cannot_receive", "This seller has no XRPL address yet.")
        # ADR 0005: buyers pay Sliver's platform wallet, never the seller directly.
        pay_to = self.settings.sliver_platform_address
        if not pay_to:
            raise PurchaseError(503, "platform_cannot_receive", "Sliver has no platform XRPL address yet.")
        if not header:
            return self.challenge(db, resource, pay_to, url, agent_note=agent_note)
        return self.pay(db, resource, pay_to, header, url, agent_note)

    def record(self, event_type: str, payment: Payment | dict, **fields: Any) -> None:
        if self.activity is not None:
            self.activity.record(event_type, payment, **fields)

    def challenge(
        self,
        db: Session,
        resource: Resource,
        pay_to: str,
        url: str,
        error: str | None = None,
        agent_note: str | None = None,
    ):
        # Unpaid invoices are free to request; drop expired ones so they cannot pile up.
        db.execute(delete(Payment).where(Payment.status == "required", Payment.expires_at < utcnow()))
        invoice_id = uuid.uuid4().hex
        amount = drops_for(resource.price_minor, self.settings.drops_per_usd)
        requirements = build_requirements(self.settings, amount=amount, pay_to=pay_to, invoice_id=invoice_id)
        payment = Payment(
            invoice_id=invoice_id,
            resource_id=resource.id,
            pay_to=pay_to,
            amount=amount,
            asset="XRP",
            network=self.settings.xrpl_network,
            price_minor=resource.price_minor,
            requirements=requirements.to_dict(),
            expires_at=utcnow() + timedelta(seconds=self.settings.payment_timeout_seconds),
        )
        db.add(payment)
        db.commit()
        self.record("payment_required", payment, detail=error, agent_note=agent_note)
        description = f"{resource.title} ({resource.row_count} rows, CSV)"
        return Challenge(
            payment_required(url=url, description=description, requirements=requirements, error=error)
        )

    def pay(
        self, db: Session, resource: Resource, pay_to: str, header: str, url: str, agent_note: str | None
    ) -> Challenge | Delivery:
        try:
            payload = decode_payment_signature(header)
            tx_hash = transaction_hash(payload.payload["signedTxBlob"])
        except ValueError as error:
            raise PurchaseError(400, "invalid_payment", str(error)) from None

        invoice_id = payload.accepted.invoice_id()
        payment = (
            db.scalar(select(Payment).where(Payment.invoice_id == invoice_id).with_for_update())
            if invoice_id
            else None
        )
        if payment is None or payment.resource_id != resource.id:
            return self.challenge(db, resource, pay_to, url, error="unknown_invoice", agent_note=agent_note)
        # The hash of a presented transaction is shown only once it is settled on the ledger.
        self.record("signature_received", payment, tx_hash=None, agent_note=agent_note)
        if payload.accepted.to_dict() != payment.requirements:
            self.record("rejected", payment, tx_hash=None, detail="requirements_mismatch")
            return self.challenge(db, resource, pay_to, url, error="requirements_mismatch")
        requirements = PaymentRequirements.from_dict(payment.requirements)

        if payment.status in ("delivered", "settling"):
            if payment.tx_hash != tx_hash:
                self.record("rejected", payment, detail="invoice_already_paid")
                raise PurchaseError(
                    409, "invoice_already_paid", "This invoice was paid by another transaction."
                )
            # Safe retry: same invoice, same transaction. Never settles twice.
            return self.finish(db, resource, payment, tx_hash)
        if payment.status == "failed":
            self.record("rejected", payment, tx_hash=None, detail="invoice_failed")
            raise PurchaseError(409, "invoice_failed", payment.failure_reason or "This invoice failed.")
        if utcnow() > payment.expires_at:
            self.record("rejected", payment, detail="invoice_expired")
            return self.challenge(db, resource, pay_to, url, error="invoice_expired")

        verified = self.facilitator.verify(header, requirements)
        if not verified.is_valid:
            reason = f"payment_invalid:{verified.invalid_reason or 'unknown'}"
            self.record("rejected", payment, detail=reason)
            return self.challenge(db, resource, pay_to, url, error=reason)
        self.record("verified", payment, payer=verified.payer)

        # Only move money once the bytes we are about to sell are intact.
        self.read_verified(resource, payment)
        self.record("integrity_checked", payment, payer=verified.payer, detail=resource.sha256)

        facts = payment_facts(payment)  # the row is unreadable if the commit below fails
        payment.status, payment.tx_hash = "settling", tx_hash
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            self.record("rejected", facts, detail="transaction_already_used")
            raise PurchaseError(
                409, "transaction_already_used", "This transaction already paid another invoice."
            ) from None
        db.refresh(payment)
        self.record("settlement_submitted", payment, payer=verified.payer)

        try:
            settlement = self.facilitator.settle(header, requirements)
        except Exception:
            logger.exception("settlement outcome unknown for invoice %s", payment.invoice_id)
            self.record("pending", payment, payer=verified.payer, detail="settlement_status_unknown")
            raise PurchaseError(
                409, "settlement_status_unknown", "Settlement outcome is unknown; retry the same payment."
            ) from None
        if not settlement.success:
            reason = f"settle_failed:{settlement.error_reason or 'unknown'}"
            if settlement.transaction:  # submitted but failed: never reuse this transaction
                self.fail(db, payment, f"settle_failed:{settlement.error_reason}")
                self.record("failed", payment, payer=verified.payer, detail=reason)
                raise PurchaseError(402, "settle_failed", settlement.error_reason or "Settlement failed.")
            payment.status, payment.tx_hash = "required", None
            db.commit()
            self.record("failed", payment, payer=verified.payer, detail=reason)
            return self.challenge(db, resource, pay_to, url, error=reason)
        if settlement.transaction and settlement.transaction.upper() != tx_hash.upper():
            self.fail(db, payment, "facilitator_reported_another_transaction")
            self.record(
                "failed", payment, payer=verified.payer, detail="facilitator_reported_another_transaction"
            )
            raise PurchaseError(
                502, "settlement_mismatch", "The facilitator reported a different transaction."
            )
        payment.payer = settlement.payer
        self.record("settled", payment)
        return self.finish(db, resource, payment, tx_hash)

    def finish(self, db: Session, resource: Resource, payment: Payment, tx_hash: str) -> Delivery:
        replay = payment.status == "delivered"
        if not replay:
            result, problem = None, "transaction_not_found"
            for attempt in range(self.ledger_attempts):
                try:
                    result = self.ledger.transaction(tx_hash)
                except Exception:
                    logger.warning("ledger lookup failed for %s; will retry", tx_hash, exc_info=True)
                    result = None
                problem = settlement_problem(
                    result, pay_to=payment.pay_to, amount_drops=payment.amount, invoice_id=payment.invoice_id
                )
                if problem not in ("transaction_not_found", "not_validated"):
                    break
                if attempt + 1 < self.ledger_attempts:
                    self.sleep(1.0)
            if problem in ("transaction_not_found", "not_validated"):
                db.commit()
                self.record("pending", payment, detail=problem)
                raise PurchaseError(409, "settlement_pending", "Not validated yet; retry the same payment.")
            if problem:
                self.fail(db, payment, f"ledger_check:{problem}")
                self.record("failed", payment, detail=f"ledger_check:{problem}")
                raise PurchaseError(
                    502, "ledger_check_failed", f"The ledger does not confirm this payment: {problem}"
                )
            tx = result.get("tx_json") or result
            payment.status, payment.settled_at = "delivered", utcnow()
            payment.payer = payment.payer or tx.get("Account")
            payment.ledger_index = result.get("ledger_index")
            self.record_platform_fee(payment)
            db.commit()
            self.record(
                "ledger_validated",
                payment,
                ledger_index=payment.ledger_index,
                ledger_closed_at=ledger_close_time(result),
            )
        data = self.read_verified(resource, payment)
        settlement = {
            "success": True,
            "transaction": tx_hash,
            "network": payment.network,
            "payer": payment.payer,
        }
        self.record(
            "delivered", payment, ledger_index=payment.ledger_index, detail="replay" if replay else None
        )
        return Delivery(data=data, payment=payment, settlement=settlement)

    def record_platform_fee(self, payment: Payment) -> None:
        """Snapshot Sliver's fee on the sale (ADR 0005). Bookkeeping only: it never blocks delivery."""
        try:
            record_fee(payment, self.settings.sliver_platform_fee_bps, self.settings.sliver_platform_address)
        except Exception:
            logger.exception("could not record the platform fee for payment %s", payment.id)

    def read_verified(self, resource: Resource, payment: Payment) -> bytes:
        try:
            data = self.store.get(resource.object_key)
        except Exception:
            logger.exception("could not read %s", resource.object_key)
            self.record("failed", payment, detail="storage_unavailable")
            raise PurchaseError(503, "storage_unavailable", "The data is temporarily unavailable.") from None
        if hashlib.sha256(data).hexdigest() != resource.sha256:
            logger.error("integrity check failed for resource %s", resource.id)
            self.record("failed", payment, detail="integrity_check_failed")
            raise PurchaseError(503, "integrity_check_failed", "The stored data failed its integrity check.")
        return data

    def fail(self, db: Session, payment: Payment, reason: str) -> None:
        payment.status, payment.failure_reason = "failed", reason
        db.commit()


def ledger_close_time(result: dict[str, Any]) -> datetime | None:
    """When the validating ledger closed, from a `tx` result (API v2 or v1), if reported."""
    stamp = result.get("close_time_iso")
    if isinstance(stamp, str):
        try:
            return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            pass
    tx = result.get("tx_json") or result
    seconds = tx.get("date", result.get("date"))
    if type(seconds) is int:
        try:
            return datetime.fromtimestamp(RIPPLE_EPOCH + seconds, UTC)
        except (OverflowError, OSError, ValueError):  # only labels an event; never fail delivery
            return None
    return None
