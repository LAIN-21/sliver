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

- Application stack decision through an ADR
- Initial application skeleton
- Isolating application dependencies from contributor machines as much as practical

## Continuous integration

Foundation CI runs on pull requests, pushes to `main`, and merge queue events.
The quality job checks POSIX shell syntax, ShellCheck, actionlint, and Compose
configuration. The integration job exercises the existing Make interface in an
isolated Compose project, verifies repeated installation preserves `.env`, and
requires PostgreSQL and MinIO to be running and healthy. Failed runs collect
service logs; cleanup always attempts `make dev-stop`.

Checks use synthetic local configuration and read-only repository permissions.
They do not deploy an application or access production secrets. ShellCheck and
actionlint releases are pinned and their downloads verified with SHA-256.

## Future / not yet committed

- Production deployment workflow
