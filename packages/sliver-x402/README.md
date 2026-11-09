# sliver-x402

Minimal x402 v2 client for the XRPL `exact` scheme on XRPL Testnet, used by [sliver-mcp](../sliver-mcp).

- `parse_payment_required` / `select_requirement`: decode a `PAYMENT-REQUIRED` challenge and accept only a requirement that matches the caller's expected amount, payee and network (`xrpl:1`).
- `sign_payment` (autofill from a Testnet RPC) / `sign_offline`: build the Payment with `InvoiceID = SHA-256(invoiceId)`, `SourceTag`, a `LastLedgerSequence` of at most `validated + ceil(maxTimeoutSeconds / 5) + 2` and a capped fee, check every field against an allow-list (no Memos, SendMax, DeliverMin, Paths or partial payments), then sign locally.
- `encode_payment_signature` / `decode_payment_response`: the `PAYMENT-SIGNATURE` and `PAYMENT-RESPONSE` headers.

Network access happens only in `sign_payment` (ledger index, sequence and fee).
