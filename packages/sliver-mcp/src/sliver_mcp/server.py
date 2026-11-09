"""The Sliver buyer MCP server (stdio). The buyer's own tool: it runs on the buyer's machine,
signs with the buyer's key, and spends only within the budget the buyer's human sets."""

from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .api import ApiError, SliverApi
from .buyer import Buyer, Refused, XrplSigner, check_resource_id
from .config import Config, drops_for, usd_to_minor
from .evaluate import evaluate
from .store import Store
from .wallet import WalletMissing, balance_drops, load_wallet

INSTRUCTIONS = """\
Sliver is a marketplace of small, verifiable data slices ("slivers") sold per purchase with x402
on the XRP Ledger Testnet. This server is the buyer's own tool: it signs payments locally with the
buyer's wallet, and every spending decision belongs to you and your human.

Use it honestly:
1. Search with sliver_search, then call sliver_evaluate with the human's actual need (required
   columns, time range, budget) before buying anything.
2. If the recommendation is look_elsewhere, say plainly that Sliver does not have this data and
   suggest looking elsewhere. Do not buy a near miss.
3. When sliver_evaluate suggests a custom slice (the best sliver covers much more than the need),
   call sliver_quote_slice with its arguments. Quoting is free and never spends: Sliver cuts just
   the requested rows and prices them per row. Compare the quote with the pre-cut sliver and buy
   whichever fits the need and the budget; a quote's id is bought with sliver_buy like any sliver.
4. Only call sliver_buy with a budget your human gave you. Never exceed it and never invent one.
   If the best fit costs more than the budget, ask your human before doing anything else.
5. Pass sliver_buy a short, honest reason: your human's actual need in plain words, for example
   "Weekly SGSIN-CNSHA spot rates since September to quote a shipment". Sliver shows it publicly
   on the purchase timeline, so never include wallet data, seeds, budgets or your human's private
   details.
6. After buying, report the file path, the SHA-256 check, the transaction hash and explorer link.
Testnet only: no real money moves.
"""


def money(minor: int) -> float:
    return minor / 100


def summary(listing: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": listing.get("id"),
        "title": listing.get("title"),
        "category": listing.get("category"),
        "price_usd": money((listing.get("price") or {}).get("amount_minor") or 0),
        "columns": [column.get("name") for column in listing.get("columns") or []],
        "rows": listing.get("row_count"),
        "coverage": listing.get("coverage"),
        "seller": (listing.get("seller") or {}).get("name"),
    }


def refusal(error: Exception) -> dict[str, Any]:
    if isinstance(error, Refused) and error.paid:
        return {"status": "paid_not_completed", "code": error.code, "message": error.message, **error.paid}
    if isinstance(error, Refused):
        return {"status": "refused", "code": error.code, "message": error.message, "spent": 0}
    return {"status": "error", "message": str(error), "hint": "Check sliver_purchases before retrying."}


def quote_summary(status: int, body: dict[str, Any], budget_minor: int | None) -> dict[str, Any]:
    """A custom-slice quote (or refusal) as the agent sees it. Nothing has been spent."""
    if status not in (200, 201):
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        hints = {key: value for key, value in error.items() if key not in ("code", "message")}
        return {
            "status": "refused",
            "code": str(error.get("code") or f"http_{status}"),
            "message": str(error.get("message") or body.get("detail") or ""),
            **hints,
            "spent": 0,
        }
    price_minor = (body.get("price") or {}).get("amount_minor")
    result = {
        "status": "quoted",
        "resource_id": body.get("id"),
        "new": body.get("created") is True,
        "parent": body.get("parent"),
        "filter": body.get("filter"),
        "rows": body.get("row_count"),
        "coverage": body.get("coverage"),
        "price_usd": money(price_minor) if isinstance(price_minor, int) else None,
        "price_breakdown": body.get("price_breakdown"),
        "sha256": (body.get("content") or {}).get("sha256"),
        "seller": (body.get("seller") or {}).get("name"),
        "spent": 0,
    }
    if budget_minor is not None and isinstance(price_minor, int):
        result["within_budget"] = price_minor <= budget_minor
    result["next"] = (
        f"To buy, call sliver_buy(resource_id={body.get('id')!r}, budget_usd=<your human's budget>)."
    )
    return result


