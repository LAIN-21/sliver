# Architecture

This document records system-level decisions, assumptions, and open questions. Product invariants live in [PRODUCT.md](PRODUCT.md).

## Decisions

- Sliver does not make autonomous buyer spending decisions.
- Resource is a first-class domain abstraction.
- A Resource is a purchasable view over an underlying data source.
- Protected underlying data must not leak through discovery metadata.
- Seller, marketplace/catalog, buyer-facing interface, and transaction layer are distinct conceptual responsibilities.
- Those four conceptual responsibilities are an agreed architectural decision. They are not automatic microservices, packages, modules, or deployables.
- The old `ripple-challenge` Ledger402 autonomous procurement agent is a reference/demo buyer, not the Sliver architecture.
- Initial work focuses on structured dataset sellers.
- Enterprise API integration should eventually converge into the same marketplace abstraction.
- Sliver is intended to support settlement through the XRP Ledger.
- The API and pipeline worker use Python 3.13, FastAPI 0.115.x, SQLAlchemy 2 and Alembic; the web app uses React, TypeScript, Vite and Tailwind CSS. See [ADR 0003](adr/0003-application-stack-and-local-containers.md).
- Local development runs entirely in Docker Compose: PostgreSQL, MinIO, API, worker and web, published on 127.0.0.1 only.
- Background jobs will be PostgreSQL rows claimed with `FOR UPDATE SKIP LOCKED`; there is no queue service. The worker does not claim jobs yet; claiming arrives with the first pipeline stage (#13).
- A Resource ("sliver") is either a whole dataset or one slice of it (one value of a column, or one calendar month of a date column). Each Resource is stored as its own immutable CSV object with its own SHA-256, so delivery and integrity checks never touch the rest of the dataset.
- Public discovery serializes Resources through one allow-list (`catalog/public.py`) and searches them with PostgreSQL full-text search, matching any query term and ranking by relevance. See [agents/catalog.md](agents/catalog.md).
- Resources are bought with x402 v2 on XRPL Testnet: `GET /api/resources/{id}/data` answers 402, buyers pay the seller directly with a presigned Payment, a facilitator (t54 by default) settles it, and Sliver independently checks the ledger before delivering. Sliver never signs or holds funds. See [ADR 0004](adr/0004-x402-payments-on-xrpl.md) and [agents/transactions.md](agents/transactions.md).
- Every catalog query records an anonymous search event. Queries that return nothing are exposed as unmet demand (`GET /api/demand`) for sellers.

## Current assumptions

- CSV, JSON, and Parquet are likely early source formats. Support does not exist until it is implemented.
- Initial pricing is expected to consider coverage and value. The exact formula is not finalized.
- Prices are set in USD and converted to XRP drops at a fixed, disclosed demo rate.

## Open questions

- Cloud provider
- Cache
- Vector database
- Authentication provider
- Resource metadata schema
- Exact pricing formula
- Whether the four conceptual responsibilities become packages, modules, services, or deployables
- Marketplace fees, payouts beyond direct payment, refunds, and mainnet operation

Record significant answers as ADRs. See [adr/README.md](adr/README.md).
