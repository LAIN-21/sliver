# ADR 0005: Sliver collects payments and pays sellers on a 15-day schedule

## Context

Sliver's business model is now decided. Sellers list data for sale; on every sale the seller gets paid and Sliver takes a cut. For the demo, the product owner chose the simplest version: when a person buys, Sliver keeps the money, and Sliver pays the seller every 15 days. Sellers see a panel with all the money Sliver owes them.

[ADR 0004](0004-x402-payments-on-xrpl.md) had buyers pay the seller's address directly, with Sliver never custodying funds, and left a marketplace fee out of scope. This ADR replaces that direct-to-seller, non-custodial part. Everything else in ADR 0004 still holds:

- x402 v2 `exact` on `xrpl:1` and the requirements format;
- the order of operations;
- the independent ledger re-check;
- one settlement per invoice;
- the facilitator;
- Testnet only;
- the USD-to-drops rate.

XRPL amendment status, checked on 9 November 2026 against the validated `Amendments` ledger object on Testnet (`s.altnet.rippletest.net`, ledger 22,191,316) and Mainnet (`s1.ripple.com`, ledger 108,218,198):

- The original `Batch` amendment (XLS-56) is not enabled on either network, has no majority, and Mainnet servers report it as unsupported.
- Its replacement, `BatchV1_1`, is enabled on both.

## Decision

- **Buyers pay Sliver.** The 402 `payTo` is Sliver's platform address (`SLIVER_PLATFORM_ADDRESS`). The amount stays the listed price at `DROPS_PER_USD`, and every other requirement is unchanged. The ledger re-check expects the platform address as the destination, because it always checks against the stored invoice's `payTo`. Without a platform address, purchases answer 503. A seller still needs an XRPL address to sell, because that is where payouts go.
- **Platform wallet.** `make wallets` creates a faucet-funded Testnet wallet for Sliver. It appends its seed to `.env` as `SLIVER_PLATFORM_SEED` (kept for future payouts) and its address as `SLIVER_PLATFORM_ADDRESS`. Compose passes only the address to the API and worker. The API never reads the platform seed and still never signs anything.
- **Fee and net, snapshotted per sale.** When a sale Sliver collected is delivered, the same database commit records the rate in force (`SLIVER_PLATFORM_FEE_BPS`, default 1000 = 10%, bounded 0–5000), Sliver's fee and the seller's net on the payment row. Amounts are stored in drops and USD cents (migration `0008_platform_fee`). Integer math: `fee = gross × bps ÷ 10,000`, rounded down to a whole drop and a whole cent, and `net = gross − fee`. So fee + net = gross exactly, and rounding favours the seller. A recorded fee is never replaced, so replays and later rate changes leave past sales alone. Recording is bookkeeping only: a failure is logged and never blocks delivery.
- **Payouts every 15 days.** Sliver owes each seller the nets of their delivered sales that are not yet paid out (`payments.seller_paid_out_at` is NULL). Payouts run on the 1st and 16th of each month (UTC) and cover everything owed at that time. The seller's insights show the balance owed, the next payout date, a per-sale breakdown with transaction links, and the payout history. **Payout execution is not built.** Nothing signs a payout yet, and `seller_paid_out_at` is the place to record one.
- **Earlier sales.** Payments delivered before this change, and invoices issued with the seller as `payTo`, were paid straight to the seller. They get no fee and are never owed: their fee columns stay NULL. No backfill.
- **Public views.** The receipt and purchase timeline state the split through an explicit allow-list: rate, Sliver's fee and the seller's net, all derived from the public price. Payout status is not public. Public activity events are unchanged.
- **Buyer MCP.** The buyer's MCP pins one payee per Sliver API (the platform address from the first challenge) instead of one per seller. It still refuses a challenge whose payee changes after that.

## Alternatives Considered

- **Keep direct-to-seller payments and record the fee as a claim settled off-chain.** This was implemented first and kept Sliver non-custodial. The product owner rejected it: sellers would have to pay Sliver, and the trust gap sits on Sliver's side.
- **A second on-chain payment from the buyer for the fee.** Rejected. Standard x402 `exact` has one Payment per request; a second payment breaks off-the-shelf clients and can half-succeed.
- **An XRPL-native atomic split in one Batch transaction.** Roadmap. Paying the seller's net and Sliver's fee all-or-nothing would remove custody again. `BatchV1_1` is enabled on Testnet and Mainnet, but the x402 `exact` XRPL scheme, the t54 facilitator and the ledger re-check all assume a single Payment. It needs its own ADR.
- **Paying out on every sale.** Rejected for the demo. It needs automated signing from the platform wallet on every purchase, which is more risk than a fixed schedule.

## Consequences

- **Custody.** Sliver now holds buyers' funds (Testnet XRP, no real value) between a sale and the next payout. Sellers must trust Sliver to pay. The balance panel and the per-sale transaction links let them check what they are owed.
- **The platform seed must be protected.** It controls every collected sale. Today it lives only in the gitignored `.env`, like the other Testnet seeds. It must never be logged, committed or passed to the API container. A real deployment needs a proper key store before payouts are automated.
- **Payouts are not automated.** Until a payout job exists, balances are paid by hand from the platform wallet, and nothing marks sales as paid out yet.
- **Compliance before Mainnet.** Holding and forwarding other people's money is regulated: money transmission, KYC/AML for sellers and buyers, tax reporting, and safeguarding of funds. That work, a custody design and a new ADR are required before any Mainnet use. Testnet only, as before.
- Standard x402 clients are unaffected apart from the payee. A client that pinned a seller's address will refuse the new payee until it trusts the platform address; the Sliver MCP has been updated.
- Refunds remain manual (ADR 0004), now from the platform wallet.

## Status

Accepted. Supersedes the direct-to-seller and non-custodial decision of [ADR 0004](0004-x402-payments-on-xrpl.md); the rest of ADR 0004 stands.
