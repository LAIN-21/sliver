# Local-demo quotes, purchases and private delivery

## Status

Accepted for issue #8's explicitly requested recordable demonstration on 7 November 2026. This decision extends the local demonstration, not production commerce. Neither the seller foundation nor the new branch is authorized to merge.

## Decision

- Preserve the whole immutable CSV Resource and seller/reviewer publication gate.
- Bind a short-lived quote to an existing opaque browser session. Snapshot the Resource, file digest/size, USD minor-unit price, payment mode and settlement terms. An unpredictable quote memo binds a testnet transfer to one quote. Session rotation/expiry can end access; durable buyer identity is pilot work.
- Payment mode defaults to `disabled`. Explicit `simulated` mode is a loopback recording tool, visibly labelled SIMULATED / NO REAL MONEY throughout. Its receipt identifiers start with `SIM-`; it does not invent ledger hashes. A simulation is never used to resolve a real testnet payment.
- `xrpl-testnet` accepts an externally submitted transaction hash and verifies it against an allowlisted official testnet RPC. Check a validated successful native-XRP Payment, payer, recipient, delivered drops, quote memo and proof reuse. The server does not sign, possess buyer wallet secrets or implement autonomous buyer spending. No mainnet mode exists.
- The testnet USD-to-drops conversion is a configured illustrative demonstration rate, not a market price feed. Display this distinction with quote terms. The exact integration is not advertised as a complete x402 implementation merely because unpaid access returns 402.
- Persist each quote's attempted hash before network verification, without globally reserving an unverified public hash. Bind a separate globally unique settled hash only on the verified paid transition; invalid/pending attempts cannot preempt another buyer's legitimate payment. Duplicate confirmations return the existing result. Pending/unknown outcomes reconcile the same proof without creating another payment. Authoritative confirmation and successful file delivery remain distinct facts.
- Buyer download requires the owning valid session, paid state, matching snapshotted version and intact bytes. Existing owner/reviewer downloads remain unchanged.
- The buyer interface/example decides whether a candidate fits its budget before confirmation, downloads original bytes, verifies the digest and computes the example result locally. Data/metadata never authorize arbitrary spending destinations.
- Add bounded metadata search/price filtering/pagination and public digest/size so a client can understand and verify the offer. Do not expose previews, private declarations, filenames or storage keys.

## Recording adapter

The user's local Docker/WSL installation currently cannot attach its Docker VHD. Provide an explicit `examples/local_demo.py` loopback runner using a separate SQLite database and private local-file adapter. This is a deliberate additional demo/test adapter exception to ADR 0003. It never changes `Settings.from_env`'s PostgreSQL/S3 production contract, never silently falls back on dependency failure, and never resets existing PostgreSQL/MinIO data.

Create a dedicated ignored data directory with generated local credentials, private original bytes and a fixture marker. Seed synthetic example offers through the same seller/reviewer APIs. Repeated launch preserves accounts and data. No automatic destructive reset is introduced. Document its verification as adapter evidence separately from real PostgreSQL/MinIO hosted integration.

## Alternatives and limits

- Public buyer signup, wallet login and production custody/payout decisions require a larger pilot design.
- Adding an agent to the platform to spend autonomously violates the product invariant; keep it external.
- Calling a local simulation testnet settlement would be misleading; modes and receipts remain distinct.
- Synchronous, bounded verification is sufficient for this local demonstration; durable scheduled reconciliation and production operations are follow-ups.
- Existing seed/bootstrap can create additive tables; it does not constitute production schema migration history.

## Required evidence

Preserve seller/reviewer checks. Test quote/session/expiry/mode boundaries, duplicate and concurrent confirmations, wrong/replayed testnet proofs, unknown outcomes and exact-version delivery. Run browser refusal/purchase/result flows and frontend build. Retain hosted real-service CI separately and disclose live-testnet or local-service blockers.
