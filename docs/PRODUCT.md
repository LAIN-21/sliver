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

Pricing considers both coverage and value. Sliver suggests an explainable price for each sliver from its quality, uniqueness against the catalog, unmet buyer demand, public availability and coverage; the seller accepts or overrides it before publishing. The formula is an architecture question, not a product invariant. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Business model

Sellers list data for sale. On every sale the seller gets paid and Sliver takes a cut, the platform fee (10% by default).

- The buyer pays the full listed price to Sliver's platform wallet, with one standard x402 payment.
- Sliver keeps its fee and pays the seller the rest every 15 days (on the 1st and 16th of each month). Payouts are not automated yet.
- Sellers see the balance Sliver owes them, the next payout date, and the gross, Sliver's fee and their net for every sale. Before publishing, they see the net they would receive at each price.
- Testnet only. Sliver holds funds between a sale and the payout, so Mainnet use needs custody and compliance work first.

See [ADR 0005](adr/0005-platform-collection-and-payouts.md).

## Conceptual flows

These sequences describe product behavior. They are not service, package, or deployable boundaries.

Seller flow:

ingestion → inspection → provenance/trust validation → Resource generation → pricing → approval → publication

Buyer flow:

information need → discovery → candidate Resources → buyer decision → purchase → entitlement → delivery → accounting
