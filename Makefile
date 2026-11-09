COMPOSE = docker compose --env-file .env -f compose.yml

ensure-env = test -f .env || cp .env.example .env

.PHONY: doctor install dev-start dev-stop dev-reset ps logs test lint migrate

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
	$(COMPOSE) run --rm api pytest

lint:
	@$(ensure-env)
	$(COMPOSE) run --rm --no-deps api sh -c "ruff check . && ruff format --check ."
	$(COMPOSE) run --rm --no-deps web npm run typecheck

migrate:
	@$(ensure-env)
	$(COMPOSE) run --rm api alembic upgrade head
