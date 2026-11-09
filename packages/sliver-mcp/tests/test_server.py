"""End to end through the MCP protocol: an in-process MCP client drives the server's tools
against the stub Sliver API and stub facilitator."""

import asyncio
import json
import os
from pathlib import Path

import pytest
from mcp import Client

from conftest import BUYER, CUSTOM_CSV, CUSTOM_ID, FULL_BERTHS
from sliver_mcp import server as server_module
from sliver_mcp.server import build_server
from sliver_mcp.store import Store
from sliver_mcp.wallet import WalletMissing, init_wallet, load_wallet

CHEAP = "11111111-1111-4111-8111-111111111111"


def call(server, tool: str, arguments: dict | None = None) -> dict:
    async def run():
        async with Client(server) as client:
            result = await client.call_tool(tool, arguments or {})
            return json.loads(result.content[0].text)

    return asyncio.run(run())


@pytest.fixture
def server(config, api, buyer):
    return build_server(config, api=api, buyer=buyer)


def test_tools_and_honest_use_instructions(server):
    async def tools():
        async with Client(server) as client:
            return [tool.name for tool in (await client.list_tools()).tools]

    assert asyncio.run(tools()) == [
        "sliver_search",
        "sliver_inspect",
        "sliver_evaluate",
        "sliver_quote_slice",
        "sliver_buy",
        "sliver_wallet",
        "sliver_purchases",
    ]
    for rule in ("before buying", "suggest looking elsewhere", "Never exceed it", "ask your human"):
        assert rule in server.instructions
    assert "honest reason" in server.instructions and "never include wallet data" in server.instructions


def test_buy_sends_the_reason_as_the_agent_note_through_the_protocol(server, stub):
    async def schema():
        async with Client(server) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            return tools["sliver_buy"]

    tool = asyncio.run(schema())
    properties, required = tool.input_schema["properties"], tool.input_schema.get("required", [])
    assert "reason" in properties and "reason" not in required
    assert "never include wallet data" in " ".join(tool.description.lower().split())

    reason = "Weekly SGSIN-CNSHA spot rates to quote a shipment"
    bought = call(server, "sliver_buy", {"resource_id": CHEAP, "budget_usd": 5, "reason": reason})
    assert bought["status"] == "delivered"
    assert [request.headers.get("X-Sliver-Agent-Note") for request in stub.data_requests] == [reason, reason]


def test_search_evaluate_buy_and_list_purchases(server, stub):
    found = call(server, "sliver_search", {"query": "container"})
    assert [item["id"] for item in found["items"]] == [CHEAP]
    listing = call(server, "sliver_inspect", {"resource_id": CHEAP})
    assert listing["expected_payment"]["amount_drops"] == "600000"

    report = call(
        server,
        "sliver_evaluate",
        {"need": "container spot freight rates Singapore", "required_terms": ["CNSHA"], "budget_usd": 5},
    )
    assert report["recommendation"] == "buy" and report["best"] == CHEAP

    bought = call(server, "sliver_buy", {"resource_id": CHEAP, "budget_usd": 5})
    assert bought["status"] == "delivered" and bought["sha256_verified"] is True
    assert Path(bought["file"]).read_bytes() == stub.data[CHEAP]
    assert bought["explorer_url"] == f"https://testnet.xrpl.org/transactions/{bought['tx_hash']}"

    purchases = call(server, "sliver_purchases")
    assert purchases["items"][0]["tx_hash"] == bought["tx_hash"]
    assert purchases["spent_last_24h_usd"] == 1.5


def test_buy_without_budget_is_refused_through_the_protocol(server, stub):
    refused = call(server, "sliver_buy", {"resource_id": CHEAP})
    assert refused == {
        "status": "refused",
        "code": "no_budget",
        "message": refused["message"],
        "spent": 0,
    }
    assert not stub.payments


def test_look_elsewhere_through_the_protocol(server):
    report = call(server, "sliver_evaluate", {"need": "air-cargo rates Changi to Frankfurt", "budget_usd": 5})
    assert report["recommendation"] == "look_elsewhere"


def test_wallet_tool_never_returns_the_seed(server, monkeypatch):
    monkeypatch.setenv("SLIVER_WALLET_SEED", BUYER.seed)
    monkeypatch.setattr(server_module, "balance_drops", lambda address, rpc_url: 25_000_000)
    wallet = call(server, "sliver_wallet")
    assert wallet["address"] == BUYER.address and wallet["balance_xrp"] == 25
    assert BUYER.seed not in json.dumps(wallet)


def test_wallet_file_is_owner_only_and_reused(tmp_path):
    store = Store(tmp_path / "home")
    wallet, created = init_wallet(store, "unused", fund=False)
    path = tmp_path / "home" / "wallet.json"
    assert created and path.stat().st_mode & 0o777 == 0o600
    again, created = init_wallet(store, "unused", fund=False)
    assert not created and again.address == wallet.address
    assert load_wallet(store, env={}).address == wallet.address
    assert load_wallet(store, env={"SLIVER_WALLET_SEED": BUYER.seed}).address == BUYER.address


def test_a_wallet_file_readable_by_others_is_refused(tmp_path):
    store = Store(tmp_path / "home")
    init_wallet(store, "unused", fund=False)
    os.chmod(tmp_path / "home" / "wallet.json", 0o644)
    with pytest.raises(WalletMissing, match="chmod 600"):
        load_wallet(store, env={})


