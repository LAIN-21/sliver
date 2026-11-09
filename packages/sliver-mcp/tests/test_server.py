"""End to end through the MCP protocol: an in-process MCP client drives the server's tools
against the stub Sliver API and stub facilitator."""

import asyncio
import json
import os
from pathlib import Path

import pytest
from mcp import Client

from conftest import BUYER
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
