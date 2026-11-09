# ADR 0004: x402 payments on the XRP Ledger

## Context

Resources must be purchasable by external AI agents without accounts or API keys, and Sliver must never decide to spend buyer funds ([PRODUCT.md](../PRODUCT.md)). [ARCHITECTURE.md](../ARCHITECTURE.md) left the x402 and XRPL integration open until a transaction ADR.

Facts that shape the decision (checked in November 2026):

- XRPL support for x402 exists only in x402 v2: headers `PAYMENT-REQUIRED`, `PAYMENT-SIGNATURE`, `PAYMENT-RESPONSE`; CAIP-2 network ids (`xrpl:1` is Testnet); the `exact` scheme carries a presigned XRPL Payment (`signedTxBlob`) that the facilitator submits.
- t54 contributed XRPL x402 support to the XRPL AI Starter Kit: the `x402-xrpl` Python SDK and a hosted Testnet facilitator (`https://xrpl-facilitator-testnet.t54.ai`, best effort, no SLA). The team's SingHacks prototype used them for real Testnet payments.
- The official x402 spec (`scheme_exact_xrpl.md`) and t54 differ: the spec allows only `InvoiceID = SHA-256(invoiceId)` binding and rejects memos, while t54 requires `extra.sourceTag`. The official open-source facilitator runs at `https://x402.org/facilitator`.

## Decision

- **Protocol:** `GET /api/resources/{id}/data` answers HTTP 402 with x402 v2 `PAYMENT-REQUIRED` (also as the JSON body). Requirements: `exact`, `xrpl:1`, asset `XRP` in drops, `payTo` = the seller's address, a fresh `extra.invoiceId` per challenge, `extra.sourceTag`, `extra.areFeesSponsored: false`, `maxTimeoutSeconds` 600. They satisfy both t54 and the official spec.
- **Direct-to-seller settlement:** buyers pay the seller's XRPL address. Sliver never signs, never holds buyer keys and never custodies funds. A marketplace fee is out of scope for now.
- **Order of operations:** match the stored invoice (the payment must accept the issued requirements unchanged) → facilitator `/verify` → read the Resource object and check its SHA-256 → facilitator `/settle` → independent ledger re-check → deliver. Money only moves when the exact bytes can be delivered.
- **Independent ledger re-check:** Sliver does not take the facilitator's word. The transaction must be validated, `tesSUCCESS`, a Payment to `payTo`, with `delivered_amount` exactly equal to the invoice amount, no partial-payment flag, and `InvoiceID = SHA-256(invoiceId)`.
- **One settlement per invoice, one invoice per transaction:** invoices are rows in `payments`; `tx_hash` is unique. Replaying the same payment re-delivers without settling again; a different transaction for a paid invoice is rejected (409). If the settlement outcome is unknown, the retry reconciles from the ledger instead of settling again.
- **Facilitator:** t54 Testnet by default (`FACILITATOR_URL`); the official x402.org facilitator is a drop-in fallback, verified compatible by `make smoke-testnet`.
- **Testnet only:** `xrpl:1` and an allow-list of Testnet RPC endpoints are enforced by configuration; mainnet is refused.
- **Pricing:** Resources are priced in USD cents and converted to drops at a disclosed fixed demo rate (`DROPS_PER_USD`, default 400,000 drops per USD). RLUSD pricing is a possible later step.

## Alternatives Considered

- **Verifying a buyer-submitted transaction hash** (the closed #9 approach): not x402, the buyer pays before Sliver can guarantee delivery, and a stuck hash can lock an invoice.
- **Marketplace-held funds with payouts:** adds custody and compliance burden; direct payment keeps Sliver non-custodial.
- **Running our own facilitator:** more to operate and secure; two public facilitators already exist and are interchangeable here.
- **Memo invoice binding:** rejected by the official spec.

## Consequences

- Any x402 v2 XRPL client (t54's SDK, the Sliver MCP, other agents) can buy a Resource with one retried HTTP request.
- Availability depends on a hosted Testnet facilitator; the fallback is one setting.
- A transaction that settles but fails the ledger re-check marks the invoice `failed` for reconciliation and delivers nothing; refunds are a manual, out-of-band process for now.
- The USD-to-XRP rate is illustrative, not a market price.

## Status

Accepted
