# Development

How development is intended to work. Contributor workflow is in [CONTRIBUTING.md](../CONTRIBUTING.md). Infrastructure constraints are in [agents/infrastructure.md](agents/infrastructure.md).

## Supported hosts

Local commands assume a POSIX shell, Make, Git, and Docker with Compose v2 (`docker compose up --wait`).

Supported:

- macOS
- Linux
- Windows only through WSL

Native Windows cmd or PowerShell is not a supported host contract in this foundation.

## Available now

Infrastructure-only local environment. No application runtime.

Host tools: Git, Docker with Compose v2, Make.

Public Make interface:

- `make doctor` — reports whether Git, Make, Docker, the Docker daemon, Compose, and `docker compose up --wait` are available
- `make install` — runs `doctor`, creates `.env` from `.env.example` only if `.env` is missing, then pulls images. Never overwrites an existing `.env`. Safe to run repeatedly. May contact the container registry.
- `make dev-start` — runs `install`, then starts PostgreSQL and MinIO and waits until they are healthy. May contact the registry every time.
- `make dev-stop` — stops Compose services without deleting named volumes or development data
- `make dev-reset` — non-interactive destructive reset: stops services and deletes local persisted volumes
- `make ps` — Compose service status
- `make logs` — recent Compose logs (does not follow)

Services: PostgreSQL (`postgres:16.10-bookworm`) and MinIO (`minio/minio:RELEASE.2025-09-07T16-13-09Z`), with persistent named volumes.

Copy [`.env.example`](../.env.example) is handled by `make install`. `.env` is gitignored.

Typical flow: `make doctor`, `make install`, `make dev-start`. `make dev-start` includes `install`.

## Planned during M0

These are not available yet:

- Baseline CI
- Application stack decision through an ADR
- Initial application skeleton
- Isolating application dependencies from contributor machines as much as practical

## Future / not yet committed

- Production deployment workflow
