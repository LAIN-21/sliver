# ADR 0002: S3-compatible object storage

## Context

Issue #2 requires local object storage for dataset/object bytes and records an S3-compatible interface as Sliver's storage contract, with MinIO as the local implementation.

This ADR records a decision already approved by the task and repository owner. It does not independently originate the choice.

## Decision

S3-compatible object storage is the interface for dataset/object bytes, with MinIO used locally.

Local development runs MinIO via Docker Compose. See [DEVELOPMENT.md](../DEVELOPMENT.md).

## Alternatives Considered

- **Filesystem-only local storage.** Simple, poor parity with an object-storage production interface.
- **Cloud-native-only SDKs** (AWS, GCS, Azure APIs without an S3-compatible local stand-in). Locks a cloud provider too early.

## Consequences

- Local Compose infrastructure runs MinIO as an S3-compatible endpoint.
- Cloud provider selection remains open. See [ARCHITECTURE.md](../ARCHITECTURE.md).
- Application bucket bootstrap, object layout, and delivery remain out of scope until later issues.

This ADR does not decide bucket topology, object naming, retention, encryption, signed URLs, lifecycle policies, production provider, or delivery packaging.

## Status

Accepted
