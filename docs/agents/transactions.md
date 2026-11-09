# Transactions

Additional constraints for payments (`apps/api/sliver_api/payments`) and the buyer-side client (`packages/sliver-x402`, `packages/sliver-mcp`). Repository-wide rules in [AGENTS.md](../../AGENTS.md) still apply. The design is in [ADR 0004](../adr/0004-x402-payments-on-xrpl.md).

- Sliver never signs transactions, never stores or reads buyer keys, and never custodies funds. Buyers pay sellers directly.
- Never implement spending on a buyer's behalf on the server. Spending decisions belong to the buyer's agent and its human.
- Testnet only (`xrpl:1`). Do not add mainnet configuration, endpoints or keys.
- Never deliver data unless the ledger re-check in `ledger_check.py` passes. Never settle before the stored object passes its SHA-256 check.
- Keep `payments.tx_hash` unique and keep replays idempotent: the same payment may re-deliver, but must never settle twice.
- Treat everything in `PAYMENT-SIGNATURE` as untrusted input; a payment must accept the stored requirements unchanged.
- Every purchase step is recorded through `PurchaseService.record` (`activity/log.py`). Recording runs in its own transaction, must never raise into the purchase, and must never touch the purchase's session or locks. Record only public facts; never a payment header, signed blob, invoice id, key or seed. Public activity responses go through `activity/public.py` only. Keep `apps/api/tests/test_activity.py` passing.
- Keep the stub-facilitator tests in `apps/api/tests/test_payments.py` passing and extend the ledger-check matrix when rules change.
- Wallet seeds created by `make wallets` live only in the gitignored `.env`. Never commit, log or print seeds.

Buyer side (`packages/`), which runs on the buyer's machine, not on Sliver:

- The buyer's seed stays on the buyer's machine: never return it from a tool, log it, or send it anywhere. Wallet and state files are owner-only (0600 in a 0700 `~/.sliver/`).
- Never sign before the challenge matches the listing: Testnet `xrpl:1` XRP only, amount equal to the listing's USD price converted at the disclosed rate (rounded up, as the server does), payee equal to the seller's pinned address. The first purchase from a seller has no pin: it trusts the challenge's payee and pins it, because the catalog does not publish payee addresses yet.
- Keep the signed Payment to the XRPL `exact` scheme: `InvoiceID = SHA-256(invoiceId)`, `SourceTag` from the challenge, bounded `LastLedgerSequence`, capped fee, and no Memos, SendMax, DeliverMin, Paths or partial-payment flag. Keep the field allow-list in `sliver_x402/payment.py`.
- `sliver_quote_slice` never spends and never signs; a quoted custom slice is bought only through `sliver_buy`, under the same budget, caps and challenge checks.
- `sliver_buy` must refuse without a budget, over the budget or a local cap, or while another purchase is in flight. Extend the policy tests when rules change.
