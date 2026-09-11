# ADR 0001: PostgreSQL as primary relational database

## Context

Issue #2 requires a local relational store for Sliver's development foundation and records PostgreSQL as Sliver's primary relational database. Local infrastructure must match that choice so later application work is not built against a throwaway engine.

This ADR records a decision already approved by the task and repository owner. It does not independently originate the choice.

## Decision

PostgreSQL is Sliver's primary relational database.

Local development uses PostgreSQL via Docker Compose. See [DEVELOPMENT.md](../DEVELOPMENT.md).

## Alternatives Considered

- **SQLite.** Simpler to embed, weaker parity with a multi-user marketplace database.
- **MySQL / MariaDB.** Capable, but there is no current requirement that favors them over PostgreSQL.

## Consequences

- Local Compose infrastructure runs PostgreSQL.
- Application code, schema, and migrations remain out of scope until later issues.

This ADR does not decide PostgreSQL extensions, pgvector, connection pooling, ORM, migration framework, tenancy, schema layout, or a managed cloud provider.

## Status

Accepted
