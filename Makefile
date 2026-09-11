COMPOSE = docker compose --env-file .env -f compose.yml

ensure-env = test -f .env || cp .env.example .env

.PHONY: doctor install dev-start dev-stop dev-reset ps logs

doctor:
	sh scripts/doctor.sh

install: doctor
	@$(ensure-env)
	$(COMPOSE) pull

dev-start: install
	$(COMPOSE) up --wait

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