def build_server(config: Config, *, api: SliverApi | None = None, buyer: Buyer | None = None) -> MCPServer:
    api = api or SliverApi(config.api_url)
    store = Store(config.home)

    def signer():
        return XrplSigner(load_wallet(store), config.rpc_url, config.max_fee_drops)

    buyer = buyer or Buyer(config, api, store, signer)
    server = MCPServer("sliver", instructions=INSTRUCTIONS, version="0.1.0")
    read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

    @server.tool(annotations=read_only)
    def sliver_search(
        query: str = "",
        category: str | None = None,
        max_price_usd: float | None = None,
        columns: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search Sliver's catalog of data slivers. Returns public metadata only, never data."""
        try:
            found = api.search(
                q=query,
                category=category,
                max_price_minor=usd_to_minor(max_price_usd, "max_price_usd") if max_price_usd else None,
                columns=",".join(columns or []) or None,
                limit=max(1, min(limit, 50)),
            )
        except (ApiError, ValueError) as error:
            return refusal(error)
        return {"total": found.get("total"), "items": [summary(item) for item in found.get("items", [])]}

    @server.tool(annotations=read_only)
    def sliver_inspect(resource_id: str) -> dict[str, Any]:
        """Full public listing of one sliver: columns, coverage, provenance, price, SHA-256."""
        try:
            listing = api.listing(check_resource_id(resource_id))
        except (ApiError, Refused) as error:
            return refusal(error)
        price_minor = (listing.get("price") or {}).get("amount_minor") or 0
        return {
            **listing,
            "expected_payment": {
                "network": "xrpl:1",
                "asset": "XRP",
                "amount_drops": str(drops_for(price_minor, config.drops_per_usd)),
                "drops_per_usd": config.drops_per_usd,
            },
        }

    @server.tool(annotations=read_only)
    def sliver_evaluate(
        need: str,
        required_columns: list[str] | None = None,
        required_terms: list[str] | None = None,
        time_start: str | None = None,
        time_end: str | None = None,
        max_age_days: int | None = None,
        budget_usd: float | None = None,
        resource_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Deterministic fit report for a need: buy, skip or look_elsewhere, with reasons. Never spends.

        need: the human's information need in plain words. required_columns / required_terms must
        all appear in a listing's metadata. time_start / time_end: YYYY, YYYY-MM or YYYY-MM-DD.
        resource_ids: evaluate these listings instead of searching for the need.
        """
        try:
            if resource_ids:
                listings = [api.listing(check_resource_id(rid)) for rid in resource_ids[:20]]
            else:
                listings = api.search(q=need, limit=20).get("items", [])
            return evaluate(
                listings,
                need=need,
                today=date.today(),
                required_columns=required_columns or [],
                required_terms=required_terms or [],
                time_start=time_start,
                time_end=time_end,
                max_age_days=max_age_days,
                budget_minor=None if budget_usd is None else usd_to_minor(budget_usd, "budget_usd"),
            )
        except (ApiError, Refused, ValueError) as error:
            return refusal(error)

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
        )
    )
    def sliver_quote_slice(
        resource_id: str,
        time_start: str | None = None,
        time_end: str | None = None,
        where: dict[str, str] | None = None,
        budget_usd: float | None = None,
    ) -> dict[str, Any]:
        """Quote a custom slice: exactly the rows your human needs from a full-dataset listing.
        Never spends.

        resource_id: a full-dataset listing whose custom_slices.available is true.
        time_start / time_end: YYYY, YYYY-MM or YYYY-MM-DD, inclusive, on the dataset's time column.
        where: equality on category columns, for example {"lane": "SGSIN-CNSHA"}.
        budget_usd: optional, only to say whether the quote fits; nothing is bought here.
        Sliver answers with an unlisted sliver id, rows, coverage, price (with its breakdown) and
        SHA-256, never row values. Buy it with sliver_buy(resource_id=<that id>, budget_usd=...).
        Refusals name what can be filtered, or point to an existing sliver with the same rows.
        """
        try:
            status, body = api.quote_slice(check_resource_id(resource_id), time_start, time_end, where)
            budget_minor = None if budget_usd is None else usd_to_minor(budget_usd, "budget_usd")
        except (ApiError, Refused, ValueError) as error:
            return refusal(error)
        return quote_summary(status, body, budget_minor)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
    def sliver_buy(
        resource_id: str,
        budget_usd: float | None = None,
        output_dir: str | None = None,
        reason: str | None = None,
    ) -> dict:
        """Buy one sliver with x402 on XRPL Testnet, paying the seller directly from the buyer wallet.

        budget_usd is required: the most your human allowed for this purchase. Refused when there
        is no budget, the price exceeds it or a local cap, the 402 challenge differs from the
        listing, the network is not Testnet, or another purchase is in flight. Saves the CSV
        (default ~/.sliver/data), checks its SHA-256, returns the transaction hash and explorer link.

        reason: a short, honest statement of why your human needs this data (at most 200
        characters), sent to Sliver and shown publicly on the purchase timeline. Never include
        wallet data, seeds, budgets or your human's private details.
        """
        try:
            return buyer.buy(resource_id, budget_usd, output_dir, reason)
        except (Refused, WalletMissing, ValueError) as error:
            return refusal(error)

    @server.tool(annotations=read_only)
    def sliver_wallet() -> dict[str, Any]:
        """The buyer wallet's address, Testnet balance and spend in the last 24 hours (never the seed)."""
        spent = store.spent_minor()
        result: dict[str, Any] = {
            "network": "xrpl:1",
            "spent_last_24h_usd": money(spent),
            "daily_cap_usd": money(config.daily_cap_minor),
            "remaining_today_usd": money(max(config.daily_cap_minor - spent, 0)),
            "max_per_purchase_usd": money(config.max_purchase_minor),
        }
        try:
            wallet = load_wallet(store)
        except WalletMissing as error:
            return {**result, "address": None, "message": str(error)}
        drops = balance_drops(wallet.address, config.rpc_url)
        return {
            **result,
            "address": wallet.address,
            "balance_xrp": None if drops is None else drops / 1_000_000,
            "explorer_url": f"https://testnet.xrpl.org/accounts/{wallet.address}",
        }

    @server.tool(annotations=read_only)
    def sliver_purchases(limit: int = 20) -> dict[str, Any]:
        """Purchases made from this machine, newest first, with files, hashes and transactions."""
        records = sorted(store.purchases(), key=lambda item: item["created_at"], reverse=True)
        return {"items": records[: max(1, min(limit, 200))], "spent_last_24h_usd": money(store.spent_minor())}

    return server
