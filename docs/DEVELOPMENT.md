# Development

How development is intended to work. Contributor workflow is in [CONTRIBUTING.md](../CONTRIBUTING.md). Infrastructure constraints are in [agents/infrastructure.md](agents/infrastructure.md).

Commands listed under later headings are targets, not currently executable commands. Do not assume `make install`, `make dev-start`, or `make dev-stop` exist yet.

## Available now

Documentation and governance only.

There is no Make interface, Docker environment, CI, `.env.example`, or application runtime.

## Planned during M0

These are intended for the rest of repository foundation. They are not available yet:

- Reproducible, containerized local development
- Make interface: `make install`, `make dev-start`, `make dev-stop`
- Application dependencies isolated from contributor machines as much as practical
- `.env.example` once local configuration exists
- Baseline CI
- Application stack decision through an ADR

`make dev-stop` must never destroy development data. Destructive reset must be an explicit, separate operation. See [agents/infrastructure.md](agents/infrastructure.md).

## Future / not yet committed

- Production deployment workflow
