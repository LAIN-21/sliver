"""The buyer's purchase policy and flow. Runs on the buyer's machine with the buyer's key.

A purchase is refused, before anything is signed, when: no budget is given; the price exceeds
the budget, the per-purchase cap or the remaining daily cap; another purchase is in flight;
the 402 challenge asks for a different amount than the listing's price, a different payee
than the seller's pinned address, or anything but XRPL Testnet. Delivered bytes must match the
listing's SHA-256 before they are saved as the purchased file.
"""

import hashlib
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import httpx
from xrpl.clients import JsonRpcClient
from xrpl.models.transactions import Payment
from xrpl.wallet import Wallet

from sliver_x402 import (
    TESTNET,
    PaymentRejected,
    Requirement,
    decode_payment_response,
    encode_payment_signature,
    explorer_url,
    parse_payment_required,
    select_requirement,
    sign_payment,
)

from .api import ApiError, SliverApi
from .config import Config, drops_for, usd_to_minor
from .store import PurchaseInFlight, Store, iso, now

RESOURCE_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
RETRYABLE = frozenset({"settlement_pending", "settlement_status_unknown"})


class Refused(Exception):
    """A purchase that did not complete. `paid` is set when a signed payment already left this
    machine, so the caller is never told that nothing was spent."""

    def __init__(self, code: str, message: str, *, paid: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.paid = code, message, paid


class Signer(Protocol):
    address: str

    def sign(self, requirement: Requirement) -> Payment: ...


class XrplSigner:
    """Autofills from XRPL Testnet and signs locally. The seed stays in this process."""

    def __init__(self, wallet: Wallet, rpc_url: str, max_fee_drops: int):
        self.wallet, self.address = wallet, wallet.address
        self.client, self.max_fee_drops = JsonRpcClient(rpc_url), max_fee_drops

    def sign(self, requirement: Requirement) -> Payment:
        return sign_payment(requirement, self.wallet, self.client, max_fee_drops=self.max_fee_drops)


def check_resource_id(resource_id: str) -> str:
    if not RESOURCE_ID.match(resource_id or ""):
        raise Refused("invalid_resource_id", "resource_id must be a Sliver Resource id.")
    return resource_id


def error_code(response: httpx.Response) -> tuple[str, str]:
    try:
        body = response.json()
    except ValueError:
        return "http_error", response.text[:300]
    error = (body.get("error") or {}) if isinstance(body, dict) else {}
    if isinstance(error, dict):
        return str(error.get("code", "http_error")), str(error.get("message", ""))
    return str(error), ""


class Buyer:
    def __init__(
        self,
        config: Config,
        api: SliverApi,
        store: Store,
        signer_factory: Callable[[], Signer],
        *,
        sleep: Callable[[float], None] = time.sleep,
        settle_attempts: int = 5,
    ):
        self.config, self.api, self.store = config, api, store
        self.signer_factory, self.sleep, self.settle_attempts = signer_factory, sleep, settle_attempts

    def payee_key(self, listing: dict[str, Any]) -> str:
        return f"{self.config.api_url}|{(listing.get('seller') or {}).get('name', '')}"

    def check_policy(self, price_minor: int, budget_usd: float | None) -> int:
        if budget_usd is None:
            raise Refused("no_budget", "No budget given. Ask your human how much you may spend, then retry.")
        budget_minor = usd_to_minor(budget_usd, "budget_usd")
        if budget_minor <= 0:
            raise Refused("no_budget", "The budget must be more than $0. Ask your human for a budget.")
        if price_minor > budget_minor:
            raise Refused(
                "over_budget",
                f"Price ${price_minor / 100:.2f} exceeds the ${budget_minor / 100:.2f} budget. "
                "Ask your human before spending more.",
            )
        if price_minor > self.config.max_purchase_minor:
            raise Refused(
                "over_purchase_cap",
                f"Price ${price_minor / 100:.2f} exceeds the per-purchase cap of "
                f"${self.config.max_purchase_minor / 100:.2f} (SLIVER_MAX_PURCHASE_USD).",
            )
        spent = self.store.spent_minor()
        if spent + price_minor > self.config.daily_cap_minor:
            raise Refused(
                "over_daily_cap",
                f"Buying would bring the last 24 hours to ${(spent + price_minor) / 100:.2f}, over the "
                f"${self.config.daily_cap_minor / 100:.2f} daily cap (SLIVER_DAILY_CAP_USD).",
            )
        return budget_minor

    def buy(
        self, resource_id: str, budget_usd: float | None, output_dir: str | None = None
    ) -> dict[str, Any]:
        check_resource_id(resource_id)
        if budget_usd is None:  # refuse before touching the network
            self.check_policy(0, None)
        try:
            listing = self.api.listing(resource_id)
        except ApiError as error:
            raise Refused("listing_unavailable", str(error)) from None
        if listing.get("id") != resource_id:
            raise Refused("bad_listing", "The API returned a listing for a different resource id.")
        price_minor = (listing.get("price") or {}).get("amount_minor")
        if (
            type(price_minor) is not int
            or price_minor <= 0
            or (listing.get("price") or {}).get("currency") != "USD"
        ):
            raise Refused("bad_listing", "The listing has no valid USD price.")
        self.check_policy(price_minor, budget_usd)
        try:
            with self.store.one_purchase():
                self.check_policy(price_minor, budget_usd)  # re-check under the lock
                return self.pay(listing, price_minor, Path(output_dir or self.config.output_dir).expanduser())
        except PurchaseInFlight as error:
            raise Refused("purchase_in_flight", str(error)) from None

    def pay(self, listing: dict[str, Any], price_minor: int, output_dir: Path) -> dict[str, Any]:
        resource_id = listing["id"]
        signer = self.signer_factory()
        try:
            unpaid = self.api.fetch_data(resource_id)
        except httpx.HTTPError as error:
            raise Refused("api_unreachable", str(error)) from None
        if unpaid.status_code != 402:
            code, message = error_code(unpaid)
            raise Refused(code, f"Expected an x402 challenge, got HTTP {unpaid.status_code}: {message}")
        try:
            required = parse_payment_required(unpaid.headers.get("PAYMENT-REQUIRED") or unpaid.json())
            offered = next(
                (raw.get("payTo") for raw in required.accepts if raw.get("network") == TESTNET), None
            )
            pinned = self.store.payee(self.payee_key(listing))
            pay_to = pinned or offered
            if not isinstance(pay_to, str) or pay_to == signer.address:
                raise PaymentRejected("the challenge has no usable XRPL Testnet payee")
            amount_drops = drops_for(price_minor, self.config.drops_per_usd)
            requirement = select_requirement(required, amount_drops=amount_drops, pay_to=pay_to)
            signed = signer.sign(requirement)
        except (PaymentRejected, ValueError) as error:
            raise Refused("challenge_rejected", f"Refused to sign: {error}") from None

        tx_hash = signed.get_hash()
        header = encode_payment_signature(required, requirement, signed.blob())
        record = {
            "id": uuid.uuid4().hex,
            "created_at": iso(now()),
            "status": "pending",
            "resource_id": resource_id,
            "title": listing.get("title"),
            "seller": (listing.get("seller") or {}).get("name"),
            "price_minor": price_minor,
            "amount_drops": str(amount_drops),
            "network": TESTNET,
            "pay_to": pay_to,
            "payer": signer.address,
            "invoice_id": requirement.invoice_id,
            "tx_hash": tx_hash,
            "explorer_url": explorer_url(tx_hash),
        }
        # Recorded before the payment leaves this machine, so it counts toward the daily cap.
        self.store.save_purchase(record)
        if not pinned:
            self.store.pin_payee(self.payee_key(listing), pay_to)

        paid = {
            "spent_usd": price_minor / 100,
            "tx_hash": tx_hash,
            "explorer_url": explorer_url(tx_hash),
            "purchase_id": record["id"],
        }
        response = self.send(resource_id, header)
        if response is None or response.status_code != 200:
            code, message = (
                ("timeout", "No response from Sliver") if response is None else error_code(response)
            )
            record.update(status="failed", error=f"{code}: {message}"[:500])
            self.store.save_purchase(record)
            raise Refused(
                "payment_not_delivered",
                f"Payment {tx_hash} was sent but the data was not delivered ({code}: {message}). "
                f"Check {explorer_url(tx_hash)} before retrying; it counts toward the daily cap.",
                paid=paid,
            )

        settlement: dict[str, Any] = {}
        try:
            settlement = decode_payment_response(response.headers.get("PAYMENT-RESPONSE", ""))
        except ValueError:
            pass
        digest = hashlib.sha256(response.content).hexdigest()
        verified = digest == (listing.get("content") or {}).get("sha256")
        receipt_id = response.headers.get("X-Sliver-Receipt")
        record.update(
            sha256=digest,
            sha256_verified=verified,
            settled_transaction=settlement.get("transaction"),
            receipt_id=receipt_id,
        )
        try:
            path = self.save(output_dir, resource_id, response.content, verified)
        except OSError as error:
            record.update(status="delivered_unsaved", error=f"save failed: {error}"[:500])
            self.store.save_purchase(record)
            raise Refused(
                "save_failed",
                f"Payment {tx_hash} was delivered but the file could not be saved to {output_dir} "
                f"({error}). It counts toward the daily cap; tell your human before buying again.",
                paid=paid,
            ) from None
        record.update(status="delivered" if verified else "delivered_unverified", file=str(path))
        self.store.save_purchase(record)
        receipt = self.api.receipt(receipt_id) if receipt_id else None  # best effort, after the record
        result = {
            "status": record["status"],
            "resource_id": resource_id,
            "title": listing.get("title"),
            "price_usd": price_minor / 100,
            "amount_xrp": amount_drops / 1_000_000,
            "network": TESTNET,
            "pay_to": pay_to,
            "tx_hash": tx_hash,
            "explorer_url": explorer_url(tx_hash),
            "file": str(path),
            "bytes": len(response.content),
            "sha256": digest,
            "sha256_verified": verified,
            "receipt": receipt,
            "spent_last_24h_usd": self.store.spent_minor() / 100,
        }
        if not verified:
            result["warning"] = (
                "The delivered bytes do not match the listing's SHA-256. They were saved with an "
                ".unverified suffix; do not use them without telling your human."
            )
        if settlement.get("transaction") and str(settlement["transaction"]).upper() != tx_hash.upper():
            result["warning"] = "Sliver reported a different settlement transaction than the one signed here."
        return result

    def send(self, resource_id: str, header: str) -> httpx.Response | None:
        """Send the payment; retry the same payment while Sliver says settlement is pending."""
        response = None
        for attempt in range(self.settle_attempts):
            try:
                response = self.api.fetch_data(resource_id, header)
            except httpx.HTTPError:
                response = None
            else:
                if response.status_code != 409 or error_code(response)[0] not in RETRYABLE:
                    return response
            if attempt + 1 < self.settle_attempts:
                self.sleep(3.0)
        return response

    def save(self, output_dir: Path, resource_id: str, data: bytes, verified: bool) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        name = f"sliver-{resource_id}.csv" + ("" if verified else ".unverified")
        path = output_dir / name
        counter = 1
        while path.exists() and path.read_bytes() != data:
            path = output_dir / f"sliver-{resource_id}-{counter}.csv{'' if verified else '.unverified'}"
            counter += 1
        path.write_bytes(data)
        return path
