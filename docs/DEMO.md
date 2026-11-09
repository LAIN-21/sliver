# Demo video script (about 3 minutes)

The video follows one story: a seller lists and prices data, a buying agent in Claude Desktop declines what doesn't fit and buys what does within its human's budget, and the payment shows up live, in the seller's earnings and on the XRP Ledger. Each scene names the judging criteria it covers, so the cut can be checked against them.

> **Draft for team review.** See [Open questions](#open-questions-for-the-team).

## Before recording

Start from a freshly seeded stack so the timeline shows only the demo purchase.

1. On a fresh checkout, run `make install` first so `.env` is created from `.env.example` (don't create it by hand: `make` only copies the example when `.env` is missing). Set `SLIVER_SELLER_PASSWORD`, `SLIVER_REVIEWER_PASSWORD` and `ANTHROPIC_API_KEY` in `.env` (the dataset page should say "Written by Claude", not "offline fallback"). If earlier test purchases are on the timeline, run `make dev-reset` first; it deletes all local data. Then run `make dev-start`, `make seed` and `make wallets` (re-run `make wallets` after every reset, see [DEVELOPMENT.md](DEVELOPMENT.md#make-targets)).
2. Install the [Sliver MCP](../packages/sliver-mcp/README.md) in Claude Desktop with `"SLIVER_API_URL": "http://127.0.0.1:8000"`, and create the funded buyer wallet (the Claude Desktop setup doesn't put `sliver-mcp` on your shell's PATH, so use `uvx`):

   ```bash
   uvx --from "git+https://github.com/LAIN-21/sliver#subdirectory=packages/sliver-mcp" sliver-mcp wallet init
   ```

   If a wallet already exists, `wallet init` reuses it without funding it again. After rehearsals, run the same command with `wallet show` instead of `wallet init` and make sure the balance covers the purchase. Keep the default caps ($5 per purchase, $20 per day).
3. Prepare the seller CSV for scene 2. It must not duplicate a seeded dataset: the duplicates stage flags exact and near copies of published data and sends them to the reviewer. It should also be accepted automatically (quality score of at least 70, no blocking findings), because only an accepted dataset can be priced and published. Rehearse the upload once before the final `make dev-reset` to check this.
4. Open browser tabs: http://127.0.0.1:5173/sell/login, http://127.0.0.1:5173/activity, and https://testnet.xrpl.org. After signing in, open http://127.0.0.1:5173/sell/insights in a fourth tab; it updates live, so leave it open through scene 6.
5. **Never show `.env`, a wallet seed, `~/.sliver/wallet.json`, an API key or a password on screen.** Type the seller password off camera or blur it. `sliver_wallet` shows only the address and balance, so it is safe to show.
6. If you record a `make demo` run, check its step 3 output. "accepted automatically" is the normal case. If it prints that `reviewer@sliver.local` approved the upload, Claude's quality score was just under the auto-accept threshold with no blocking finding, and the demo's scripted reviewer account approved it. Either re-run `make demo` until it is accepted automatically, or narrate it as it happened (see scene 3).

## Shot list

| # | Time | Scene | On screen | Criteria |
|---|---|---|---|---|
| 1 | 0:00–0:15 | Problem | Title card, then the marketplace at http://127.0.0.1:5173 | Creativity |
| 2 | 0:15–0:40 | Seller upload | `/sell/upload`: choose CSV, title, provenance, rights confirmation, upload | Reachability, UX |
| 3 | 0:40–1:10 | Pipeline and Claude review | `/sell/datasets/{id}`: stages tick through, findings, "Written by Claude", packaged slivers with SHA-256, quality score and decision | Creativity (AI-native), Technical depth (safeguards) |
| 4 | 1:10–1:25 | Price and publish | Dataset page: suggested prices, Claude's explanation, "Why?" breakdown, one override, publish | Creativity (AI-native), Feasibility |
| 5 | 1:25–1:50 | Agent declines a miss | Claude Desktop: air-cargo question → `sliver_search`, `sliver_evaluate` → `look_elsewhere` | Technical depth (agents), Safeguards |
| 6 | 1:50–2:25 | Agent buys within budget | Claude Desktop: spot-rate question with a $5 budget → `sliver_evaluate` → `sliver_buy` → file, SHA-256 verified, tx hash | Creativity (x402), Technical depth (XRPL) |
| 7 | 2:25–2:45 | Live timeline and earnings | `/activity`, the purchase's `/purchases/{id}` page, then `/sell/insights` | UX, Feasibility |
| 8 | 2:45–3:00 | On chain | Explorer link from the timeline: Payment buyer → seller, `InvoiceID`, validated | Technical depth (XRPL), Feasibility |

## Scenes

### 1. Problem (0:00–0:15)

**On screen:** title card "Sliver: data for agents, paid on the XRP Ledger", then the marketplace page.

**Narration:** "AI agents need small, specific facts, but data is sold as whole datasets behind subscriptions and sign-ups. Sliver lets anyone sell data in slices that agents can find, check and pay for themselves on the XRP Ledger."

### 2. Seller upload (0:15–0:40)

**On screen:**

1. Sign in at `/sell/login` as `strait-line-data@sliver.local` (password typed off camera). This demo seller owns the seeded SGSIN-CNSHA sliver bought in scene 6, so its earnings appear in scene 7.
2. Go to `/sell/upload`. Choose the prepared CSV. Fill in title, source, method and collection date, tick the rights confirmation, and upload.

**Narration:** "A seller uploads a CSV with its provenance and confirms they have the rights to sell it. Nothing is public yet."

### 3. Pipeline and Claude review (0:40–1:10)

**On screen:** the dataset page polls as each stage finishes: validate, profile, privacy, duplicates, AI review, research (skipped unless enabled), package, decide. Pause on:

- the proposed public listing with "Written by Claude (model)";
- the packaged slivers, each with rows, size and SHA-256;
- the quality score and the decision (accepted, or waiting for a reviewer).

Optional 5-second cutaway: an earlier upload of `examples/seller/customer-contacts-pii.csv`, showing privacy findings that name columns and row numbers but never the values, and the dataset sent to the reviewer queue.

**Narration:** "A pipeline validates and profiles the table, scans it for personal data, and checks it against the catalog for duplicates. Then Claude writes the public listing and decides how to slice it. Claude only sees the schema, a profile and up to twenty redacted rows. It can send a dataset to a human reviewer, but it can never approve one. Each slice becomes its own file with its own hash."

If the recorded run was approved by the demo reviewer rather than accepted automatically, add: "Claude's score was just under the auto-accept threshold, so the reviewer account approved it, here scripted by `make demo`. An upload with a blocking privacy, duplicate or sensitivity finding can never be approved this way."

### 4. Price and publish (1:10–1:25)

**On screen:** scroll the dataset page to "Price and publish":

1. Pause on the suggested prices, their ranges and the explanation ("Explained by Claude (model)"; "Sliver's template" means no API key or a rejected answer).
2. Open "Why?" on one sliver: the base (comparables or category), then quality, uniqueness, demand, public availability and coverage, each with its reason.
3. Override one sliver's price, leave the rest at their suggestions, and publish. The panel switches to "Published prices" with listing links.

Don't tick sample rows unless the chosen CSV has none flagged; nothing is public unless the seller selects it.

**Narration:** "Sliver suggests a price for every slice with a fixed formula: comparable listings, quality, overlap with what's already for sale, unmet buyer demand, and coverage. Claude explains the numbers but never sets them. The seller accepts or overrides, and publishes."

### 5. The agent declines a miss (1:25–1:50)

**On screen:** Claude Desktop with the Sliver MCP connected. Type:

> Find air-cargo rates from Changi (SIN) to Frankfurt (FRA), with origin, destination and usd_per_kg columns. Budget $5.

Expand the tool calls: `sliver_search`, then `sliver_evaluate`. The recommendation is `look_elsewhere`, and Claude says Sliver doesn't have this data and spends nothing.

**Narration:** "This is the buyer's own agent, using the open-source Sliver MCP on the buyer's machine. Sliver doesn't have air-cargo rates, so the evaluation says look elsewhere, and the agent spends nothing rather than buying a near miss."

### 6. The agent buys within budget (1:50–2:25)

**On screen:** in the same chat, type:

> Find weekly container spot rates from Singapore to Shanghai since September. Budget $5.

Expand `sliver_evaluate` and check its arguments: a short `need` such as `weekly container spot rates Singapore to Shanghai`, with `time_start: "2026-09"` and `budget_usd: 5`. That gets `buy` for the SGSIN-CNSHA sliver ($1.50). If Claude passes the whole sentence as `need`, only 5 of its 11 terms appear in the listing (the evaluator needs 60%) and it answers `look_elsewhere`; rehearse, and if needed rephrase the prompt or name the arguments. Then `sliver_buy` with `budget_usd: 5`. Pause on the result: saved file path, SHA-256 verified, transaction hash and explorer link.

**Narration:** "This one fits, and it costs a dollar fifty, inside the five-dollar budget. The MCP checks that the payment request matches the listing, then signs an XRPL payment locally. It pays Sliver's platform wallet, which keeps a ten percent fee and pays the seller every fifteen days; Sliver never sees the buyer's keys. The bytes it receives match the listed hash. Without a budget, or over it, the MCP refuses before signing anything."

### 7. Live timeline and earnings (2:25–2:45)

**On screen:** switch to `/activity`. The purchase card is at the top. Open it to `/purchases/{id}` and scroll the steps as the page labels them: "402 Payment Required", "Signed payment received", "Verified by the facilitator", "Data integrity checked", "Submitted to the XRP Ledger", "Settled", "Validated on the ledger", "Data delivered", each with its time.

Then switch to the `/sell/insights` tab: without a reload, the Balance shows $1.35 owed to the seller with the next payout date, and the $1.50 purchase is under Earnings with Sliver's $0.15 fee and its transaction link.

**Narration:** "Every step of the x402 flow appears live: the 402 challenge, the signed payment, facilitator verification, Sliver's own integrity check, settlement, and Sliver's independent check of the ledger before it delivers. And the seller sees what Sliver owes them, and when it pays out, as soon as the sale lands."

### 8. On chain (2:45–3:00)

**On screen:** click the transaction link on the timeline. On testnet.xrpl.org, show the Payment from the buyer to Sliver's platform wallet, the delivered amount, the `InvoiceID` field and the validated result.

**Narration:** "And here it is on the XRP Ledger: a Payment from the agent's wallet to Sliver, bound to the invoice; Sliver pays the seller on the next payout. Sliver: data sold in slices to agents, settled with x402 on XRPL."

## Criteria coverage

| Criterion | Scenes |
|---|---|
| Reachability | 2, 5 (MCP in Claude Desktop) |
| Creativity: AI-native, Starter Kit, x402 | 1, 3, 4, 6 |
| Feasibility | 4, 7, 8 |
| Technical depth: XRPL, x402, agents, security, safeguards | 3, 5, 6, 8 |
| UX: agent actions, payments, on-chain | 3, 7, 8 |
| Builder feedback | Not in the video; see [BUILDER_FEEDBACK.md](BUILDER_FEEDBACK.md) |

## Open questions for the team

- **Scene 6 prompt:** settle the exact wording in rehearsal so Claude's `sliver_evaluate` call gets `buy` (see the scene).
- **Seller CSV for scene 2:** which dataset? It must not duplicate a seeded one, it should be accepted automatically, and it should slice into a few slivers. Its category also shapes scene 4: with at least two published comparables in the same category (the seeded freight rates, for example), the base comes from the catalog and the range is narrower; otherwise a fixed category base is used.
- **Explorer:** the timeline links to testnet.xrpl.org. Confirm that the `InvoiceID` field is easy to find on that page, or zoom in during editing.
- **Agent note:** the API accepts an `X-Sliver-Agent-Note` header and shows it on the timeline, but the Sliver MCP doesn't send one yet, so no note appears in scene 7.
- **Length:** the shot list adds up to 3:00 exactly. If the pipeline or settlement is slow on the day, speed up scenes 3 and 6 in editing rather than cutting scene 8.
