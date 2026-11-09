# ADR 0003: Application stack and local container topology

## Context

Sliver needs an application runtime for the seller pipeline, the marketplace API, x402 payments on the XRP Ledger, and a web interface. The previous attempt (closed PRs #7 and #9) was not merged, so the stack was still an open question in [ARCHITECTURE.md](../ARCHITECTURE.md).

Two constraints shape the choice:

- The XRPL x402 support in the XRPL AI Starter Kit comes from t54's Python SDK, `x402-xrpl`, with a FastAPI merchant guide. The team's SingHacks prototype used the same SDK for real testnet payments. Version 0.3.4 pins `fastapi>=0.115,<0.116` and `uvicorn<0.31`.
- Contributors should not need language toolchains on their machines. Everything runs in containers on loopback.

Official MinIO container images and binaries are no longer distributed, so the image pinned in the original Compose file no longer pulls.

This ADR records the stack the repository owner approved with the build plan on 9 November 2026 (issue #10).

## Decision

- **API and worker:** Python 3.13, FastAPI 0.115.x, SQLAlchemy 2 with Alembic migrations, psycopg 3, boto3 for S3-compatible storage. Dependencies are locked with uv. The API is an application factory (`uvicorn --factory sliver_api.main:create_app`). The worker uses the same image.
- **Web:** React 19, TypeScript, Vite and Tailwind CSS, served by the Vite dev server, which proxies `/api` to the API so browser requests stay same-origin.
- **Local topology:** Docker Compose runs `postgres`, `minio`, `api`, `worker` and `web`. Every published port binds to 127.0.0.1. Named volumes `postgres_data` and `minio_data` hold persisted state. The API applies migrations on start; the worker starts after the API is healthy.
- **No queue service:** background jobs are rows in PostgreSQL claimed with `SELECT … FOR UPDATE SKIP LOCKED` by the worker. This needs no new infrastructure and is enough for pipeline jobs at demo and early production scale.
- **MinIO:** built from pinned, unmodified upstream source (`RELEASE.2025-10-15T17-29-55Z` server, `RELEASE.2025-08-13T08-35-41Z` client) in a scratch image, `docker/minio/Dockerfile`. The S3-compatible interface from ADR 0002 is unchanged.
- **Buyer tooling stays outside the stack:** the buyer MCP server runs on the buyer's machine and talks to the API over HTTP.

## Alternatives Considered

- **TypeScript end to end** with the official `@x402/xrpl` packages: clean x402 support, but it would discard the team's working Python x402 experience and the Starter Kit's FastAPI path, and it is a larger rewrite in the time available.
- **Newer FastAPI:** not compatible with `x402-xrpl` 0.3.4.
- **Redis or another queue for jobs:** new infrastructure without a current need (see [agents/infrastructure.md](../agents/infrastructure.md)).
- **Another S3-compatible server or a filesystem store:** would add a new source of trust or change ADR 0002; the pinned source build keeps the existing interface.
- **Running applications on the host:** requires matching Python and Node versions on every contributor machine.

## Consequences

- `make dev-start` brings up the whole system; the first build compiles MinIO and takes several minutes, later builds are cached.
- The API stays on FastAPI 0.115.x until `x402-xrpl` relaxes its pins.
- Containers mount the source for hot reload, so they are development images, not production images. Production images, deployment and hosting remain separate decisions.
- Job throughput is bounded by PostgreSQL; a dedicated queue can be reconsidered with a new ADR if that ever matters.

## Status

Accepted
