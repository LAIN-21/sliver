# Architecture Decision Records

Use an ADR to record a significant technical decision.

Accepted records:

- [0001-postgresql-primary-relational-database.md](0001-postgresql-primary-relational-database.md)
- [0002-s3-compatible-object-storage.md](0002-s3-compatible-object-storage.md)
- [0003-application-stack-and-local-containers.md](0003-application-stack-and-local-containers.md)
- [0004-x402-payments-on-xrpl.md](0004-x402-payments-on-xrpl.md)
- [0005-platform-fee-model.md](0005-platform-fee-model.md): Sliver's platform fee, recorded per sale and settled off-chain. It fills the marketplace fee that ADR 0004 left out of scope, without changing ADR 0004's payment flow.

Do not add speculative ADRs.

## When an ADR is required

Create an ADR before or with the change that:

- Selects a language or framework
- Selects a database
- Chooses a storage strategy
- Introduces a queue
- Changes architectural boundaries
- Defines transaction architecture
- Chooses cloud architecture

See [ARCHITECTURE.md](../ARCHITECTURE.md) for current decisions, assumptions, and open questions. Transaction architecture and the x402 integration are recorded in ADR 0004; the platform fee model in ADR 0005.

## Format

Each ADR should include:

### Context

What problem or choice is being decided, and why it matters now.

### Decision

What we chose.

### Alternatives Considered

What we considered and rejected, and why.

### Consequences

What becomes easier, harder, or newly constrained.

### Status

Proposed, accepted, superseded, or deprecated.

## Naming

Use numbered files such as `0001-short-title.md`.