def test_a_failure_after_payment_is_not_reported_as_nothing_spent(server, tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("x")
    result = call(server, "sliver_buy", {"resource_id": CHEAP, "budget_usd": 5, "output_dir": str(blocked)})
    assert result["status"] == "paid_not_completed" and result["code"] == "save_failed"
    assert result["spent_usd"] == 1.5 and result["tx_hash"] and "spent" not in result


# --- custom slices (#39) ------------------------------------------------------------------


def test_quoting_a_custom_slice_never_spends_and_the_quote_is_bought_like_any_sliver(server, stub):
    quoted = call(
        server,
        "sliver_quote_slice",
        {"resource_id": FULL_BERTHS, "time_start": "2026-10-01", "time_end": "2026-10-10", "budget_usd": 1},
    )
    assert quoted["status"] == "quoted" and quoted["spent"] == 0
    assert quoted["resource_id"] == CUSTOM_ID and quoted["rows"] == 10 and quoted["price_usd"] == 0.24
    assert quoted["within_budget"] is True and quoted["new"] is True
    assert quoted["parent"]["id"] == FULL_BERTHS and "sliver_buy" in quoted["next"]
    assert quoted["summary"] == (
        "A custom slice of 'Singapore berth waiting times' by Harbour Analytics (demo seller): "
        "10 rows × 2 columns (date, avg_berth_wait_hours), covering date 2026-10-01 to 2026-10-10, "
        "for $0.24 (0.096 XRP on XRPL Testnet). Nothing has been spent; buy it only if your human agrees."
    )
    assert quoted["price_xrp"] == 0.096 and quoted["payment"]["amount_drops"] == "96000"
    assert quoted["columns"] == ["date", "avg_berth_wait_hours"] and quoted["column_count"] == 2
    assert quoted["parent"]["seller"] == "Harbour Analytics (demo seller)"
    assert quoted["validity"]["price_fixed"] is True and "warning" not in quoted
    assert "after they agree" in quoted["next"]
    assert dict(stub.quote_requests[0].url.params) == {"time_start": "2026-10-01", "time_end": "2026-10-10"}
    assert not stub.data_requests and not stub.payments  # quoting never touches the x402 path

    bought = call(server, "sliver_buy", {"resource_id": CUSTOM_ID, "budget_usd": 1})
    assert bought["status"] == "delivered" and bought["sha256_verified"] is True
    assert bought["pay_to"] == stub.pay_to and bought["price_usd"] == 0.24
    assert Path(bought["file"]).read_bytes() == CUSTOM_CSV


def test_a_custom_slice_is_still_bought_only_within_the_budget(server, stub):
    call(server, "sliver_quote_slice", {"resource_id": FULL_BERTHS, "time_start": "2026-10-01"})
    refused = call(server, "sliver_buy", {"resource_id": CUSTOM_ID, "budget_usd": 0.1})
    assert refused["status"] == "refused" and refused["code"] == "over_budget"
    assert call(server, "sliver_buy", {"resource_id": CUSTOM_ID})["code"] == "no_budget"
    assert not stub.payments


def test_quote_refusals_pass_the_servers_hints_through(server, stub):
    refused = call(server, "sliver_quote_slice", {"resource_id": "11111111-1111-4111-8111-111111111111",
                                                  "where": {"lane": "SGSIN-CNSHA"}})  # fmt: skip
    assert refused == {
        "status": "refused",
        "code": "use_full_dataset",
        "message": "Custom slices are cut from the full dataset.",
        "full_dataset_id": FULL_BERTHS,
        "spent": 0,
    }
    assert json.loads(stub.quote_requests[0].url.params["where"]) == {"lane": "SGSIN-CNSHA"}
    empty = call(server, "sliver_quote_slice", {"resource_id": FULL_BERTHS})
    assert empty["code"] == "empty_filter" and empty["filterable"]["min_rows"] == 5
    assert call(server, "sliver_quote_slice", {"resource_id": "../etc"})["code"] == "invalid_resource_id"
    assert not stub.payments


def test_evaluate_suggests_a_custom_slice_through_the_protocol(server):
    report = call(
        server,
        "sliver_evaluate",
        {"need": "singapore berth waiting times", "time_start": "2026-10-01", "time_end": "2026-10-10",
         "budget_usd": 5},
    )  # fmt: skip
    assert report["recommendation"] == "skip"  # the full dataset is over budget
    suggestion = report["custom_slice"]
    assert suggestion["tool"] == "sliver_quote_slice" and suggestion["resource_id"] == FULL_BERTHS
    assert (suggestion["time_start"], suggestion["time_end"]) == ("2026-10-01", "2026-10-10")
    assert "sliver_quote_slice" in report["summary"] and report["spent"] == 0


def test_a_quote_whose_xrp_amount_differs_from_the_local_rate_is_flagged(server, stub, config):
    stub.drops_per_usd = 1
    quoted = server_module.quote_summary(
        201,
        {"id": CUSTOM_ID, "row_count": 10, "price": {"amount_minor": 24}, "columns": [],
         "payment": {"amount_drops": "1"}},
        None,
        config.drops_per_usd,
    )  # fmt: skip
    assert "sliver_buy will refuse" in quoted["warning"]
    broken = server_module.quote_summary(200, {"id": CUSTOM_ID, "price": {"amount_minor": 0}}, None, 400_000)
    assert broken["status"] == "error" and broken["spent"] == 0


def test_instructions_require_the_humans_yes_before_buying_a_quote(server):
    text = " ".join(server.instructions.split())
    assert "ask whether it is worth it" in text and "only after your human says yes" in text
    assert "Sliver never decides to spend" in text
