"""Independent, budget-bound buyer for the Sliver local demonstration.

Discovery and analysis run here, outside Sliver. Nothing spends by default.
Use --confirm-simulated for a SIMULATED / NO REAL MONEY purchase, or supply a
testnet transaction hash. Optional --sign-testnet signs locally after an explicit
prompt, using examples/requirements-testnet.txt. Keys never enter HTTP requests
to Sliver, its logs, or the recovery file. No mainnet endpoint is supported.

The recovery file contains a private session cookie, not wallet keys. Keep it
outside the repository. Logout/session expiry loses access in this local demo.
"""

from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import io
import json
import os
import re
import sys
import warnings
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

import httpx

TESTNET_RPC = "https://s.altnet.rippletest.net:51234"
COOKIE = "sliver_session"
MAX_BYTES = 5 * 1024 * 1024


class BuyerError(Exception):
    """An actionable error whose message contains no credentials."""


def route_summary(data: bytes) -> dict:
    """Parse bounded UTF-8 CSV, then calculate reproducible route statistics."""
    if not data or len(data) > MAX_BYTES:
        raise BuyerError("Downloaded CSV exceeds the 5 MiB analysis limit.")
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
    columns = reader.fieldnames or []
    if not columns or len(columns) > 100 or len(set(columns)) != len(columns):
        raise BuyerError("Downloaded CSV has an invalid schema.")
    rows = []
    for row in reader:
        if len(rows) >= 10_000 or None in row or any(v is None for v in row.values()):
            raise BuyerError("Downloaded CSV has invalid rows or exceeds 10,000 rows.")
        rows.append(row)
    result: dict = {"row_count": len(rows), "columns": columns}
    if not {"route", "delay_minutes"}.issubset(columns):
        return result
    routes: dict[str, list] = {}
    for row in rows:
        try:
            delay = Decimal(row["delay_minutes"])
        except InvalidOperation:
            raise BuyerError("Route delay must be a finite number.") from None
        if not delay.is_finite() or not row["route"].strip():
            raise BuyerError("Route delay must be finite and route must be present.")
        on_time = row.get("delivered_on_time", "").strip().lower()
        if "delivered_on_time" in columns and on_time not in {"true", "false", "1", "0"}:
            raise BuyerError("delivered_on_time must be true/false or 1/0.")
        values = routes.setdefault(row["route"], [])
        values.append((delay, on_time in {"true", "1"}))
    result["routes"] = [
        {"route": route, "observations": len(values),
         "average_delay_minutes": float(sum(v[0] for v in values) / len(values)),
         **({"on_time_percent": 100 * sum(v[1] for v in values) / len(values)}
            if "delivered_on_time" in columns else {})}
        for route, values in sorted(routes.items())
    ]
    return result


