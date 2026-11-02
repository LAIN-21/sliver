# Reproducible MinIO source image for local development

## Status

Accepted on 2 November 2026 as the necessary repair discovered by issue #5's
first hosted integration run.

## Context

The existing pinned `minio/minio` Docker Hub image fails to pull. Anonymous Quay
access is also unavailable, and the historical binary checksum endpoint returns
HTTP 410. Upstream now documents source-only distribution. Keeping the removed
image would prevent both existing development and the new seller integration
from starting.

## Decision

Build the same local MinIO service from unmodified official upstream source in
`docker/minio/Dockerfile`, using a multistage build:

- Server module `github.com/minio/minio@v0.0.0-20251015172955-9e49d5e7a648`,
  the final upstream release `RELEASE.2025-10-15T17-29-55Z`.
- Client module `github.com/minio/mc@v0.0.0-20250813083541-7394ce0dd2a8`,
  release `RELEASE.2025-08-13T08-35-41Z`, for the existing readiness check.
- A pinned official Go builder image with its manifest digest. The Go proxy and
  public checksum database remain enabled; builds do not use a mutable branch.
- Static binaries in a scratch runtime, with certificates, timezone data,
  upstream licenses, and exact source attribution in `/licenses`.
- BuildKit caches and bounded compiler parallelism reduce repeat-install cost.

`make install` pulls non-buildable services and builds MinIO. Repeated calls reuse
the build cache. All public Make targets, the two-service topology, credentials,
loopback ports, readiness command, and named data volumes are preserved. No
production storage or external account is introduced.

## Alternatives Considered

- Retaining the old Docker Hub pin leaves a demonstrated clean-start failure.
- Quay and legacy official binary downloads were tested and unavailable.
- Unreviewed third-party forks or image mirrors would add a new source of trust.
- Replacing S3-compatible storage would expand the architecture and is not needed
  to repair local startup.

## Consequences

The first clean install now compiles Go dependencies and is slower than pulling
a prebuilt image. It requires network access to the official builder registry,
Go module proxy, and checksum database; subsequent builds are cached.

The pinned upstream code is archived and is a local development dependency.
Production storage, maintenance, update strategy, and deployment remain separate
decisions. This change repairs reproducibility; it does not claim ongoing
upstream maintenance.

## Sources

- [Upstream distribution documentation](https://github.com/minio/minio#source-only-distribution)
- [Pinned server source](https://github.com/minio/minio/tree/9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a)
- [Pinned client source](https://github.com/minio/mc/tree/7394ce0dd2a80935aded936b09fa12cbb3cb8096)
