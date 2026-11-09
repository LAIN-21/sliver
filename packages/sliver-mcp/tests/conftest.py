"""A stub Sliver API (catalog + x402 gate) and a stub facilitator, served through httpx.MockTransport.

The stub mirrors `apps/api/sliver_api/payments`: the 402 challenge, the requirements echoed back
unchanged, and a facilitator check of the signed blob with the t54 / official-spec rules.
"""

import base64
import copy
import hashlib
import json
import uuid
from pathlib import Path

import httpx
import pytest
from xrpl.models.transactions import Transaction
from xrpl.wallet import Wallet

from sliver_mcp.api import SliverApi
from sliver_mcp.buyer import Buyer
from sliver_mcp.config import Config, drops_for
from sliver_mcp.store import Store
from sliver_x402 import Requirement, invoice_id_field, sign_offline

PLATFORM = Wallet.create()  # Sliver's platform wallet: every 402 asks to pay it (ADR 0005)
BUYER = Wallet.create()
CSV = b"week_start,lane,container_type,usd_per_container\n2026-10-26,SGSIN-CNSHA,40HC,1650\n"
VALIDATED_LEDGER = 1000

LISTINGS = [
    {
        "id": "11111111-1111-4111-8111-111111111111",
        "title": "Container spot freight rates from Singapore: SGSIN-CNSHA",
        "description": "Weekly container spot rates (USD) from Singapore. This sliver covers SGSIN-CNSHA.",
        "category": "freight-rates",
        "tags": ["freight", "spot rate", "container", "lane", "pricing", "20GP", "40HC"],
        "columns": [
            {"name": "week_start", "type": "date"},
            {"name": "lane", "type": "text"},
            {"name": "container_type", "type": "text"},
            {"name": "usd_per_container", "type": "integer"},
        ],
        "row_count": 34,
        "coverage": {
            "time": {"column": "week_start", "start": "2026-07-06", "end": "2026-10-26"},
            "slice": {"column": "lane", "value": "SGSIN-CNSHA"},
        },
        "price": {"amount_minor": 150, "currency": "USD"},
        "seller": {"name": "Harbour Analytics (demo seller)"},
        "provenance": {"source": "Synthetic", "collected_at": "2026-11-01"},
        "content": {"sha256": hashlib.sha256(CSV).hexdigest(), "size_bytes": len(CSV), "format": "text/csv"},
        "published_at": "2026-11-09T07:09:00Z",
    },
    {
        "id": "22222222-2222-4222-8222-222222222222",
        "title": "Singapore customs clearance times by HS chapter: air",
        "description": "Monthly median customs clearance hours by HS chapter. This sliver covers air only.",
        "category": "customs",
        "tags": ["customs", "clearance", "hs code", "imports"],
        "columns": [
            {"name": "month", "type": "month"},
            {"name": "hs_chapter", "type": "integer"},
            {"name": "transport_mode", "type": "text"},
            {"name": "median_clearance_hours", "type": "decimal"},
        ],
        "row_count": 100,
        "coverage": {
            "time": {"column": "month", "start": "2026-01", "end": "2026-10"},
            "slice": {"column": "transport_mode", "value": "air"},
        },
        "price": {"amount_minor": 300, "currency": "USD"},
        "seller": {"name": "Harbour Analytics (demo seller)"},
        "provenance": {"collected_at": "2026-11-01"},
        "content": {"sha256": "0" * 64, "size_bytes": 1, "format": "text/csv"},
        "published_at": "2026-11-09T07:09:00Z",
    },
    {
        "id": "33333333-3333-4333-8333-333333333333",
        "title": "Singapore berth waiting times",
        "description": "Daily berth waiting hours by terminal and vessel class at the port of Singapore.",
        "category": "port-operations",
        "tags": ["singapore", "port", "berth", "congestion"],
        "columns": [{"name": "date", "type": "date"}, {"name": "avg_berth_wait_hours", "type": "decimal"}],
        "row_count": 500,
        "coverage": {"time": {"column": "date", "start": "2026-08-01", "end": "2026-10-31"}},
        "price": {"amount_minor": 1200, "currency": "USD"},
        "seller": {"name": "Harbour Analytics (demo seller)"},
        "provenance": {"collected_at": "2026-11-01"},
        "content": {"sha256": "1" * 64, "size_bytes": 1, "format": "text/csv"},
        "published_at": "2026-11-09T07:09:00Z",
    },
]


def b64(body: dict) -> str:
    return base64.b64encode(json.dumps(body).encode()).decode()


