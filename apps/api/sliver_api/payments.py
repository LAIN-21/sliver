"""Read-only XRPL TESTNET proof checks. This module never signs or submits payments."""

import hashlib
import json
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

RIPPLE_ALPHABET = "rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"
MAX_RPC_BYTES = 1_048_576


def valid_classic_address(address: str) -> bool:
    """Check the account-id version, payload length and base58check checksum."""
    if not isinstance(address, str) or not 25 <= len(address) <= 35 or not address.startswith("r"):
        return False
    value = 0
    for char in address:
        if char not in RIPPLE_ALPHABET:
            return False
        value = value * 58 + RIPPLE_ALPHABET.index(char)
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    raw = b"\0" * (len(address) - len(address.lstrip(RIPPLE_ALPHABET[0]))) + raw
    return (len(raw) == 25 and raw[0] == 0 and
            hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] == raw[-4:])


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_transaction(rpc_url: str, transaction_hash: str) -> dict:
    """One bounded request to the configured testnet server; unknown is never success."""
    payload = json.dumps({"method": "tx", "params": [{
        "transaction": transaction_hash, "binary": False, "api_version": 2,
    }]}).encode("utf-8")
    request = Request(rpc_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with build_opener(NoRedirects()).open(request, timeout=5) as response:
        body = response.read(MAX_RPC_BYTES + 1)
    if len(body) > MAX_RPC_BYTES:
        raise ValueError("RPC response exceeded its limit")
    document = json.loads(body)
    if not isinstance(document, dict) or not isinstance(document.get("result"), dict):
        raise ValueError("Invalid RPC response")
    return document["result"]


def verify_testnet_payment(quote, rpc_url: str) -> str:
    """Return paid, pending, or failed. Unknown outcomes retain the same attempt."""
    try:
        result = fetch_transaction(rpc_url, quote.transaction_hash)
    except (URLError, OSError, ValueError, TimeoutError):
        return "pending"
    if result.get("error") or result.get("validated") is not True:
        return "pending"
    # v2 places common transaction fields in tx_json. Support the v1 flat form too.
    tx = result.get("tx_json", result)
    meta = result.get("meta")
    if not isinstance(tx, dict) or not isinstance(meta, dict):
        return "failed"
    result_hash = result.get("hash", tx.get("hash"))
    if not isinstance(result_hash, str) or result_hash.upper() != quote.transaction_hash:
        return "failed"
    flags = tx.get("Flags", 0)
    if type(flags) is not int or flags < 0 or flags & 0x00020000:
        return "failed"
    if (tx.get("TransactionType") != "Payment" or meta.get("TransactionResult") != "tesSUCCESS" or
            tx.get("Destination") != quote.pay_to or tx.get("Account") != quote.buyer_address or
            type(meta.get("delivered_amount")) is not str or
            meta.get("delivered_amount") != quote.amount_drops):
        return "failed"
    memos = tx.get("Memos", [])
    if not isinstance(memos, list) or len(memos) > 32:
        return "failed"
    expected_memo = quote.id.encode("utf-8").hex().upper()
    for entry in memos:
        memo = entry.get("Memo") if isinstance(entry, dict) else None
        data = memo.get("MemoData") if isinstance(memo, dict) else None
        if isinstance(data, str) and data.upper() == expected_memo:
            return "paid"
    return "failed"
