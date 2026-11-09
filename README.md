# Sliver

Sliver is infrastructure and a marketplace that lets data owners turn datasets into granular, machine-purchasable Resources for external AI agents.

This repository is in early development. The whole stack runs locally in Docker:

```bash
make dev-start
```

Then open http://127.0.0.1:5173. Details are in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Buy with your agent (MCP)

The free, open-source [Sliver MCP](packages/sliver-mcp/README.md) lets any agent search Sliver, check whether data fits its need, and buy it with x402 on the XRP Ledger Testnet within a budget you set. It runs on your machine and pays sellers directly; your wallet seed never leaves it.

```bash
uvx --from "git+https://github.com/LAIN-21/sliver#subdirectory=packages/sliver-mcp" sliver-mcp wallet init
claude mcp add sliver -- uvx --from "git+https://github.com/LAIN-21/sliver#subdirectory=packages/sliver-mcp" sliver-mcp
```

Claude Desktop and Cursor configuration, tools, spending limits and settings are in [packages/sliver-mcp/README.md](packages/sliver-mcp/README.md).

## Start here

- Product: [docs/PRODUCT.md](docs/PRODUCT.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Development: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md)
- Contributors: [CONTRIBUTING.md](CONTRIBUTING.md)
- Coding agents: [AGENTS.md](AGENTS.md)

Licensed under the [Apache License 2.0](LICENSE).
