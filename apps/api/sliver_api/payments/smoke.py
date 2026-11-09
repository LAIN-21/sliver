"""Real XRPL Testnet purchase through t54's official x402 client: `make smoke-testnet`.

Buys the cheapest published Resource with the demo buyer wallet, checks the delivered bytes
against the catalog SHA-256, replays the same payment (must re-deliver without paying again),
and asks the official x402.org facilitator to verify (not settle) a payment for our requirements.
"""

import hashlib
import json
import sys
from pathlib import Path

import httpx
import requests
from x402_xrpl.client import XRPLPresignedPaymentPayer, XRPLPresignedPaymentPayerOptions
from x402_xrpl.clients import decode_payment_response, x402_requests
from x402_xrpl.types import PaymentRequirements
from xrpl.account import get_balance
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet

from ..config import get_settings
from .wallets import BUYER_VAR, read_env
from .x402 import explorer_url

OFFICIAL_FACILITATOR = "https://x402.org/facilitator"


def check_official_facilitator(url: str, buyer: Wallet, rpc_url: str) -> dict:
    challenge = requests.get(url, timeout=30).json()
    requirements = PaymentRequirements.from_dict(challenge["accepts"][0])
    payer = XRPLPresignedPaymentPayer(
        XRPLPresignedPaymentPayerOptions(
            wallet=buyer, network="xrpl:1", rpc_url=rpc_url, invoice_binding="invoice_id"
        )
    )
    prepared = payer.prepare_payment(requirements)
    response = httpx.post(
        f"{OFFICIAL_FACILITATOR}/verify",
        json={
            "paymentPayload": prepared.payment_payload.to_dict(),
            "paymentRequirements": requirements.to_dict(),
        },
        timeout=30,
    )
    try:
        return {"status": response.status_code, "body": response.json()}
    except ValueError:
        return {"status": response.status_code, "body": response.text[:300]}


def main() -> None:
    env_path, base_url = Path(sys.argv[1]), sys.argv[2].rstrip("/")
    settings = get_settings()
    seed = read_env(env_path).get(BUYER_VAR)
    if not seed:
        sys.exit(f"{BUYER_VAR} is missing; run `make wallets` first")
    buyer = Wallet.from_seed(seed)
    rpc = JsonRpcClient(settings.xrpl_rpc_url)

    catalog = requests.get(f"{base_url}/api/catalog", params={"limit": 50}, timeout=30).json()["items"]
    if not catalog:
        sys.exit("The catalog is empty; run `make seed`")
    resource = min(catalog, key=lambda item: item["price"]["amount_minor"])
    url = f"{base_url}/api/resources/{resource['id']}/data"
    before = int(get_balance(buyer.address, rpc))

    compatibility = check_official_facilitator(url, buyer, settings.xrpl_rpc_url)

    session = x402_requests(
        buyer,
        rpc_url=settings.xrpl_rpc_url,
        network_filter=settings.xrpl_network,
        scheme_filter="exact",
        invoice_binding="invoice_id",
    )
    paid = session.get(url, timeout=120)
    if paid.status_code != 200:
        sys.exit(f"purchase failed: HTTP {paid.status_code} {paid.text[:500]}")
    digest = hashlib.sha256(paid.content).hexdigest()
    if digest != resource["content"]["sha256"]:
        sys.exit("delivered bytes do not match the catalog SHA-256")
    settlement = decode_payment_response(paid.headers["PAYMENT-RESPONSE"])

    replay = requests.get(
        url, headers={"PAYMENT-SIGNATURE": paid.request.headers["PAYMENT-SIGNATURE"]}, timeout=120
    )
    after = int(get_balance(buyer.address, rpc))
    receipt = requests.get(f"{base_url}/api/receipts/{paid.headers['X-Sliver-Receipt']}", timeout=30).json()

    print(
        json.dumps(
            {
                "resource": resource["title"],
                "price_usd_minor": resource["price"]["amount_minor"],
                "buyer": buyer.address,
                "transaction": settlement["transaction"],
                "explorer": explorer_url(settlement["transaction"]),
                "receipt": receipt,
                "sha256_matches_catalog": True,
                "bytes": len(paid.content),
                "replay": {"status": replay.status_code, "same_bytes": replay.content == paid.content},
                "buyer_spent_drops": before - after,
                "official_x402_org_facilitator_verify": compatibility,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
