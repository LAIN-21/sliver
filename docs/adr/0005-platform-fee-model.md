# ADR 0005: Platform fee recorded per sale, settled off-chain

## Context

Sliver's business model is now decided. Sellers list data for sale, and on every sale the seller gets paid and Sliver takes a cut. [ADR 0004](0004-x402-payments-on-xrpl.md) fixed how a sale is paid. The buyer's agent signs one standard x402 v2 `exact` XRPL Payment to the seller's address for the listed price. The facilitator settles it, and Sliver re-checks the ledger before delivering. Sliver never signs, never holds keys and never custodies funds. That ADR left "a marketplace fee out of scope for now".

The fee must therefore fit around a payment that goes in full from the buyer to the seller. Any design has to keep these properties:

- Sliver stays non-custodial: no funds pass through a Sliver account.
- Any standard x402 v2 XRPL client can still buy with one retried request. The 402 requirements, verification and the ledger re-check stay exactly as in ADR 0004.
- A rate change never rewrites the fee of a past sale.

XRPL amendment status, checked on 9 November 2026 against the validated `Amendments` ledger object on Testnet (`s.altnet.rippletest.net`, ledger 22,191,316) and Mainnet (`s1.ripple.com`, ledger 108,218,198):

- The original `Batch` amendment (XLS-56) is not enabled on either network, has no majority, and Mainnet servers report it as unsupported.
- Its replacement, `BatchV1_1`, is enabled on both Testnet and Mainnet.

## Decision

- **The fee is recorded per sale and settled off-chain.** The buyer still pays the full listed price to the seller's address with one standard x402 Payment. Nothing in the 402 challenge, verification, settlement or ledger re-check changes. `payTo` stays the seller, and the amount stays the listed price.
- **Rate.** `SLIVER_PLATFORM_FEE_BPS`, in basis points, defaults to 1000 (10%). It is bounded to 0–5000 and refused at startup outside those bounds.
- **Snapshot at sale time.** When a payment becomes `delivered`, the same database commit records the rate in force, Sliver's fee and the seller's net on the payment row. Amounts are stored in drops and in USD cents (`payments.platform_fee_bps`, `platform_fee_drops`, `seller_net_drops`, `platform_fee_minor`, `seller_net_minor`; migration `0008_platform_fee`). A recorded fee is never replaced, so replays and later rate changes leave it alone. Recording is bookkeeping only. If it ever failed, the sale would still be delivered and its fee left empty, with the error logged.
- **Integer math and rounding.** `fee = gross × bps ÷ 10,000`, rounded down to a whole drop and a whole cent, and `net = gross − fee`. So `fee + net = gross` exactly, and rounding always favours the seller. Drops and cents are rounded independently. A database check constraint enforces the cent identity.
- **No backfill.** Payments delivered before `0008_platform_fee` were sold under ADR 0004 without any fee. Their fee columns stay NULL, which means "no fee recorded". They owe Sliver nothing, and their net equals their gross.
- **Visibility.** The seller's insights show gross, fee and net per sale and in total, plus the fee owed to Sliver. All recorded fees count as owed until off-chain settlement exists. The pricing panel shows the seller's net at the current rate. The public receipt and purchase timeline state the split through an explicit allow-list: rate, fee and seller net, all derived from the public price. Public activity events are unchanged.

## Alternatives Considered

- **Sliver collects the payment and forwards the seller's share (custodial).** Rejected. It makes Sliver hold funds, which brings the custody and compliance burden ADR 0004 rejected. It also puts Sliver in the money path.
- **A second on-chain payment from the buyer to Sliver for the fee.** Rejected. Standard x402 `exact` asks for one Payment per request. A second payment breaks off-the-shelf x402 clients, needs a second signature and budget check in every buyer agent, and can half-succeed.
- **An XRPL-native atomic split in one Batch transaction.** Roadmap. Payment to the seller and fee to Sliver would be all-or-nothing, and Sliver would still hold nothing. `BatchV1_1` is enabled on Testnet and Mainnet (see Context), so the ledger can already do this. But the x402 `exact` XRPL scheme, the t54 facilitator and the ledger re-check all assume a single Payment. Adopting it needs a scheme or facilitator that settles a Batch, and buyer clients that sign one. It needs its own ADR.
- **The seller pays the fee to Sliver on-chain after each sale.** Rejected for now. It depends on the seller signing a transaction for every sale, and Sliver holds no seller keys. Periodic off-chain invoicing covers the same need with less machinery.

## Consequences

- Standard x402 buyers and the Sliver MCP are unaffected. The challenge, the amount and the payee are byte-for-byte what they were.
- There is an accounting trust gap until on-chain settlement exists. The fee is a ledger of claims, not money received. Sliver relies on sellers settling invoices, and sellers rely on Sliver's records. Each recorded fee points to its validated transaction, so either side can audit the gross. Invoicing, marking fees settled and dispute handling are not built yet.
- Rate changes need a restart and apply only to sales delivered afterwards.
- Refunds remain manual (ADR 0004). A refunded sale's recorded fee has to be cancelled by hand.
- When an on-chain split is adopted, a new ADR will supersede the off-chain settlement part of this one.

## Status

Accepted
