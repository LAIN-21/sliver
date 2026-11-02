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

Local PostgreSQL/MinIO infrastructure, a Python/FastAPI seller API, and a
React/TypeScript UI. The seller demonstration includes private CSV upload,
structural validation, fixed-price Resources, reviewer approval, and a public
metadata-only catalog. Payments and buyer delivery are not implemented.

Host tools: Git, Docker with Compose v2, Make.

Public Make interface:

- `make doctor` — reports whether Git, Make, Docker, the Docker daemon, Compose, and `docker compose up --wait` are available
- `make install` — runs `doctor`, creates `.env` from `.env.example` only if `.env` is missing, pulls PostgreSQL, then builds MinIO from pinned official source. Never overwrites an existing `.env`. Safe to run repeatedly. May contact registries, the Go proxy, and its checksum database.
- `make dev-start` — runs `install`, then starts PostgreSQL and MinIO and waits until they are healthy. May contact the registry every time.
- `make dev-stop` — stops Compose services without deleting named volumes or development data
- `make dev-reset` — non-interactive destructive reset: stops services and deletes local persisted volumes
- `make ps` — Compose service status
- `make logs` — recent Compose logs (does not follow)

Services: PostgreSQL (`postgres:16.10-bookworm`) and a local MinIO source image
(server `RELEASE.2025-10-15T17-29-55Z`), with persistent named volumes. The old
prebuilt MinIO image is no longer available. The first clean installation
compiles the pinned server and client and can take several minutes; later builds
use the Docker build cache. See [ADR 0004](adr/0004-minio-source-build.md).

Copy [`.env.example`](../.env.example) is handled by `make install`. `.env` is gitignored.

Typical flow: `make doctor`, `make install`, `make dev-start`. `make dev-start` includes `install`.

## Run the seller demonstration

Use Python 3.13, Node.js 24, and npm in addition to the infrastructure tools.
On Windows, run the commands inside WSL. Application dependencies are isolated
in a Python virtual environment and the UI's `node_modules`; no Python or Node
application container is added to Compose.

From the repository root:

```sh
make dev-start
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r apps/api/requirements-dev.txt
python -m pip install -e apps/api --no-deps
npm ci --prefix apps/web
```

Edit the local `.env` created by `make install`. Set three distinct passwords
(12–256 characters) in `SLIVER_SELLER_A_PASSWORD`, `SLIVER_SELLER_B_PASSWORD`,
and `SLIVER_REVIEWER_PASSWORD`. For example, generate each with
`python -c 'import secrets; print(secrets.token_urlsafe(24))'`. Do not commit the
generated values. Keep `DATABASE_URL` and the `S3_*` configuration aligned with
any infrastructure credential/port overrides.

Initialize the local schema, private bucket, and accounts explicitly:

```sh
python -m sliver_api.seed
uvicorn sliver_api.main:app --host 127.0.0.1 --port 8000
```

The seed command refuses empty/short passwords and preserves existing accounts
and passwords when repeated. It creates the initial schema, not a production
migration history. In another terminal, start the UI:

```sh
npm run dev --prefix apps/web
```

Open <http://127.0.0.1:5173>. Accounts are `seller-a@sliver.local`,
`seller-b@sliver.local`, and `reviewer@sliver.local`, using the passwords you
configured. The Vite proxy forwards `/api` requests to port 8000. Its development
and preview servers bind to loopback; do not expose these demo accounts publicly.

Try the complete workflow:

1. Log in as seller A and upload a synthetic UTF-8 CSV with a header and data row.
2. Supply the source, method, ISO collection date, coverage, and private rights
   declaration. Inspect structural checks and the private first-20-row preview.
3. Create a Resource for that immutable upload at a fixed USD price, then submit.
4. Log out and log in as the reviewer. Inspect the submitted Resource and private
   evidence; approve/publish or reject with a reason.
5. Log out and inspect the public catalog. Only approved metadata appears; private
   rows, original filename, storage key, and rights declaration are excluded.

