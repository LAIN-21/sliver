# Infrastructure

Additional constraints for infrastructure and local development changes. Repository-wide rules in [AGENTS.md](../../AGENTS.md) still apply.

- Change infrastructure only when the assigned GitHub Issue requests it.
- Keep local development reproducible.
- Prefer simple infrastructure over speculative infrastructure.
- Do not introduce Redis, Kafka, Kubernetes, queues, extra databases, or similar systems without a concrete requirement and an ADR.
- Local Compose topology is PostgreSQL and MinIO only, with named volumes `postgres_data` and `minio_data`.
- Public Make targets are `doctor`, `install`, `dev-start`, `dev-stop`, `dev-reset`, `ps`, and `logs`.
- `dev-stop` must never destroy development data or named volumes.
- `dev-reset` is the explicit, non-interactive destructive reset for local persisted state.
- Never commit secrets.
- Production infrastructure is currently secondary to excellent local development.

See [DEVELOPMENT.md](../DEVELOPMENT.md) for what exists now versus what is planned.
