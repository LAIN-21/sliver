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

Buyers pay for the slice their question needs. Besides the slivers a seller publishes, a buyer's agent may ask for a custom slice of a published dataset (a time range and/or one value of a category column): Sliver cuts exactly those rows, prices them per row from the seller's published full-dataset price, never above it, and sells them like any sliver: the sale is credited to the same seller. Sellers choose at publication whether to offer custom slices (on by default). Asking for a quote never spends; the buyer's agent still decides whether to buy.

Pricing considers both coverage and value. Sliver suggests an explainable price for each sliver from its quality, uniqueness against the catalog, unmet buyer demand, public availability and coverage; the seller accepts or overrides it before publishing. The formula is an architecture question, not a product invariant. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Conceptual flows

These sequences describe product behavior. They are not service, package, or deployable boundaries.

Seller flow:

ingestion → inspection → provenance/trust validation → Resource generation → pricing → approval → publication

Buyer flow:

information need → discovery → candidate Resources → buyer decision → purchase → entitlement → delivery → accounting
