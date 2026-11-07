# Sliver

Sliver is infrastructure and a marketplace that lets data owners turn datasets into granular, machine-purchasable Resources for external AI agents.

The first local seller demonstration supports private CSV upload, structural
validation, fixed-price Resources, separate reviewer approval, and a public
metadata-only catalog. The interface uses React/TypeScript and the API uses
Python/FastAPI, PostgreSQL, and private S3-compatible storage.

The buyer lab adds budget checks, expiring version-bound quotes, explicit
simulated purchases or external XRPL testnet proof verification, private delivery,
receipts and a locally computed answer. Simulation is visibly labelled and moves
no money. The platform never signs buyer payments.

Follow [the development guide](docs/DEVELOPMENT.md) for PostgreSQL/MinIO or the
explicit loopback recording adapter (`python examples/local_demo.py`). The latter
uses dedicated SQLite/private local files and synthetic fixtures, including on
native Windows. Public signup, mainnet commerce and production hosting remain
outside this local demonstration.

## Start here

- Product: [docs/PRODUCT.md](docs/PRODUCT.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Development: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md)
- Contributors: [CONTRIBUTING.md](CONTRIBUTING.md)
- Coding agents: [AGENTS.md](AGENTS.md)

Licensed under the [Apache License 2.0](LICENSE).
