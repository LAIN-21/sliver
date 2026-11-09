"""How a custom-slice quote is shown to the agent: one sentence to read to its human, plus the
numbers. No MCP dependency, so the scripted demo buyer (`make demo`) uses the same code."""

from typing import Any

from .config import drops_for


def money(minor: int) -> float:
    return minor / 100


def describe_quote(body: dict[str, Any], price_minor: int, drops: int, columns: list[str]) -> str:
    """One sentence an agent can read to its human before asking whether to buy."""
    parent = body.get("parent") or {}
    seller = (body.get("seller") or {}).get("name")
    rows = body.get("row_count")
    time = (body.get("coverage") or {}).get("time") or {}
    where = (body.get("filter") or {}).get("where") or {}
    covers = []
    if time.get("start") and time.get("end"):
        covers.append(f"{time.get('column')} {time['start']} to {time['end']}")
    covers.extend(f"{column} {value}" for column, value in where.items())
    shown = ", ".join(columns[:8]) + (", …" if len(columns) > 8 else "")
    text = (
        f"A custom slice of {parent.get('title')!r}"
        + (f" by {seller}" if seller else "")
        + f": {rows:,} rows × {len(columns)} columns ({shown})"
        + (f", covering {'; '.join(covers)}" if covers else "")
        + f", for ${price_minor / 100:.2f} ({drops / 1_000_000:g} XRP on XRPL Testnet)."
    )
    return text + " Nothing has been spent; buy it only if your human agrees."


def quote_summary(
    status: int, body: dict[str, Any], budget_minor: int | None, drops_per_usd: int
) -> dict[str, Any]:
    """A custom-slice quote (or refusal) as the agent sees it. Nothing has been spent.

    The XRP amount is computed here at the configured rate, the same one sliver_buy checks the
    402 challenge against; a different amount from Sliver is reported as a warning."""
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
    if type(price_minor) is not int or price_minor <= 0 or not isinstance(body.get("row_count"), int):
        return {"status": "error", "message": "Sliver returned a quote without a valid price or row count.",
                "spent": 0}  # fmt: skip
    columns = [str(column.get("name")) for column in body.get("columns") or [] if isinstance(column, dict)]
    drops = drops_for(price_minor, drops_per_usd)
    result = {
        "status": "quoted",
        "summary": describe_quote(body, price_minor, drops, columns),
        "resource_id": body.get("id"),
        "new": body.get("created") is True,
        "parent": {**(body.get("parent") or {}), "seller": (body.get("seller") or {}).get("name")},
        "filter": body.get("filter"),
        "rows": body.get("row_count"),
        "columns": columns,
        "column_count": len(columns),
        "coverage": body.get("coverage"),
        "price_usd": money(price_minor),
        "price_xrp": drops / 1_000_000,
        "payment": {
            "network": "xrpl:1",
            "asset": "XRP",
            "amount_drops": str(drops),
            "drops_per_usd": drops_per_usd,
        },  # fmt: skip
        "price_breakdown": body.get("price_breakdown"),
        "validity": body.get("validity"),
        "sha256": (body.get("content") or {}).get("sha256"),
        "seller": (body.get("seller") or {}).get("name"),
        "spent": 0,
    }
    offered = (body.get("payment") or {}).get("amount_drops")
    if offered is not None and str(offered) != str(drops):
        result["warning"] = (
            f"Sliver quoted {offered} drops but this MCP expects {drops} at its configured rate; "
            "sliver_buy will refuse a challenge that does not match."
        )
    if budget_minor is not None and isinstance(price_minor, int):
        result["within_budget"] = price_minor <= budget_minor
    result["next"] = (
        "Tell your human the summary and ask whether it is worth it. Only after they agree, call "
        f"sliver_buy(resource_id={body.get('id')!r}, budget_usd=<your human's budget>)."
    )
    return result
