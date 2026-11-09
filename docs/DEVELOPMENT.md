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
- `make wallets`: creates faucet-funded XRPL Testnet wallets for the demo sellers and a demo buyer (seeds go into `.env`, reused later) and sets the sellers' payout addresses. Run it after `make seed`, and again after a database reset.
- `make smoke-testnet`: with the stack running, buys the cheapest Resource on XRPL Testnet with t54's official client, checks the bytes against the catalog SHA-256, replays the payment, and asks the official x402.org facilitator to verify our requirements. Prints the transaction and explorer link.
- `make seed`: loads the demo catalog from `examples/datasets` (synthetic trade and logistics data, two demo sellers). Safe to run repeatedly.

## Demo catalog

`examples/datasets/manifest.toml` lists the demo sellers and datasets, their prices (USD cents) and how each dataset is sliced. Each dataset is published in full plus one Resource per slice. The CSVs are synthetic and regenerated deterministically with `python3 examples/datasets/generate.py`. Edit the manifest or the generator, then run `make dev-reset`, `make dev-start` and `make seed` to load the new content from scratch (existing objects are immutable).

Public endpoints:

- `GET /api/catalog?q=&category=&max_price_minor=&columns=&limit=&offset=`: search published Resources (metadata only).
- `GET /api/catalog/{id}`: one published Resource.
- `GET /api/catalog/categories`: categories with counts.
- `GET /api/demand?days=7`: searches that found nothing.

## Seller uploads and inspection

Set `SLIVER_SELLER_PASSWORD` and `SLIVER_REVIEWER_PASSWORD` in `.env` (empty values disable sign-in), restart the stack with `make dev-start` so the containers pick them up, then run `make seed`. Sign in at http://127.0.0.1:5173/sell/login as a demo seller (`harbour-analytics@sliver.local` or `strait-line-data@sliver.local`) or as `reviewer@sliver.local`. Re-run `make seed` after changing a password.

Sellers upload a UTF-8 CSV (at most 5 MiB, 10,000 rows, 100 columns) with a title, provenance (source, method, collection date) and a rights confirmation. The worker then runs validate, profile, privacy, duplicates, AI review, research, package and decide; the dataset page polls and shows each stage's status and findings, the proposed public listing, the packaged slivers and the acceptance decision. Datasets without blocking findings and with a quality score of at least `SLIVER_AUTO_ACCEPT_QUALITY` (70) are accepted automatically and wait for pricing (#15); the rest wait in the reviewer queue at `/sell`, where the reviewer approves or rejects each one with a reason. Sellers see only their own uploads; the reviewer sees only datasets that reached review (waiting, accepted or decided).

### AI review

