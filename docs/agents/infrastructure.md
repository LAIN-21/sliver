# Infrastructure

Additional constraints for infrastructure and local development changes. Repository-wide rules in [AGENTS.md](../../AGENTS.md) still apply.

- Change infrastructure only when the assigned GitHub Issue requests it.
- Keep local development reproducible.
- Prefer simple infrastructure over speculative infrastructure.
- Do not introduce Redis, Kafka, Kubernetes, queues, extra databases, or similar systems without a concrete requirement and an ADR.
- `dev-stop` must never destroy development data.
- Destructive reset operations must be explicit and separately requested.
- Never commit secrets.
- Production infrastructure is currently secondary to excellent local development.

See [DEVELOPMENT.md](../DEVELOPMENT.md) for what exists now versus what is planned.
