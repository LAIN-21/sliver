# Infrastructure

Additional constraints for infrastructure and local development changes. Repository-wide rules in [AGENTS.md](../../AGENTS.md) still apply.

- Change infrastructure only when the assigned GitHub Issue requests it.
- Keep local development reproducible.
- Prefer simple infrastructure over speculative infrastructure.
- Do not introduce Redis, Kafka, Kubernetes, queues, extra databases, or similar systems without a concrete requirement and an ADR. Background jobs use PostgreSQL ([ADR 0003](../adr/0003-application-stack-and-local-containers.md)).
- Local Compose topology is `postgres`, `minio`, `api`, `worker` and `web`, with named volumes `postgres_data` and `minio_data`.
- Every published port binds to 127.0.0.1.
- MinIO is built from the pinned upstream source in `docker/minio/Dockerfile`; do not switch to unreviewed images or mirrors.
- Public Make targets are `doctor`, `install`, `dev-start`, `dev-stop`, `dev-reset`, `ps`, `logs`, `test`, `lint`, `migrate`, `seed`, `wallets` and `smoke-testnet`.
- `dev-stop` must never destroy development data or named volumes.
- `dev-reset` is the explicit, non-interactive destructive reset for local persisted state.
- `install` must never overwrite an existing `.env`, and new variables need defaults so older `.env` files keep working.
- Never commit secrets.
- Production infrastructure is currently secondary to excellent local development.

See [DEVELOPMENT.md](../DEVELOPMENT.md) for what exists now versus what is planned.
