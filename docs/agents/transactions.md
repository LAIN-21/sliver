# Transactions

Additional constraints for payments (`apps/api/sliver_api/payments`). Repository-wide rules in [AGENTS.md](../../AGENTS.md) still apply. The design is in [ADR 0004](../adr/0004-x402-payments-on-xrpl.md).

- Sliver never signs transactions, never stores or reads buyer keys, and never custodies funds. Buyers pay sellers directly.
- Never implement spending on a buyer's behalf on the server. Spending decisions belong to the buyer's agent and its human.
- Testnet only (`xrpl:1`). Do not add mainnet configuration, endpoints or keys.
- Never deliver data unless the ledger re-check in `ledger_check.py` passes. Never settle before the stored object passes its SHA-256 check.
- Keep `payments.tx_hash` unique and keep replays idempotent: the same payment may re-deliver, but must never settle twice.
- Treat everything in `PAYMENT-SIGNATURE` as untrusted input; a payment must accept the stored requirements unchanged.
- Keep the stub-facilitator tests in `apps/api/tests/test_payments.py` passing and extend the ledger-check matrix when rules change.
- Wallet seeds created by `make wallets` live only in the gitignored `.env`. Never commit, log or print seeds.
