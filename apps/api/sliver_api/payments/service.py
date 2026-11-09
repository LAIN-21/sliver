"""Purchase flow for `GET /api/resources/{id}/data` (ADR 0004).

402 challenge -> PAYMENT-SIGNATURE -> facilitator verify -> stored-object integrity check ->
facilitator settle -> independent ledger re-check -> deliver. Sliver never signs, never holds
buyer keys and never custodies funds: the buyer's presigned Payment goes to the seller.
"""

import hashlib
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from x402_xrpl.types import PaymentRequirements

from ..config import Settings
from ..models import Payment, Resource, User, utcnow
from ..storage import ObjectStore
from .adapters import Facilitator, Ledger
from .ledger_check import settlement_problem
from .x402 import build_requirements, decode_payment_signature, drops_for, payment_required, transaction_hash

logger = logging.getLogger(__name__)


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
    ):
        self.settings, self.store, self.facilitator, self.ledger = settings, store, facilitator, ledger
        self.sleep, self.ledger_attempts = sleep, ledger_attempts

    def handle(self, db: Session, resource_id: str, header: str | None, url: str) -> Challenge | Delivery:
        resource = db.get(Resource, resource_id)
        if resource is None or resource.status != "published":
            raise PurchaseError(404, "not_found", "Resource not found.")
        seller = db.get(User, resource.owner_id)
        if seller is None or not seller.xrpl_address:
            raise PurchaseError(503, "seller_cannot_receive", "This seller has no XRPL address yet.")
        if not header:
            return self.challenge(db, resource, seller.xrpl_address, url)
        return self.pay(db, resource, seller.xrpl_address, header, url)

    def challenge(self, db: Session, resource: Resource, pay_to: str, url: str, error: str | None = None):
        invoice_id = uuid.uuid4().hex
        amount = drops_for(resource.price_minor, self.settings.drops_per_usd)
        requirements = build_requirements(self.settings, amount=amount, pay_to=pay_to, invoice_id=invoice_id)
        db.add(
            Payment(
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
        )
        db.commit()
        description = f"{resource.title} ({resource.row_count} rows, CSV)"
        return Challenge(
            payment_required(url=url, description=description, requirements=requirements, error=error)
        )

    def pay(
        self, db: Session, resource: Resource, pay_to: str, header: str, url: str
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
            return self.challenge(db, resource, pay_to, url, error="unknown_invoice")
        if payload.accepted.to_dict() != payment.requirements:
            return self.challenge(db, resource, pay_to, url, error="requirements_mismatch")
        requirements = PaymentRequirements.from_dict(payment.requirements)

        if payment.status in ("delivered", "settling"):
            if payment.tx_hash != tx_hash:
                raise PurchaseError(
                    409, "invoice_already_paid", "This invoice was paid by another transaction."
                )
            # Safe retry: same invoice, same transaction. Never settles twice.
            return self.finish(db, resource, payment, tx_hash)
        if payment.status == "failed":
            raise PurchaseError(409, "invoice_failed", payment.failure_reason or "This invoice failed.")
        if utcnow() > payment.expires_at:
            return self.challenge(db, resource, pay_to, url, error="invoice_expired")

        verified = self.facilitator.verify(header, requirements)
        if not verified.is_valid:
            return self.challenge(
                db, resource, pay_to, url, error=f"payment_invalid:{verified.invalid_reason or 'unknown'}"
            )

        # Only move money once the bytes we are about to sell are intact.
        self.read_verified(resource)

        payment.status, payment.tx_hash = "settling", tx_hash
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise PurchaseError(
                409, "transaction_already_used", "This transaction already paid another invoice."
            ) from None
        db.refresh(payment)

        try:
            settlement = self.facilitator.settle(header, requirements)
        except Exception:
            logger.exception("settlement outcome unknown for invoice %s", payment.invoice_id)
            raise PurchaseError(
                409, "settlement_status_unknown", "Settlement outcome is unknown; retry the same payment."
            ) from None
        if not settlement.success:
            if settlement.transaction:  # submitted but failed: never reuse this transaction
                self.fail(db, payment, f"settle_failed:{settlement.error_reason}")
                raise PurchaseError(402, "settle_failed", settlement.error_reason or "Settlement failed.")
            payment.status, payment.tx_hash = "required", None
            db.commit()
            return self.challenge(
                db, resource, pay_to, url, error=f"settle_failed:{settlement.error_reason or 'unknown'}"
            )
        if settlement.transaction and settlement.transaction.upper() != tx_hash.upper():
            self.fail(db, payment, "facilitator_reported_another_transaction")
            raise PurchaseError(
                502, "settlement_mismatch", "The facilitator reported a different transaction."
            )
        payment.payer = settlement.payer
        return self.finish(db, resource, payment, tx_hash)

    def finish(self, db: Session, resource: Resource, payment: Payment, tx_hash: str) -> Delivery:
        if payment.status != "delivered":
            result, problem = None, "transaction_not_found"
            for attempt in range(self.ledger_attempts):
                result = self.ledger.transaction(tx_hash)
                problem = settlement_problem(
                    result, pay_to=payment.pay_to, amount_drops=payment.amount, invoice_id=payment.invoice_id
                )
                if problem not in ("transaction_not_found", "not_validated"):
                    break
                if attempt + 1 < self.ledger_attempts:
                    self.sleep(1.0)
            if problem in ("transaction_not_found", "not_validated"):
                db.commit()
                raise PurchaseError(409, "settlement_pending", "Not validated yet; retry the same payment.")
            if problem:
                self.fail(db, payment, f"ledger_check:{problem}")
                raise PurchaseError(
                    502, "ledger_check_failed", f"The ledger does not confirm this payment: {problem}"
                )
            tx = result.get("tx_json") or result
            payment.status, payment.settled_at = "delivered", utcnow()
            payment.payer = payment.payer or tx.get("Account")
            payment.ledger_index = result.get("ledger_index")
            db.commit()
        data = self.read_verified(resource)
        settlement = {
            "success": True,
            "transaction": tx_hash,
            "network": payment.network,
            "payer": payment.payer,
        }
        return Delivery(data=data, payment=payment, settlement=settlement)

    def read_verified(self, resource: Resource) -> bytes:
        try:
            data = self.store.get(resource.object_key)
        except Exception:
            logger.exception("could not read %s", resource.object_key)
            raise PurchaseError(503, "storage_unavailable", "The data is temporarily unavailable.") from None
        if hashlib.sha256(data).hexdigest() != resource.sha256:
            logger.error("integrity check failed for resource %s", resource.id)
            raise PurchaseError(503, "integrity_check_failed", "The stored data failed its integrity check.")
        return data

    def fail(self, db: Session, payment: Payment, reason: str) -> None:
        payment.status, payment.failure_reason = "failed", reason
        db.commit()
