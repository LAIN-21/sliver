# Demo video script (about 3 minutes)

The video tells one story. A founder asks their own AI for real work and never mentions Sliver. The agent researches public sources, notices what they don't have, finds it on Sliver, quotes exactly the slice it needs, asks its human "I found data worth buying: $X for N rows × M columns, agree?", pays over x402 on XRPL Testnet after the yes, and writes the estimate from the data. Then the camera follows the money: the live payment timeline, the seller's balance, and the Payment to Sliver's wallet on the ledger.

The pitch in one line: **buy only the slice you need**, data you couldn't otherwise get or would have to buy as a whole bundle. The buyer pays Sliver's platform wallet; Sliver keeps its 10% fee and pays the seller every 15 days.

> **Draft for team review.** The numbers in this script come from a rehearsal run (see [Rehearsal facts](#rehearsal-facts)). See also [Open questions](#open-questions-for-the-team).

## Rehearsal facts

From a rehearsal run on 9 November 2026: an isolated stack on this branch, freshly seeded with `make seed` (34 slivers), quoted with the MCP's own evaluator and quote code. The full tables and the slices are the seeded synthetic data in [`examples/datasets`](../examples/datasets), so the same quotes come back on any freshly seeded stack. Resource ids differ per stack.

| Need | `sliver_evaluate` arguments | What it says | `sliver_quote_slice` arguments | Quote |
|---|---|---|---|---|
| Volumes near Tuas | `need: "Singapore port container throughput Tuas"`, `time_start: "2025-11"`, `time_end: "2026-10"`, `budget_usd: 5` | `buy` "Singapore port container throughput: Tuas" ($2.50, 24 months), and a custom slice is suggested because the need is half of what that sliver covers | the full "Singapore port container throughput" table, `time_start: "2025-11"`, `time_end: "2026-10"`, `where: {"terminal": "Tuas"}` | **12 rows × 8 columns for $0.90** (0.36 XRP), seller Harbour Analytics |
| Operating costs now | `need: "Singapore port logistics operating costs"`, `time_start: "2026-08"`, `time_end: "2026-10"`, `budget_usd: 5` | `buy` one $3.00 cost-category sliver (all six tie), and a custom slice of the whole table is suggested, keeping every category | the full "Singapore port-business operating costs" table, `time_start: "2026-08"`, `time_end: "2026-10"`, no `where` | **69 rows × 7 columns for $1.25** (0.5 XRP), seller Strait Line Data |

Together: **$2.15** instead of $19.00 for both full tables ($9.00 + $10.00), or $20.50 for the Tuas sliver plus all six cost-category slivers. Sliver records a 10% fee on each sale (rounded down, in the seller's favour): Strait Line Data is credited $1.13 net of $0.12, Harbour Analytics $0.81 net of $0.09.

`make demo` buys the same operating-cost slice for the same price on Testnet; its last run is in the README's [Testnet transactions](../README.md#testnet-transactions-from-make-demo).

## Before recording

Record after this branch is merged: the custom-slice suggestions above rely on the evaluator changes in it, and the MCP installs from `main`.

1. **Reset and seed.** On the recording machine: `make dev-reset` (it deletes all local data, so the timeline and balances show only the demo), then `make dev-start`, `make seed` and `make wallets` (re-run `make wallets` after every reset, see [DEVELOPMENT.md](DEVELOPMENT.md#make-targets)). Don't run `make demo` on this stack after the reset: its purchases would show up in the balances and on the timeline. `.env` needs `SLIVER_SELLER_PASSWORD` for the insights scene; `ANTHROPIC_API_KEY` is not needed, because nothing is uploaded in the video.
2. **Refresh the MCP in Claude Desktop.** `uvx` caches the git install, so a stale copy may not have `sliver_quote_slice` or the latest evaluator. Run this once, then fully quit Claude Desktop (Cmd+Q) and reopen it:

   ```bash
   uvx --refresh --from "git+https://github.com/LAIN-21/sliver#subdirectory=packages/sliver-mcp" sliver-mcp wallet show
   ```

   In Claude Desktop's connector settings, `sliver` must list seven tools, including `sliver_quote_slice`. Its config needs `"SLIVER_API_URL": "http://127.0.0.1:8000"` ([MCP README](../packages/sliver-mcp/README.md#install)). `wallet show` prints the buyer address and balance; it must cover $2.15 (0.86 XRP) plus fees. If there is no wallet yet, run the same command with `wallet init`.
3. **Give the agent its standing permission.** Create a Claude Desktop project for the founder with web search on and these project instructions (not shown in the video, but show them if asked):

   > You have a Testnet data wallet through the Sliver tools. When public sources don't have the data you need, you may look for it there. Before buying anything, tell me what you found, the price and what it covers, and wait for my yes. Never spend more than $5 on one purchase.

   This is the "agent already has a wallet and spending permission" premise; the human's prompt itself never mentions Sliver. Keep the MCP's default caps ($5 per purchase, $20 per day).
4. **Open tabs:** http://127.0.0.1:5173/activity; http://127.0.0.1:5173/sell/insights signed in as `strait-line-data@sliver.local` (seller of the operating-cost table; type the password off camera); and the platform wallet's account page, https://testnet.xrpl.org/accounts/ followed by `SLIVER_PLATFORM_ADDRESS`. To get that address without opening `.env`, run `grep '^SLIVER_PLATFORM_ADDRESS=' .env` in a terminal that is not being recorded; it prints only the public address.
5. **Never show secrets:** not `.env`, not a seed (`SLIVER_*_SEED`), not `~/.sliver/wallet.json`, not an API key or password. Addresses, transaction hashes and `sliver_wallet` output are public and safe to show.
6. **Rehearse the chat once,** then reset again (step 1). Check that Claude's `sliver_evaluate` and `sliver_quote_slice` arguments match [Rehearsal facts](#rehearsal-facts). Claude chooses its own arguments; if it asks for a different period or filter, the rows and price change with it, and the narration should follow what is on screen.

## The opening prompt

Type exactly:

> I'm planning to start a port logistics company in Singapore, probably near the new Tuas terminal. How expensive could it be to run, given the container volumes we could expect and today's operating costs? Research it and give me a one-page estimate with your sources.

## Shot list

| # | Time | Scene | On screen | Criteria |
|---|---|---|---|---|
| 1 | 0:00–0:12 | Hook | Title card, then Claude Desktop | Creativity |
| 2 | 0:12–0:25 | The ask | The opening prompt is typed and sent | UX (agent actions) |
| 3 | 0:25–0:45 | Public research | Claude's web searches and what it finds | Creativity (AI-native) |
| 4 | 0:45–1:20 | Finds and quotes on Sliver | `sliver_search`, `sliver_evaluate`, two `sliver_quote_slice` calls | Creativity (AI-native), Technical depth (agents) |
| 5 | 1:20–1:35 | The human says yes | Claude's quote message, the reply "Yes, go ahead." | UX (agent actions), Safeguards |
| 6 | 1:35–2:00 | Pays over x402 | Two `sliver_buy` calls; cut to the live `/activity` timeline and one `/purchases/{id}` page | Creativity (Starter Kit + x402), Technical depth (XRPL, x402), UX (payments) |
| 7 | 2:00–2:20 | The estimate | Claude's one-page estimate (or dashboard) built from the bought rows | Feasibility, UX |
| 8 | 2:20–2:40 | The seller gets paid | `/sell/insights`: the sale, Sliver's fee, the net, the balance and next payout date | Feasibility |
| 9 | 2:40–3:00 | On chain | testnet.xrpl.org: the Payment from the agent's wallet to Sliver's platform wallet | Technical depth (XRPL), UX (on-chain) |

## Scenes

### 1. Hook (0:00–0:12)

**On screen:** title card "Sliver: buy only the slice of data you need", then Claude Desktop.

**Narration:** "AI agents do real research now, and they hit the same wall people do: the data they need is sold as whole datasets, behind subscriptions and sign-ups. Sliver sells it in slices that agents can find, check and pay for themselves, on the XRP Ledger."

### 2. The ask (0:12–0:25)

**On screen:** the founder's project in Claude Desktop. Type [the opening prompt](#the-opening-prompt) and send it.

**Narration:** "Here's a founder thinking about a port logistics company in Singapore. They ask their own AI the real question. They don't mention Sliver or any data source."

### 3. Public research (0:25–0:45)

**On screen:** Claude's web searches. It finds public, port-wide figures (annual container throughput, general guides to setting up a company) but no monthly volumes by terminal and no current cost benchmarks for terminal handling, port dues, warehouse rent, trucking, labour and customs brokerage. Speed this up in editing.

**What the agent should do:** say what public sources cover and what is missing, then decide to look for the missing data with its Sliver tools.

**Narration:** "It starts with public sources. They give the big picture, but not what an estimate needs: volumes at the terminal it would use, and what things cost today."

### 4. Finds and quotes on Sliver (0:45–1:20)

**On screen:** expand the tool calls as they run.

1. `sliver_search` for port throughput and operating costs: two seeded tables from two demo sellers, each also sold as pre-cut slivers (one per terminal, one per cost category).
2. `sliver_evaluate` for each need, with the arguments in [Rehearsal facts](#rehearsal-facts). Pause on one result: the recommendation, the reasons and the `custom_slice` suggestion ("It covers much more than the need: a custom slice … may cost less").
3. `sliver_quote_slice` twice. Pause on a quote: rows × columns, the price in USD and XRP, the coverage, the SHA-256, and `spent: 0`.

**What the agent should do:** quote only what the estimate needs, the last 12 months at Tuas and the last three months of every cost category, and spend nothing yet.

**Narration:** "The agent finds the missing data on Sliver. It doesn't buy whole tables: Sliver's evaluator says a custom slice fits better, so the agent asks for a quote on exactly the rows it needs, the last twelve months at Tuas and the last three months of operating costs. Quoting is free; Sliver cuts the rows, prices them per row from the seller's price, and hashes them. Nothing has been spent."

### 5. The human says yes (1:20–1:35)

**On screen:** Claude's message. From the rehearsal, it should read close to:

> I found data worth buying on Sliver, a data marketplace:
> 1. Tuas terminal container throughput, November 2025 to October 2026: **12 rows × 8 columns for $0.90** (0.36 XRP).
> 2. Singapore port-business operating costs, all six categories, August to October 2026: **69 rows × 7 columns for $1.25** (0.5 XRP).
>
> That's $2.15 in total on XRPL Testnet, instead of $19 for both full tables. Shall I buy them?

Type: **Yes, go ahead.**

**Narration:** "Then it asks. Two dollars fifteen for exactly these rows, instead of nineteen dollars for the full tables. The agent has a wallet and a spending limit, but the decision is the human's, and Sliver never spends on anyone's behalf."

### 6. Pays over x402 (1:35–2:00)

**On screen:**

1. Two `sliver_buy` calls, each with the quote's `resource_id`, a `budget_usd` no higher than what the human approved, and a short `reason`. Pause on one result: `pay_to` (Sliver's platform wallet), the saved file, `sha256_verified: true`, the transaction hash and explorer link.
2. Cut to `/activity`: the two purchases arrive live, with the agent's reason. Open one to `/purchases/{id}` and scroll its steps: "402 Payment Required", "Signed payment received", "Verified by the facilitator", "Data integrity checked", "Submitted to the XRP Ledger", "Settled", "Validated on the ledger", "Data delivered", and the split: Sliver's 10% fee and the seller's net.

**Narration:** "Each purchase is one standard x402 payment. Sliver answers with a 402; the agent's MCP checks the request against the quote, signs an XRPL payment locally with its own key, and pays Sliver's wallet. A facilitator from the XRPL AI Starter Kit settles it, and Sliver checks the ledger itself before it delivers the bytes, which match the quoted hash. Every step shows up live."

### 7. The estimate (2:00–2:20)

**On screen:** Claude's one-page estimate (or an artifact dashboard): expected volumes from the Tuas rows, monthly running costs from the cost rows (warehouse rent, trucking, labour, terminal handling, port dues, customs brokerage), with sources: the public pages it read and the two Sliver slices with their transaction hashes. Caption: "Demo data is synthetic."

**Narration:** "And it does the work it was asked for: an estimate built from public sources and from the rows it bought, with every source cited, down to the transaction."

### 8. The seller gets paid (2:20–2:40)

**On screen:** the `/sell/insights` tab (Strait Line Data), updated without a reload: the $1.25 sale tagged "custom slice", Sliver's $0.12 fee, the $1.13 net, the balance owed and the next payout date (the 1st or 16th, UTC).

**Narration:** "On the other side, the seller sees the sale as it lands: what the buyer paid, Sliver's ten percent, and what Sliver owes them at the next payout, every fifteen days. They published one table; Sliver sold the slice a buyer needed."

### 9. On chain (2:40–3:00)

**On screen:** the platform wallet's page on testnet.xrpl.org (or the explorer link from the purchase timeline): the Payment from the agent's wallet to Sliver's platform wallet, the delivered amount, the `InvoiceID` field and the validated result.

**Narration:** "And here it is on the XRP Ledger: a validated payment from the agent's wallet to Sliver, bound to the invoice. Sliver: buy only the slice you need, settled with x402 on XRPL."

### Optional: the agent declines a miss (cut if over time)

If there is time, or as a separate short clip: ask "Find air-cargo rates from Changi (SIN) to Frankfurt (FRA) per kg. Budget $5." `sliver_evaluate` answers `look_elsewhere` and the agent says Sliver doesn't have it and spends nothing. `make demo` runs the same check on every run.

## Criteria coverage

| Criterion | Scenes |
|---|---|
| Reachability | 2–6: an off-the-shelf agent (Claude Desktop) with the open-source MCP; no Sliver account, API key or sign-up |
| Creativity: AI-native | 3, 4, 7: the agent decides it needs data, evaluates fit and quotes a custom slice; Sliver cuts and prices the slice on request |
| Creativity: XRPL AI Starter Kit + x402 | 6: x402 v2 `exact` on XRPL Testnet, settled through t54's Starter Kit facilitator |
| Feasibility | 5, 8: a $2.15 sale instead of a $19 bundle, a 10% platform fee, seller payouts every 15 days |
| Technical depth: XRPL, x402, agents, safeguards | 4, 6, 9: challenge checked before signing, local signing, SHA-256 check, Sliver's independent ledger re-check, `InvoiceID` binding |
| UX: agent actions, payments, on-chain | 5, 6, 8, 9: the quote and the human's yes, the live timeline, the seller's balance, the explorer |
| Builder feedback | Not in the video; see [BUILDER_FEEDBACK.md](BUILDER_FEEDBACK.md) |

## What the product does not do yet

Say these plainly if asked, and don't imply otherwise on screen:

- **Payouts are not automated.** The seller's balance and next payout date are real records, but nothing pays sellers out yet; it would be done by hand from the platform wallet ([ADR 0005](adr/0005-platform-collection-and-payouts.md)).
- **Sliver holds the funds between a sale and the payout** (Testnet XRP only). Mainnet would need custody, KYC/AML and money-transmission work first.
- **The data is synthetic,** including the port throughput and operating costs.
- **The agent's spending permission is its own setting,** the MCP's budget and caps plus the project instructions. Sliver has no buyer accounts and never decides to spend.
- **Claude chooses its own tool arguments.** The rehearsal numbers hold for the arguments above; other periods or filters give other prices.

## Open questions for the team

- **Scene 3:** which public sources Claude actually cites varies. Rehearse and keep whatever it finds, as long as the narration doesn't claim specific numbers.
- **Scene 7:** a written one-page estimate or an artifact dashboard? A dashboard is more visual but takes longer to generate; speed it up in editing.
- **Explorer:** confirm that the `InvoiceID` field is easy to find on testnet.xrpl.org, or zoom in during editing.
- **Length:** the shot list adds up to 3:00. If settlement or Claude is slow on the day, speed up scenes 3, 4 and 6 in editing rather than cutting scene 9.