The original file has a SHA-256 integrity digest. Uploads are limited to 5 MiB,
10,000 data rows, and 100 columns; fields are bounded. Invalid UTF-8, empty or
duplicate headers, ragged rows, and exceeded limits fail without storing a
Dataset. Missing values, duplicate rows, and spreadsheet-like formulas produce
warnings. Downloaded originals are not sanitized for spreadsheet execution.

### API and responsibility boundaries

The API's interactive schema is available at <http://127.0.0.1:8000/docs> while
the server runs. Browser mutations require both an allowed `Origin` and the
`X-CSRF-Token` returned by `GET /api/session`. Login rotates the opaque session
and CSRF token; logout revokes the server record. Cookies are HttpOnly and
SameSite Strict. Use `SESSION_SECURE=true` only with HTTPS.

| Route | Access and behavior |
| --- | --- |
| `GET /api/health` | Server liveness; does not prove database/storage readiness |
| `GET /api/session` | Current user and CSRF token; creates an anonymous session if needed |
| `POST /api/session`, `DELETE /api/session` | Login/logout; CSRF and Origin required |
| `GET`, `POST /api/datasets` | Seller lists own/uploads; reviewer lists all |
| `GET /api/datasets/{id}` | Owner/reviewer private metadata |
| `GET /api/datasets/{id}/preview`, `/download` | Owner/reviewer preview/original bytes |
| `GET`, `POST /api/resources` | Seller lists own/creates draft; reviewer lists all |
| `POST /api/resources/{id}/submit` | Owner only; draft to submitted |
| `POST /api/resources/{id}/review` | Reviewer only; submitted to approved/published or rejected |
| `GET /api/catalog` | Public approved metadata; no paid bytes or purchase endpoint |

A Dataset is a private immutable uploaded version. A Resource is a priced view
over that version; this first slice offers the whole CSV only. Prices are positive
integer USD cents (`price_minor`), never floating-point currency or stored XRP
drops. Rejection is terminal; a correction requires a new draft. No API mutates
the uploaded bytes, published price, or published Resource version.

CSV checks establish file quality. Reviewer approval records a human decision;
neither proves legal ownership, licensing permission, or factual accuracy.
External agents retain their own spending decisions. No model or application
path in this slice signs payments, issues entitlements, or serves buyers paid rows.

### Application checks

```sh
python -m pytest apps/api/tests -q
npm run typecheck --prefix apps/web
npm run build --prefix apps/web
```

API tests use explicit SQLite/in-memory storage adapters. Runtime configuration
does not select those adapters. They do not replace PostgreSQL/MinIO integration.
For browser integration, start real infrastructure, seed accounts, run the API,
and export the three demo password variables into the test process:

```sh
cd apps/web
npx playwright install chromium
npm run test:e2e
```

Playwright starts the local Vite server. Tests use synthetic CSV fixtures; their
password environment must match the seeded accounts. Hosted application CI runs
API tests, frontend type/build checks, and this real-service browser journey.

## Continuous integration

Foundation CI runs on pull requests, pushes to `main`, and merge queue events.
The quality job checks POSIX shell syntax, ShellCheck, actionlint, and Compose
configuration. Application CI's combined foundation/seller integration job
exercises the existing Make interface in an
isolated Compose project, verifies repeated installation preserves `.env`, and
requires PostgreSQL and MinIO to be running and healthy. Failed runs collect
service logs; cleanup always attempts `make dev-stop`. Foundation and seller
checks share one infrastructure lifecycle, avoiding two cold MinIO compilations
on every pull request.

Checks use synthetic local configuration and read-only repository permissions.
They do not deploy an application or access production secrets. ShellCheck and
actionlint releases are pinned and their downloads verified with SHA-256.

## Future / not yet committed

- Production deployment workflow
- Production identity, signup, abuse/rate controls, schema migrations, expired
  session cleanup, and object lifecycle/retention policies
- x402/XRPL transaction architecture, entitlements, and buyer delivery
- JSON/Parquet adapters and finer-grained Resource views
