# Product

Sliver enables data owners to make useful data machine-purchasable.

Sliver is not the buying agent. External agents decide whether purchasing data is worthwhile. Sliver's buyer-facing responsibility is to help an external agent discover relevant Resources, understand what they contain, understand their trust and provenance signals and price, and purchase them if the external agent chooses to do so.

## Invariants

- External agents discover Resources through Sliver.
- Sliver returns candidate Resources and metadata.
- External agents make their own spending decisions.
- Sliver must not autonomously decide to spend buyer funds.
- A Resource is a purchasable view over an underlying data source.
- Discovery metadata must not reveal the protected contents of paid data.

## Focus

The initial seller focus is structured uploaded datasets.

Enterprise and API integrations are a later input mechanism into the same Resource marketplace.

Pricing is expected to consider both coverage and value. The formula is an architecture question, not a product invariant. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Conceptual flows

These sequences describe product behavior. They are not service, package, or deployable boundaries.

Seller flow:

ingestion → inspection → provenance/trust validation → Resource generation → pricing → approval → publication

Buyer flow:

information need → discovery → candidate Resources → buyer decision → purchase → entitlement → delivery → accounting

## Local demonstration scope

The seller workflow publishes reviewed whole-CSV offers. The buyer demonstration
adds metadata search, session-bound quotes, labelled simulated settlement or
external XRPL testnet verification, and permission to retrieve exact quoted bytes.
The buyer UI/example enforces its own budget and computes a source-linked result
after download. Simulation is not a commercial transaction; testnet conversion
is illustrative rather than a live exchange-rate quote.

Production buyer identity, custody/payout, durable recovery, accounting and
deployment remain pilot decisions. Reviewer approval records a human publication
decision, not independently verified ownership or factual truth.