`ANTHROPIC_API_KEY` is optional. Without it the AI review uses a deterministic offline fallback (category from column names, the seller's title, a description built from column names, counts and coverage, and a rule-chosen slice column), so the whole pipeline runs locally and in tests. With a key, Claude (`SLIVER_AI_MODEL`, default `claude-opus-5-5`) writes the listing and concerns from the column schema, the profile and at most 20 sample rows with flagged cells redacted (flagged columns also lose their min, max and mean, and a time coverage taken from a flagged column is never sent or shown publicly). Each call, retries included, gets at most `SLIVER_AI_TIMEOUT_SECONDS` (default 120) and never more than 60% of `PIPELINE_STEP_TIMEOUT_SECONDS`, so a slow call is not reclaimed and paid for twice. Only answers that pass validation are cached, in the private bucket under `ai-cache/` by prompt version, model and dataset SHA-256. Prompts are versioned files in `apps/api/sliver_api/prompts/`; change a prompt by adding a new version and pointing `ai.py` at it, so cached answers from the old prompt are not reused.

`SLIVER_AI_RESEARCH=true` adds a web-search check for freely available equivalents (needs the key; off by default because every run makes several web searches). After adding or changing these variables in `.env`, restart with `make dev-start`; the API image needs a rebuild for the new `anthropic` dependency anyway. Tests never call the API: `tests/conftest.py` removes the key.

For a live check, add the key, restart, and upload the four CSVs in `examples/datasets/` as a seller who does not own them (or `make dev-reset` first): each dataset page then shows "Written by Claude".

Fixtures for manual checks live in `examples/seller/`:

- `customer-contacts-pii.csv`: emails, phone numbers, Luhn-valid test card numbers, IBANs and NRIC/FIN numbers (all fictitious) under sensitive column names.
- `spot-rates-relisted.csv`: a near duplicate of the published container spot rates (about 5% of prices changed).
- `invalid-quality.csv`: a formula in a header cell, a short row and formula cells next to plain negative numbers.
- Uploading `examples/datasets/sg-berth-waiting-times.csv` itself shows an exact duplicate.

Endpoints (all mutations need an allowed `Origin`, see `SLIVER_ALLOWED_ORIGINS`):

- `POST /api/auth/login` (`{"email", "password"}`), `POST /api/auth/logout`, `GET /api/auth/me`.
- `POST /api/seller/datasets`: multipart `file`, `title`, `source`, `method`, `collected_at` (ISO date), `rights_confirmed=true` and an optional `rights_statement`. Bodies over the limit get 413 before parsing.
- `GET /api/seller/datasets` and `GET /api/seller/datasets/{id}`: datasets visible to the signed-in account, with per-stage status, findings, the column profile, the packaged slivers (`resources`) and any reviewer decision (`review`).
- `POST /api/seller/datasets/{id}/review` (reviewer only): `{"decision": "approve" | "reject", "reason": "..."}` for a dataset waiting for review. Approving accepts the dataset and returns its slivers to `draft` for pricing; rejecting marks the dataset and its slivers `rejected`. Anything not waiting for review answers 409.

## Payments (x402 on XRPL Testnet)

See [ADR 0004](adr/0004-x402-payments-on-xrpl.md). After `make seed` and `make wallets`:

- `GET /api/resources/{id}/data`: without `PAYMENT-SIGNATURE` it answers 402 with x402 v2 `PAYMENT-REQUIRED`; with a valid payment it returns the CSV plus `PAYMENT-RESPONSE` and an `X-Sliver-Receipt` id.
- `GET /api/receipts/{id}`: public receipt with the transaction hash and explorer link.
- `GET /.well-known/x402`: machine-readable list of paid endpoints and prices.

Buyer agents may send `X-Sliver-Agent-Note` with the data request: a short reason for the purchase (UTF-8, at most 200 characters; control and invisible characters are removed). It is public, shown on the activity feed and the purchase timeline, and never affects the payment.

Live activity (public, no buyer secrets):

- `GET /api/activity?limit=50&type=`: latest purchase events, newest first, plus a `cursor` for the stream.
- `GET /api/activity/stream?after=&payment_id=`: server-sent events (`activity` per new event, `heartbeat` every 15 s when quiet). Resumes from `Last-Event-ID`; each connection ends after 5 minutes and the browser reconnects without missing events.
- `GET /api/purchases/{id}`: one purchase's timeline (the id is the `X-Sliver-Receipt` value). The web app shows it at `/purchases/{id}`.

Settings (all optional, see `.env.example`): `FACILITATOR_URL`, `XRPL_RPC_URL` (Testnet allow-list only) and `DROPS_PER_USD`.

## Buyer MCP and x402 client

`packages/` is a uv workspace (Python 3.11+, uv 0.9.17) with `sliver-x402` (x402 v2 XRPL client) and `sliver-mcp` (the buyer's stdio MCP server). They run on the host, not in Compose. Install and agent setup are in [packages/sliver-mcp/README.md](../packages/sliver-mcp/README.md).

```bash
cd packages
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest
```

The tests use a stub Sliver API and stub facilitator and need no network. To try the server against the local stack, run `uv run sliver-mcp` (or point an MCP client at it) with `SLIVER_API_URL=http://127.0.0.1:8000` and either `sliver-mcp wallet init` or `SLIVER_WALLET_SEED` set to the demo buyer seed from `.env` (Testnet only). Buyer state lives in `~/.sliver/` (`SLIVER_HOME`).

## Working on the code

- API source: `apps/api/sliver_api`, tests in `apps/api/tests`, migrations in `apps/api/migrations`. Edits reload automatically.
- New migration: `docker compose --env-file .env -f compose.yml run --rm api alembic revision -m "describe change"`, then edit the generated file.
- Python dependencies: edit `apps/api/pyproject.toml`, run `uv lock` in `apps/api` (uv 0.9.17), then `make install`.
- Web source: `apps/web/src`. Edits hot-reload in the browser.
- Web dependencies: edit `apps/web/package.json`, run `npm install` in `apps/web` to update the lockfile, then `make dev-start` (it rebuilds the image and refreshes the container's `node_modules`).

## Existing `.env` files

`make install` never rewrites `.env`. A `.env` created before the application containers existed still works; new variables fall back to defaults. It may still contain `POSTGRES_PORT=5432`. If another PostgreSQL already uses that port, change it to `5433`.

## Continuous integration

`.github/workflows/ci.yml` runs on pull requests, on pushes to `main`, and in merge queues:

- Shell scripts, workflows and Compose configuration checks (shellcheck, actionlint, `docker compose config`).
- API lint and tests against a PostgreSQL service.
- Web typecheck and production build.
- Buyer packages (`packages/`): Ruff lint and format check and tests on Python 3.11 and 3.13.
- The containerized stack: repeat-install `.env` preservation, all five services healthy, health endpoints and web proxy, tests and lint inside the containers, degraded health with storage stopped, and volume preservation on stop.

## Future / not yet committed

- Production images and a deployment workflow
