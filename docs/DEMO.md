# Demo video script (about 3 minutes)

The video follows one story: a seller lists data, a buying agent in Claude Desktop declines what doesn't fit and buys what does within its human's budget, and the payment shows up live and on the XRP Ledger. Each scene names the judging criteria it covers, so the cut can be checked against them.

> **Draft for team review.** Scene 4 (publish) depends on #15 (valuation and publication), which has not merged yet. Until it does, the buyer scenes use the seeded catalog. See [Open questions](#open-questions-for-the-team).

## Before recording

Start from a freshly seeded stack so the timeline shows only the demo purchase.

1. Set `SLIVER_SELLER_PASSWORD`, `SLIVER_REVIEWER_PASSWORD` and `ANTHROPIC_API_KEY` in `.env` (the dataset page should say "Written by Claude", not "offline fallback"). If earlier test purchases are on the timeline, run `make dev-reset` first; it deletes all local data. Then run `make dev-start`, `make seed` and `make wallets` (re-run `make wallets` after every reset, see [DEVELOPMENT.md](DEVELOPMENT.md#make-targets)).
2. Install the [Sliver MCP](../packages/sliver-mcp/README.md) in Claude Desktop with `"SLIVER_API_URL": "http://127.0.0.1:8000"`, and run `sliver-mcp wallet init` so the buyer wallet is funded. Keep the default caps ($5 per purchase, $20 per day).
3. Prepare the seller CSV for scene 2. It must not duplicate a seeded dataset: the duplicates stage flags exact and near copies of published data and sends them to the reviewer.
4. Open browser tabs: http://127.0.0.1:5173/sell/login, http://127.0.0.1:5173/activity, and https://testnet.xrpl.org.
5. **Never show `.env`, a wallet seed, `~/.sliver/wallet.json`, an API key or a password on screen.** Type the seller password off camera or blur it. `sliver_wallet` shows only the address and balance, so it is safe to show.

## Shot list

| # | Time | Scene | On screen | Criteria |
|---|---|---|---|---|
| 1 | 0:00–0:15 | Problem | Title card, then the marketplace at http://127.0.0.1:5173 | Creativity |
| 2 | 0:15–0:40 | Seller upload | `/sell/upload`: choose CSV, title, provenance, rights confirmation, upload | Reachability, UX |
| 3 | 0:40–1:10 | Pipeline and Claude review | `/sell/datasets/{id}`: stages tick through, findings, "Written by Claude", packaged slivers with SHA-256, quality score and decision | Creativity (AI-native), Technical depth (safeguards) |
| 4 | 1:10–1:25 | Publish *(pending #15)* | Seller report: suggested price, accept, publish | Feasibility |
| 5 | 1:25–1:50 | Agent declines a miss | Claude Desktop: air-cargo question → `sliver_search`, `sliver_evaluate` → `look_elsewhere` | Technical depth (agents), Safeguards |
| 6 | 1:50–2:25 | Agent buys within budget | Claude Desktop: spot-rate question with a $5 budget → `sliver_evaluate` → `sliver_buy` → file, SHA-256 verified, tx hash | Creativity (x402), Technical depth (XRPL) |
| 7 | 2:25–2:45 | Live timeline | `/activity`, then the purchase's `/purchases/{id}` page | UX |
| 8 | 2:45–3:00 | On chain | Explorer link from the timeline: Payment buyer → seller, `InvoiceID`, validated | Technical depth (XRPL), Feasibility |

## Scenes

### 1. Problem (0:00–0:15)

**On screen:** title card "Sliver: data for agents, paid on the XRP Ledger", then the marketplace page.

**Narration:** "AI agents need small, specific facts, but data is sold as whole datasets behind subscriptions and sign-ups. Sliver lets anyone sell data in slices that agents can find, check and pay for themselves on the XRP Ledger."

### 2. Seller upload (0:15–0:40)

**On screen:**

1. Sign in at `/sell/login` as `harbour-analytics@sliver.local` (password typed off camera).
2. Go to `/sell/upload`. Choose the prepared CSV. Fill in title, source, method and collection date, tick the rights confirmation, and upload.

**Narration:** "A seller uploads a CSV with its provenance and confirms they have the rights to sell it. Nothing is public yet."

### 3. Pipeline and Claude review (0:40–1:10)

**On screen:** the dataset page polls as each stage finishes: validate, profile, privacy, duplicates, AI review, research (skipped unless enabled), package, decide. Pause on:

- the proposed public listing with "Written by Claude (model)";
- the packaged slivers, each with rows, size and SHA-256;
- the quality score and the decision (accepted, or waiting for a reviewer).

Optional 5-second cutaway: an earlier upload of `examples/seller/customer-contacts-pii.csv`, showing privacy findings that name columns and row numbers but never the values, and the dataset sent to the reviewer queue.

**Narration:** "A pipeline validates and profiles the table, scans it for personal data, and checks it against the catalog for duplicates. Then Claude writes the public listing and decides how to slice it. Claude only sees the schema, a profile and up to twenty redacted rows. It can send a dataset to a human reviewer, but it can never approve one. Each slice becomes its own file with its own hash."

### 4. Publish (1:10–1:25), pending #15

**On screen (once #15 merges):** the seller report with the suggested price and its breakdown, accept the price, publish. The slivers appear in the marketplace.

**Narration:** "The seller reviews a suggested price, accepts it, and publishes. Agents can now buy each slice."

**Until #15 merges:** cut this scene and say instead, over the marketplace page: "These slices are already live in the catalog." Then buy from the seeded catalog in scenes 5–6.

### 5. The agent declines a miss (1:25–1:50)

**On screen:** Claude Desktop with the Sliver MCP connected. Type:

> Find air-cargo rates from Changi (SIN) to Frankfurt (FRA), with origin, destination and usd_per_kg columns. Budget $5.

Expand the tool calls: `sliver_search`, then `sliver_evaluate`. The recommendation is `look_elsewhere`, and Claude says Sliver doesn't have this data and spends nothing.

**Narration:** "This is the buyer's own agent, using the open-source Sliver MCP on the buyer's machine. Sliver doesn't have air-cargo rates, so the evaluation says look elsewhere, and the agent spends nothing rather than buying a near miss."

### 6. The agent buys within budget (1:50–2:25)

**On screen:** in the same chat, type:

> Find weekly container spot rates from Singapore to Shanghai since September. Budget $5.

Show `sliver_evaluate` recommending `buy` for the SGSIN-CNSHA sliver ($1.50), then `sliver_buy` with `budget_usd: 5`. Pause on the result: saved file path, SHA-256 verified, transaction hash and explorer link.

**Narration:** "This one fits, and it costs a dollar fifty, inside the five-dollar budget. The MCP checks that the payment request matches the listing, then signs an XRPL payment locally. It pays the seller directly; Sliver never holds the money or the keys. The bytes it receives match the listed hash. Without a budget, or over it, the MCP refuses before signing anything."

### 7. Live timeline (2:25–2:45)

**On screen:** switch to `/activity`. The purchase card is at the top. Open it to `/purchases/{id}` and scroll the steps as the page labels them: "402 Payment Required", "Signed payment received", "Verified by the facilitator", "Data integrity checked", "Submitted to the XRP Ledger", "Settled", "Validated on the ledger", "Data delivered", each with its time.

**Narration:** "Every step of the x402 flow appears live: the 402 challenge, the signed payment, facilitator verification, Sliver's own integrity check, settlement, and Sliver's independent check of the ledger before it delivers."

### 8. On chain (2:45–3:00)

**On screen:** click the transaction link on the timeline. On testnet.xrpl.org, show the Payment from the buyer to the seller, the delivered amount, the `InvoiceID` field and the validated result.

**Narration:** "And here it is on the XRP Ledger: a Payment from the agent's wallet straight to the seller, bound to the invoice. Sliver: data sold in slices to agents, settled with x402 on XRPL."

## Criteria coverage

| Criterion | Scenes |
|---|---|
| Reachability | 2, 5 (MCP in Claude Desktop) |
| Creativity: AI-native, Starter Kit, x402 | 1, 3, 6 |
| Feasibility | 4, 8 |
| Technical depth: XRPL, x402, agents, security, safeguards | 3, 5, 6, 8 |
| UX: agent actions, payments, on-chain | 3, 7, 8 |
| Builder feedback | Not in the video; see [BUILDER_FEEDBACK.md](BUILDER_FEEDBACK.md) |

## Open questions for the team

- **Scene 4:** keep it, or replace it with a seeded-catalog line, depending on whether #15 merges before recording.
- **Seller CSV for scene 2:** which dataset? It must not duplicate a seeded one, and it should slice into a few slivers.
- **Explorer:** the timeline links to testnet.xrpl.org. Confirm that the `InvoiceID` field is easy to find on that page, or zoom in during editing.
- **Agent note:** the API accepts an `X-Sliver-Agent-Note` header and shows it on the timeline, but the Sliver MCP doesn't send one yet, so no note appears in scene 7.
- **Length:** the shot list adds up to 3:00 exactly. If the pipeline or settlement is slow on the day, speed up scenes 3 and 6 in editing rather than cutting scene 8.
