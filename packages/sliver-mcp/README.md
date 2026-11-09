# sliver-mcp

Free, open-source MCP server that lets any agent search [Sliver](../../README.md), check whether a data sliver fits its need, and buy it with x402 on the XRP Ledger **Testnet**, within budget limits you set.

It is the buyer's own tool. It runs on your machine over stdio, signs payments locally with your Testnet wallet, and pays the seller directly. The seed never leaves your machine and Sliver never sees it. Sliver never decides to spend: your agent and you do.

## Tools

| Tool | What it does | Spends? |
|---|---|---|
| `sliver_search` | Search the catalog (public metadata only) | No |
| `sliver_inspect` | Full listing: columns, coverage, provenance, price, SHA-256 | No |
| `sliver_evaluate` | Deterministic fit report for a need: `buy`, `skip` or `look_elsewhere`, with reasons (required columns, time-range overlap, freshness, price vs budget) | No |
| `sliver_buy` | Buy one sliver within a budget, with an optional `reason`; saves the CSV, verifies its SHA-256, returns the transaction hash, explorer link and receipt | Yes (Testnet XRP) |
| `sliver_wallet` | Wallet address, Testnet balance, spend in the last 24 hours (never the seed) | No |
| `sliver_purchases` | Purchases made from this machine | No |

The server tells agents to evaluate before buying, to say so and look elsewhere when nothing fits, never to exceed the budget, and to ask their human when the best fit costs more.

### The agent's reason

`sliver_buy` takes an optional `reason`: a short, honest statement of why the human needs the data, for example "Weekly SGSIN-CNSHA spot rates since September to quote a shipment". The MCP sends it as the `X-Sliver-Agent-Note` header on both the request that gets the 402 challenge and the paid request, and Sliver shows it **publicly** on the live purchase timeline. Before sending, the MCP drops control and formatting characters, collapses whitespace, cuts it to 200 characters and encodes it as UTF-8; Sliver sanitizes it again. With no reason, no header is sent. Agents are told never to put wallet data, seeds, budgets or their human's private details in it.

## Spending policy

`sliver_buy` refuses, before anything is signed, when:

- no `budget_usd` is given, or the price exceeds it;
- the price exceeds the per-purchase cap or would push the last 24 hours over the daily cap;
- another purchase is in flight on this machine;
- the 402 challenge is not XRPL Testnet (`xrpl:1`) XRP, asks for an amount other than the listing's USD price converted at the disclosed rate (rounded up, as the Sliver API does), or a payee other than the seller's address pinned on your first purchase from that seller.

The signed Payment follows the official XRPL `exact` scheme and the t54 facilitator: `InvoiceID = SHA-256(invoiceId)`, `SourceTag` from the challenge, a bounded `LastLedgerSequence`, a capped fee, and no Memos, SendMax, DeliverMin, Paths or partial-payment flag. Delivered bytes that do not match the listing's SHA-256 are saved with an `.unverified` suffix and flagged. A payment that left your machine counts toward the daily cap even if delivery fails.

## Install

Requires [uv](https://docs.astral.sh/uv/) (Python 3.11 or newer is fetched automatically).

### 1. Create a Testnet wallet

```bash
uvx --from "git+https://github.com/LAIN-21/sliver#subdirectory=packages/sliver-mcp" sliver-mcp wallet init
```

This creates and faucet-funds an XRPL **Testnet** wallet in `~/.sliver/wallet.json` (mode 0600). Alternatively set `SLIVER_WALLET_SEED` in the MCP server's environment. `sliver-mcp wallet show` prints the address and balance.

### 2. Add the server to your agent

Claude Code:

```bash
claude mcp add sliver -- uvx --from "git+https://github.com/LAIN-21/sliver#subdirectory=packages/sliver-mcp" sliver-mcp
```

Add `-e SLIVER_API_URL=https://...` (and any setting below) before `--` to change the defaults.

Claude Desktop (`claude_desktop_config.json`) and Cursor (`~/.cursor/mcp.json` or `.cursor/mcp.json`) use the same JSON:

```json
{
  "mcpServers": {
    "sliver": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/LAIN-21/sliver#subdirectory=packages/sliver-mcp", "sliver-mcp"],
      "env": { "SLIVER_API_URL": "http://127.0.0.1:8000" }
    }
  }
}
```

If the app cannot find `uvx`, use its absolute path (`which uvx`).

Then ask your agent something like: "Find weekly container spot rates from Singapore to Shanghai since September. Budget $5."

## Settings

All optional, read from the server's environment.

| Variable | Default | Meaning |
|---|---|---|
| `SLIVER_API_URL` | `http://127.0.0.1:8000` | Sliver API |
| `SLIVER_WALLET_SEED` | unset | Testnet seed; otherwise `~/.sliver/wallet.json` |
| `SLIVER_HOME` | `~/.sliver` | Wallet, spend ledger (`purchases.json`), pinned payees (`payees.json`) |
| `SLIVER_OUTPUT_DIR` | `~/.sliver/data` | Where purchased CSVs are saved |
| `SLIVER_MAX_PURCHASE_USD` | `5` | Per-purchase cap |
| `SLIVER_DAILY_CAP_USD` | `20` | Cap over the last 24 hours |
| `SLIVER_DROPS_PER_USD` | `400000` | Sliver's disclosed demo rate (1 USD = 0.4 XRP) |
| `SLIVER_MAX_FEE_DROPS` | `1000` | Network fee cap per payment |
| `SLIVER_XRPL_RPC_URL` | `https://s.altnet.rippletest.net:51234/` | Testnet only: also `https://clio.altnet.rippletest.net:51234/`, `https://testnet.xrpl-labs.com/` |

## Development

The package lives in a uv workspace with [sliver-x402](../sliver-x402), the small x402 client it signs with (the official `x402-xrpl` SDK pins `uvicorn<0.31`, which conflicts with the `mcp` SDK).

```bash
cd packages
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest
```

Tests use a stub Sliver API and a stub facilitator; nothing touches the network.
