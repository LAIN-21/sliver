COMPOSE = docker compose --env-file .env -f compose.yml

ensure-env = test -f .env || cp .env.example .env

EXAMPLES = -v $(CURDIR)/examples:/examples:ro

.PHONY: doctor install dev-start dev-stop dev-reset ps logs test lint migrate seed wallets smoke-testnet demo

doctor:
	sh scripts/doctor.sh

install: doctor
	@$(ensure-env)
	$(COMPOSE) pull postgres
	$(COMPOSE) build

dev-start: install
	$(COMPOSE) up --wait --renew-anon-volumes

dev-stop:
	@$(ensure-env)
	$(COMPOSE) down

dev-reset:
	@$(ensure-env)
	$(COMPOSE) down --volumes --remove-orphans

ps:
	@$(ensure-env)
	$(COMPOSE) ps

logs:
	@$(ensure-env)
	$(COMPOSE) logs --tail=200

test:
	@$(ensure-env)
	$(COMPOSE) run --rm $(EXAMPLES) -e SLIVER_EXAMPLES_DIR=/examples/datasets api pytest

lint:
	@$(ensure-env)
	$(COMPOSE) run --rm --no-deps api sh -c "ruff check . && ruff format --check ."
	$(COMPOSE) run --rm --no-deps web npm run typecheck

migrate:
	@$(ensure-env)
	$(COMPOSE) run --rm api alembic upgrade head

seed:
	@$(ensure-env)
	$(COMPOSE) run --rm $(EXAMPLES) api python -m sliver_api.seed /examples/datasets

wallets:
	@$(ensure-env)
	$(COMPOSE) run --rm -v $(CURDIR):/repo api python -m sliver_api.payments.wallets /repo/.env /repo/examples/datasets/manifest.toml

smoke-testnet:
	@$(ensure-env)
	$(COMPOSE) run --rm -v $(CURDIR)/.env:/repo/.env:ro api python -m sliver_api.payments.smoke /repo/.env http://api:8000

# The whole story on XRPL Testnet: seller upload, pipeline, valuation and publish, then the Sliver
# MCP's buyer code for a question Sliver can't answer and one it buys. Writes the validated
# transactions into README.md between the demo-tx markers. Never resets or deletes data.
# `wallets` sets payout addresses on the seeded sellers, so it runs after `seed`, also under -j.
demo:
	$(MAKE) seed
	$(MAKE) wallets
	$(COMPOSE) run --rm \
		-v $(CURDIR)/.env:/repo/.env:ro \
		-v $(CURDIR)/README.md:/repo/README.md \
		-v $(CURDIR)/scripts:/repo/scripts:ro \
		-v $(CURDIR)/examples:/repo/examples:ro \
		-v $(CURDIR)/packages:/repo/packages:ro \
		-e PYTHONPATH=/repo/packages/sliver-mcp/src:/repo/packages/sliver-x402/src \
		api python /repo/scripts/sliver_demo.py --api http://api:8000 --env /repo/.env --readme /repo/README.md
