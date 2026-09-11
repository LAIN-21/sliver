# Architecture Decision Records

Use an ADR to record a significant technical decision.

This directory currently contains the process only. Do not add speculative ADRs.

## When an ADR is required

Create an ADR before or with the change that:

- Selects a language or framework
- Selects a database
- Chooses a storage strategy
- Introduces a queue
- Changes architectural boundaries
- Defines transaction architecture
- Chooses cloud architecture

See [ARCHITECTURE.md](../ARCHITECTURE.md) for current decisions, assumptions, and open questions. Transaction architecture, including x402 integration, remains open until an ADR records it.

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

Use numbered files such as `0001-short-title.md` when the first ADR is written.
