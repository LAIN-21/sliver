# Seller application and review boundary

## Status

Accepted for the local seller demonstration on 2 November 2026, following the
user's explicit choices of stack, scope, demo accounts, reviewer approval, and
whole-file Resource pricing. Production identity and transaction architecture
remain separate decisions.

## Context

Sliver has a PostgreSQL/MinIO development foundation but no application runtime.
The next useful slice lets a seller privately upload structured data and publish
a reviewed, priced Resource that external buyers can discover. The buyer agent
and payment system remain outside this implementation.

## Decision

- Use Python/FastAPI and SQLAlchemy for the API and PostgreSQL metadata. Use
  boto3 against S3-compatible storage for private uploaded bytes.
- Use TypeScript/React with Vite for the UI. The local Vite server proxies `/api`
  to the loopback API, keeping browser requests same-origin.
- Run the applications on the supported development host. Existing Compose
  services and Make targets remain unchanged; no new infrastructure is added.
- Explicitly seed two sellers and a distinct reviewer with environment-supplied
  passwords. Passwords are hashed; opaque, expiring sessions live server-side.
  Cookies are HttpOnly and SameSite, and every mutation requires a CSRF token
  and an allowed Origin. This is local demo authentication, not public signup.
- A valid upload creates an immutable CSV version with its original SHA-256.
  This slice accepts UTF-8 CSV up to 5 MiB, 10,000 data rows, and 100 columns.
  Deterministic checks establish structural quality, not truth or ownership.
- A Resource references one whole uploaded version and a positive integer
  price in USD minor units. No arbitrary SQL, FX, or dynamic pricing is accepted.
- A seller creates a draft and submits it. Only the reviewer may approve and
  publish or reject it with a reason. Rejection is terminal; correction requires
  a new draft. Approval is a review event, not a factual guarantee.
- Public discovery uses an explicit metadata-only response schema. Original
  bytes, private previews, filenames, storage keys, and rights declarations are
  never included. Public provenance contains only the seller's declared source,
  method, collection date, and coverage, with no claim of independent validation.
- SQLite and in-memory storage may be injected by tests only. Runtime
  configuration continues to require PostgreSQL and S3-compatible storage.

## Alternatives Considered

- A single TypeScript/Next.js application would reduce language boundaries;
  the user selected a Python backend with a React/TypeScript frontend instead.
- Production identity and public signup would support external deployment but
  add provider and operational decisions outside this local demonstration.
- Seller self-publication is quicker but omits the distinct rights-review gate.
- Arbitrary filtered Resources introduce query execution and finer entitlement
  questions. Whole immutable CSV versions make the first boundary explicit.
- Porting the Ledger402 prototype would couple marketplace responsibilities to
  buyer spending decisions and is outside the task.

## Consequences

The team can test the complete seller-to-catalog journey without payments or
external identity services. API and UI contracts must be verified across two
languages. Schema initialization is a local baseline; production migrations,
identity, rate limiting, session maintenance, storage lifecycle, reviewer
processes, and operational controls require follow-up before public hosting.

A listed price does not mean a Resource can yet be purchased. No payment,
entitlement, buyer delivery, deployment, or ownership verification is implemented
by this decision. The original transaction ADR remains open.
