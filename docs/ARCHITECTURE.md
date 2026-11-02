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
- The first seller application uses Python/FastAPI with SQLAlchemy and a
  TypeScript/React UI built with Vite. PostgreSQL holds metadata and server-side
  sessions; S3-compatible private storage holds immutable uploaded CSV bytes.
- The local demo has two sellers and a separate reviewer. Reviewer approval
  publishes a fixed-price, whole-CSV Resource; public discovery exposes metadata
  only. See [ADR 0003](adr/0003-seller-application-and-review-boundary.md).

## Current assumptions

- CSV, JSON, and Parquet are likely early source formats. Support does not exist until it is implemented.
- Initial pricing is expected to consider coverage and value. The exact formula is not finalized.
- x402 is the intended mechanism for machine-to-machine payment gating, subject to a later transaction ADR.

## Open questions

- Cloud provider
- Queue
- Cache
- Vector database
- Production authentication provider (local demo accounts are implemented)
- Resource metadata schema
- Exact pricing formula
- Whether the four conceptual responsibilities become packages, modules, services, or deployables
- Exact x402/XRPL integration and operational architecture, including transaction lifecycle, enforcement location, reconciliation, payout model, and wallet/key custody

Record significant answers as ADRs. See [adr/README.md](adr/README.md).