class StubSliver:
    """Catalog, x402 gate, facilitator and receipts. Knobs simulate a dishonest or flaky server."""

    def __init__(self):
        self.listings = {listing["id"]: copy.deepcopy(listing) for listing in LISTINGS}
        self.pay_to = PLATFORM.address
        self.network = "xrpl:1"
        self.drops_per_usd = 400_000
        self.data = {LISTINGS[0]["id"]: CSV}
        self.pending_responses = 0
        self.invoices: dict[str, dict] = {}
        self.payments: list[dict] = []  # signed transactions the facilitator saw
        self.receipts: dict[str, dict] = {}
        self.overrides: dict[str, httpx.Response] = {}  # path prefix -> canned (malformed) response
        self.paid_response: httpx.Response | None = None  # canned answer to a paid request
        self.data_requests: list[httpx.Request] = []  # every request to the x402 data endpoint

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for prefix, response in self.overrides.items():
            if path.startswith(prefix):
                return response
        if path == "/api/catalog":
            q = set(request.url.params.get("q", "").lower().split())
            items = [
                item
                for item in self.listings.values()
                if not q or q & set(json.dumps(item).lower().replace(":", " ").split())
            ]
            return httpx.Response(200, json={"items": items, "total": len(items)})
        if path.startswith("/api/catalog/"):
            found = self.listings.get(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=found) if found else httpx.Response(404, json={"detail": "nf"})
        if path.startswith("/api/receipts/"):
            found = self.receipts.get(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=found) if found else httpx.Response(404, json={"detail": "nf"})
        if path.startswith("/api/resources/") and path.endswith("/data"):
            return self.data_endpoint(request, path.split("/")[3])
        return httpx.Response(404)

    def challenge(self, request: httpx.Request, resource_id: str, error: str | None = None) -> httpx.Response:
        listing = self.listings[resource_id]
        invoice_id = uuid.uuid4().hex
        accepted = {
            "scheme": "exact",
            "network": self.network,
            "asset": "XRP",
            "amount": str(drops_for(listing["price"]["amount_minor"], self.drops_per_usd)),
            "payTo": self.pay_to,
            "maxTimeoutSeconds": 600,
            "extra": {"invoiceId": invoice_id, "sourceTag": 804681468, "areFeesSponsored": False},
        }
        self.invoices[invoice_id] = {"resource_id": resource_id, "accepted": accepted}
        body = {
            "x402Version": 2,
            "resource": {"url": str(request.url), "description": listing["title"], "mimeType": "text/csv"},
            "accepts": [accepted],
        }
        if error:
            body["error"] = error
        return httpx.Response(402, json=body, headers={"PAYMENT-REQUIRED": b64(body)})

    def data_endpoint(self, request: httpx.Request, resource_id: str) -> httpx.Response:
        self.data_requests.append(request)
        header = request.headers.get("PAYMENT-SIGNATURE")
        if not header:
            return self.challenge(request, resource_id)
        if self.paid_response is not None:
            return self.paid_response
        envelope = json.loads(base64.b64decode(header))
        invoice = self.invoices.get(envelope["accepted"]["extra"]["invoiceId"])
        if invoice is None or envelope["accepted"] != invoice["accepted"]:
            return self.challenge(request, resource_id, "requirements_mismatch")
        problem = self.facilitator_problem(envelope, invoice["accepted"])
        if problem:
            return self.challenge(request, resource_id, f"payment_invalid:{problem}")
        tx = Transaction.from_blob(envelope["payload"]["signedTxBlob"])
        self.payments.append(tx.to_xrpl())
        if self.pending_responses:
            self.pending_responses -= 1
            return httpx.Response(409, json={"error": {"code": "settlement_pending", "message": "retry"}})
        receipt_id = uuid.uuid4().hex
        self.receipts[receipt_id] = {"id": receipt_id, "transaction": {"hash": tx.get_hash()}}
        settlement = {"success": True, "transaction": tx.get_hash(), "network": "xrpl:1", "payer": tx.account}
        return httpx.Response(
            200,
            content=self.data.get(resource_id, b"other bytes"),
            headers={"PAYMENT-RESPONSE": b64(settlement), "X-Sliver-Receipt": receipt_id},
        )

    @staticmethod
    def facilitator_problem(envelope: dict, accepted: dict) -> str | None:
        fields = Transaction.from_blob(envelope["payload"]["signedTxBlob"]).to_xrpl()
        checks = {
            "TransactionType": fields.get("TransactionType") == "Payment",
            "Destination": fields.get("Destination") == accepted["payTo"],
            "Amount": fields.get("Amount") == accepted["amount"],
            "InvoiceID": fields.get("InvoiceID") == invoice_id_field(accepted["extra"]["invoiceId"]),
            "SourceTag": fields.get("SourceTag") == accepted["extra"]["sourceTag"],
            "Memos": "Memos" not in fields,
            "SendMax": "SendMax" not in fields and "Paths" not in fields and "DeliverMin" not in fields,
            "LastLedgerSequence": fields.get("LastLedgerSequence", 10**9) <= VALIDATED_LEDGER + 122,
            "payload.invoiceId": envelope["payload"]["invoiceId"] == accepted["extra"]["invoiceId"],
        }
        failed = [name for name, ok in checks.items() if not ok]
        return failed[0] if failed else None


class OfflineSigner:
    address = BUYER.address

    def __init__(self):
        self.signed = 0

    def sign(self, requirement: Requirement):
        self.signed += 1
        return sign_offline(requirement, BUYER, sequence=self.signed, fee_drops=12, validated_ledger=1000)


@pytest.fixture
def stub():
    return StubSliver()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(home=tmp_path / "home", output_dir=tmp_path / "out")


@pytest.fixture
def api(stub, config):
    client = httpx.Client(base_url=config.api_url, transport=httpx.MockTransport(stub.handler))
    return SliverApi(config.api_url, client)


@pytest.fixture
def signer():
    return OfflineSigner()


@pytest.fixture
def buyer(config, api, signer):
    return Buyer(config, api, Store(config.home), lambda: signer, sleep=lambda _seconds: None)
