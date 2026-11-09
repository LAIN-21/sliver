# Development

How development is intended to work. Contributor workflow is in [CONTRIBUTING.md](../CONTRIBUTING.md). Infrastructure constraints are in [agents/infrastructure.md](agents/infrastructure.md). The stack is recorded in [ADR 0003](adr/0003-application-stack-and-local-containers.md).

## Supported hosts

Local commands assume a POSIX shell, Make, Git, and Docker with Compose v2 (`docker compose up --wait`). Docker Desktop (or another Docker daemon) must be running.

Supported:

- macOS
- Linux
- Windows only through WSL

Native Windows cmd or PowerShell is not a supported host contract.

No Python or Node installation is needed on the host: the API, worker and web app run in containers.

## Quick start

```bash
make dev-start
```

Then open http://127.0.0.1:5173. The footer shows whether the API, database and storage are ready.

The first run builds MinIO from source and the application images, which takes several minutes. Later runs reuse the build cache.

## Services

All ports are published on 127.0.0.1 only. Host ports come from `.env`.

| Service | Purpose | Host address |
|---|---|---|
| `postgres` | Metadata (PostgreSQL 16) | `127.0.0.1:${POSTGRES_PORT}` (default 5433) |
| `minio` | Private object storage (S3-compatible), built from pinned upstream source | API `127.0.0.1:9000`, console `127.0.0.1:9001` |
| `api` | FastAPI app, hot reload, runs migrations on start | http://127.0.0.1:8000 (`/api/health`, `/docs`) |
| `worker` | Background pipeline worker (same image as the API) | none |
| `web` | Vite dev server for the React app, proxies `/api` to the API | http://127.0.0.1:5173 |

The application containers derive `DATABASE_URL` and S3 credentials from the PostgreSQL and MinIO values in `.env`. Persistent data lives in the named volumes `postgres_data` and `minio_data`.

## Make targets

- `make doctor`: reports whether Git, Make, Docker, the Docker daemon, Compose, and `docker compose up --wait` are available.
- `make install`: runs `doctor`, creates `.env` from `.env.example` only if `.env` is missing, pulls PostgreSQL, and builds the MinIO, API and web images. Never overwrites an existing `.env`. Safe to run repeatedly. May contact registries.
- `make dev-start`: runs `install`, then starts all services and waits until they are healthy.
- `make dev-stop`: stops services without deleting named volumes or development data.
- `make dev-reset`: non-interactive destructive reset; stops services and deletes local persisted volumes.
- `make ps`: Compose service status.
- `make logs`: recent Compose logs (does not follow).
- `make test`: runs the API test suite in the API container against PostgreSQL (database `<POSTGRES_DB>_test`, created automatically) and MinIO.
- `make lint`: Ruff lint and format check for the API, TypeScript typecheck for the web app.
- `make migrate`: applies database migrations (the API also does this on start).
- `make seed`: loads the demo catalog from `examples/datasets` (synthetic trade and logistics data, two demo sellers). Safe to run repeatedly.

## Demo catalog

`examples/datasets/manifest.toml` lists the demo sellers and datasets, their prices (USD cents) and how each dataset is sliced. Each dataset is published in full plus one Resource per slice. The CSVs are synthetic and regenerated deterministically with `python3 examples/datasets/generate.py`. Edit the manifest or the generator, then run `make dev-reset`, `make dev-start` and `make seed` to load the new content from scratch (existing objects are immutable).

Public endpoints:

- `GET /api/catalog?q=&category=&max_price_minor=&columns=&limit=&offset=`: search published Resources (metadata only).
- `GET /api/catalog/{id}`: one published Resource.
- `GET /api/catalog/categories`: categories with counts.
- `GET /api/demand?days=7`: searches that found nothing.

## Working on the code

- API source: `apps/api/sliver_api`, tests in `apps/api/tests`, migrations in `apps/api/migrations`. Edits reload automatically.
- New migration: `docker compose --env-file .env -f compose.yml run --rm api alembic revision -m "describe change"`, then edit the generated file.
- Python dependencies: edit `apps/api/pyproject.toml`, run `uv lock` in `apps/api` (uv 0.9.17), then `make install`.
- Web source: `apps/web/src`. Edits hot-reload in the browser.
- Web dependencies: edit `apps/web/package.json`, run `npm install` in `apps/web` to update the lockfile, then `make dev-start` (it rebuilds the image and refreshes the container's `node_modules`).

## Existing `.env` files

`make install` never rewrites `.env`. A `.env` created before the application containers existed still works; new variables fall back to defaults. It may still contain `POSTGRES_PORT=5432`. If another PostgreSQL already uses that port, change it to `5433`.

## Continuous integration

`.github/workflows/ci.yml` runs on pull requests and on `main`:

- Shell scripts, workflows and Compose configuration checks (shellcheck, actionlint, `docker compose config`).
- API lint and tests against a PostgreSQL service.
- Web typecheck and production build.
- The containerized stack: repeat-install `.env` preservation, all five services healthy, health endpoints and web proxy, tests and lint inside the containers, degraded health with storage stopped, and volume preservation on stop.

## Future / not yet committed

- Production images and a deployment workflow
