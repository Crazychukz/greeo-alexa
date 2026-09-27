.DEFAULT_GOAL := up

COMPOSE := docker compose

.PHONY: up down logs migrate shell test lint format seed demo

up:
	@test -f .env || cp .env.example .env
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

migrate:
	$(COMPOSE) exec web python manage.py migrate

shell:
	$(COMPOSE) exec web python manage.py shell

test:
	@if $(COMPOSE) ps --status running --services | grep -qx postgres; then \
		$(COMPOSE) run --rm -e CELERY_TASK_ALWAYS_EAGER=true web pytest; \
	elif [ -x backend/.venv/bin/pytest ]; then \
		cd backend && .venv/bin/pytest; \
	else \
		$(COMPOSE) run --rm -e CELERY_TASK_ALWAYS_EAGER=true web pytest; \
	fi

lint:
	@if [ -x backend/.venv/bin/ruff ]; then \
		backend/.venv/bin/ruff check .; \
	else \
		$(COMPOSE) run --rm web ruff check .; \
	fi

format:
	@if [ -x backend/.venv/bin/ruff ]; then \
		backend/.venv/bin/ruff format .; \
	else \
		$(COMPOSE) run --rm web ruff format .; \
	fi

seed:
	@echo "Synthetic demo seeding is added in Prompt 2B."

demo:
	@echo "Curated demo loading is added in Prompt 2B."