def save_state(path: Path, state: dict, client: httpx.Client) -> None:
    # The only credential persisted is the API session needed to reconcile an
    # unknown outcome. Never persist the wallet object, seed, or private key.
    cookies = [cookie for cookie in client.cookies.jar if cookie.name == COOKIE]
    if len(cookies) != 1:
        raise BuyerError("Cannot preserve a unique buyer session. Keep the existing recovery file.")
    state["session_cookie"] = cookies[0].value
    state["session_cookie_domain"] = cookies[0].domain
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(state, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def request_json(client: httpx.Client, method: str, path: str, **kwargs) -> dict:
    response = client.request(method, path, **kwargs)
    if not response.is_success:
        try:
            code = response.json().get("detail", {}).get("code", "request_failed")
        except (ValueError, AttributeError):
            code = "request_failed"
        raise BuyerError(f"API refused the request: HTTP {response.status_code}, {code}.")
    return response.json()


def prepare_wallet():
    try:
        from xrpl.wallet import Wallet
    except ImportError:
        raise BuyerError("Install examples/requirements-testnet.txt for optional local signing.") from None
    # Prompt input is hidden and never passed through a command-line argument.
    if not sys.stdin.isatty():
        raise BuyerError("Local signing requires an interactive terminal with hidden seed input.")
    with warnings.catch_warnings():
        # getpass otherwise falls back to echoed stdin, which could expose a key
        # in a recording or redirected log when a terminal cannot hide input.
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            seed = getpass.getpass("Funded TESTNET wallet seed (hidden, local process only): ")
        except getpass.GetPassWarning:
            raise BuyerError("Terminal cannot hide seed input; signing refused.") from None
    try:
        wallet = Wallet.from_seed(seed)
    except Exception:
        raise BuyerError("Could not derive a wallet from the supplied testnet seed.") from None
    finally:
        seed = None
    return wallet


def sign_once(quote: dict, wallet, args, state: dict, client: httpx.Client) -> str:
    """Persist a hash before submitting once; recovery only reconciles that hash."""
    from xrpl.clients import JsonRpcClient
    from xrpl.models.transactions import Memo, Payment
    from xrpl.transaction import autofill_and_sign, submit

    if state.get("transaction_hash") or state.get("submission_started"):
        raise BuyerError("A payment attempt already exists. Re-run without --sign-testnet to reconcile it.")
    amount = str(quote.get("amount_drops", ""))
    if (quote.get("mode") != "xrpl-testnet" or quote.get("network") != "xrpl:1"
            or not amount.isdigit() or not 0 < int(amount) <= args.max_testnet_drops
            or quote.get("buyer_address") != wallet.classic_address
            or quote.get("memo") != quote["id"]):
        raise BuyerError("Quote failed the external buyer's testnet payment policy.")
    expires_at = datetime.fromisoformat(quote["expires_at"].replace("Z", "+00:00"))

    def require_live_quote():
        if expires_at <= datetime.now(timezone.utc):
            raise BuyerError("Quote expired. No payment was submitted.")

    require_live_quote()
    print(f"TESTNET ONLY: {amount} drops to {quote['pay_to']}; fee cap {args.max_fee_drops} drops.")
    if input("Type PAY TESTNET to authorize this one payment: ") != "PAY TESTNET":
        raise BuyerError("Testnet payment was not authorized.")
    # Authorization can take longer than the quote lifetime. Refuse before any
    # signing/autofill work when the user approves an already-expired quote.
    require_live_quote()
    rpc = JsonRpcClient(TESTNET_RPC)
    transaction = Payment(account=wallet.classic_address, destination=quote["pay_to"],
                          amount=amount, memos=[Memo(memo_data=quote["id"].encode().hex().upper())])
    try:
        signed = autofill_and_sign(transaction, rpc, wallet)
    except Exception:
        raise BuyerError("Local signing/autofill failed; no payment was submitted.") from None
    if not signed.fee or int(signed.fee) > args.max_fee_drops:
        raise BuyerError("Network fee exceeds the buyer's explicit fee cap; no payment was submitted.")
    # Autofill may block on the ledger. An expired quote cannot accept its first
    # proof, so never submit or mark an attempt after that boundary has passed.
    require_live_quote()
    transaction_hash = signed.get_hash()
    state["transaction_hash"] = transaction_hash
    state["submission_started"] = True
    save_state(args.state, state, client)
    try:
        submit(signed, rpc)
    except Exception:
        # A timeout is unknown, not failure. Keep the same hash and do not sign
        # or submit another transaction, including on a subsequent invocation.
        print("Submission outcome unknown. Saved hash will be reconciled; do not pay again.")
    return transaction_hash


def run(args) -> int:
    parsed = urlsplit(args.base_url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise BuyerError("Use an http(s) API origin without credentials, path, query, or fragment.")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise BuyerError("Unencrypted HTTP is permitted only for a loopback local demo.")
    if args.budget_minor < 0 or args.max_testnet_drops <= 0 or args.max_fee_drops <= 0:
        raise BuyerError("Budget must be nonnegative; testnet amount and fee caps must be positive.")
    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else {}
    base_url = args.base_url.rstrip("/")
    if state and (state.get("base_url") != base_url or state.get("origin") != args.origin):
        raise BuyerError("Recovery state belongs to another API or origin. Use a different --state file.")
    state.update(base_url=base_url, origin=args.origin)
    with httpx.Client(base_url=base_url, timeout=25, follow_redirects=False) as client:
        if state.get("session_cookie"):
            client.cookies.set(COOKIE, state["session_cookie"],
                               domain=state.get("session_cookie_domain") or parsed.hostname, path="/")
        config = request_json(client, "GET", "/api/marketplace")
        mode = config.get("mode")
        if mode == "disabled":
            raise BuyerError("Marketplace payments are disabled.")
        if mode == "simulated":
            print("SIMULATED / NO REAL MONEY — receipts are demonstration records only.")
            if args.sign_testnet or args.transaction_hash:
                raise BuyerError("Testnet proof/signing cannot be used in simulated mode.")
        elif mode == "xrpl-testnet" and config.get("network") == "xrpl:1":
            print("XRPL TESTNET ONLY — illustrative USD conversion, no mainnet or live FX.")
            if args.confirm_simulated:
                raise BuyerError("Simulated confirmation is forbidden in testnet mode.")
        else:
            raise BuyerError("Unknown marketplace mode/network; refusing to proceed.")

        old_quote = state.get("quote")
        if args.new_quote and old_quote:
            if state.get("transaction_hash") or old_quote.get("status") == "pending":
                raise BuyerError("Existing payment attempt must be reconciled; no new quote/payment is automatic.")
            state.pop("quote", None)
            old_quote = None
        # A resumed quote must use its original cookie. Do not silently create a
        # replacement session after logout/expiry and lose its recovery identity.
        if old_quote:
            quote = request_json(client, "GET", f"/api/quotes/{old_quote['id']}")
            session = request_json(client, "GET", "/api/session")
        else:
            session = request_json(client, "GET", "/api/session")
            catalog = request_json(client, "GET", "/api/catalog", params={
                "q": args.query, "max_price_minor": args.budget_minor, "limit": 100})
            candidates = [item for item in catalog["items"] if item.get("currency") == "USD"
                          and isinstance(item.get("price_minor"), int)
                          and 0 < item["price_minor"] <= args.budget_minor
                          and (not args.resource_id or item["id"] == args.resource_id)]
            if not candidates:
                raise BuyerError("BUDGET REFUSAL: no matching offer fits this client's budget; no quote or payment requested.")
            selected = min(candidates, key=lambda item: (item["price_minor"], item["id"]))
            print(f"External buyer selected {selected['title']} for {selected['price_minor']} USD cents from {len(catalog['items'])} returned metadata candidates.")
            wallet = prepare_wallet() if args.sign_testnet else None
            buyer_address = wallet.classic_address if wallet else args.buyer_address
            if mode == "xrpl-testnet" and not buyer_address:
                raise BuyerError("Provide --buyer-address for testnet proof, or use --sign-testnet.")
            body = {"resource_id": selected["id"]}
            if buyer_address:
                body["buyer_address"] = buyer_address
            quote = request_json(client, "POST", "/api/quotes", json=body, headers={
                "Origin": args.origin, "X-CSRF-Token": session["csrf_token"]})
            # Store before checking subsequent behavior: a returned quote is
            # recoverable even if the external client's metadata check fails.
            state["quote"] = quote
            save_state(args.state, state, client)
            if (quote["resource_id"] != selected["id"] or any(
                    quote.get(key) != selected.get(key)
                    for key in ("price_minor", "currency", "sha256", "size_bytes", "dataset_version"))):
                raise BuyerError("Quote differs from the chosen immutable metadata; refusing payment.")

        if (quote["mode"] != mode or quote["price_minor"] > args.budget_minor
                or quote["currency"] != "USD"):
            raise BuyerError("BUDGET/MODE REFUSAL: quote exceeds this client's current policy.")
        state["quote"] = quote
        save_state(args.state, state, client)
        print(json.dumps({key: quote.get(key) for key in
                          ("id", "mode", "network", "price_minor", "currency", "amount_drops",
                           "pay_to", "memo", "buyer_address", "expires_at", "status")}, indent=2))
        headers = {"Origin": args.origin, "X-CSRF-Token": session["csrf_token"]}
        proof = state.get("transaction_hash") or args.transaction_hash
        if args.transaction_hash and state.get("transaction_hash") not in {None, args.transaction_hash}:
            raise BuyerError("Cannot replace a recorded payment hash. Reconcile the same attempt.")
        if args.sign_testnet and quote["status"] != "paid":
            if old_quote:
                raise BuyerError("Signing is only available on a newly selected quote; reconcile saved attempts without --sign-testnet.")
            proof = sign_once(quote, wallet, args, state, client)
        if proof:
            if not re.fullmatch(r"[0-9A-Fa-f]{64}", proof):
                raise BuyerError("Transaction hash must contain exactly 64 hexadecimal characters.")
            state["transaction_hash"] = proof
            save_state(args.state, state, client)
        if quote["status"] != "paid" and ((mode == "simulated" and args.confirm_simulated)
                                          or (mode == "xrpl-testnet" and proof)):
            quote = request_json(client, "POST", f"/api/quotes/{quote['id']}/confirm",
                                 json={"transaction_hash": proof} if proof else {}, headers=headers)
            state["quote"] = quote
            save_state(args.state, state, client)
        if quote["status"] != "paid":
            print(f"Quote remains {quote['status']}. No CSV released. Re-run with the same recovery file.")
            return 2
        with client.stream("GET", f"/api/quotes/{quote['id']}/download") as response:
            if response.status_code != 200:
                raise BuyerError(f"Purchased delivery unavailable: HTTP {response.status_code}.")
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise BuyerError("Downloaded CSV exceeds the buyer's 5 MiB limit.")
                chunks.append(chunk)
        data = b"".join(chunks)
        digest = hashlib.sha256(data).hexdigest()
        if digest != quote["sha256"] or len(data) != quote["size_bytes"]:
            raise BuyerError("Downloaded bytes fail the immutable quote digest/size check.")
        summary = route_summary(data)
        if args.output:
            # Exclusive creation prevents accidentally overwriting a local file.
            with args.output.open("xb") as stream:
                stream.write(data)
        print(json.dumps({"mode": mode, "receipt_id": quote["receipt_id"],
                          "transaction_hash": quote.get("transaction_hash"),
                          "sha256_verified": digest, "size_bytes_verified": len(data),
                          "analysis": summary}, indent=2))
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--origin", default="http://127.0.0.1:5173")
    parser.add_argument("--query", default="Synthetic")
    parser.add_argument("--resource-id")
    parser.add_argument("--budget-minor", type=int, default=500, help="External buyer maximum price in USD cents")
    parser.add_argument("--state", type=Path, default=Path.home() / ".sliver" / "buyer-session.json")
    parser.add_argument("--new-quote", action="store_true", help="Explicitly select another quote if no payment attempt exists")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--confirm-simulated", action="store_true")
    actions.add_argument("--transaction-hash", help="An existing independently submitted TESTNET transaction hash")
    actions.add_argument("--sign-testnet", action="store_true", help="Prompt for a testnet seed and explicit one-time authorization")
    parser.add_argument("--buyer-address", help="Expected testnet payment sender; required without local signing")
    parser.add_argument("--max-testnet-drops", type=int, default=10_000_000)
    parser.add_argument("--max-fee-drops", type=int, default=100)
    parser.add_argument("--output", type=Path, help="Write verified CSV to a new file")
    args = parser.parse_args()
    if args.transaction_hash:
        args.transaction_hash = args.transaction_hash.upper()
    try:
        return run(args)
    except BuyerError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (httpx.HTTPError, OSError, ValueError, KeyError, csv.Error):
        print("Buyer request, local recovery, or CSV validation failed. Keep the recovery file; do not pay again after an unknown outcome.", file=sys.stderr)
        return 1
    except Exception:
        # SDK failures must not print exception internals containing wallet data.
        print("Local buyer operation failed. Keep the recovery file and reconcile any saved transaction hash before another payment.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
