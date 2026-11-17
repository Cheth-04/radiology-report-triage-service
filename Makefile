.PHONY: up down status logs migrate test smoke
up:
	docker compose up --build -d
status:
	docker compose ps
migrate:
	docker compose run --rm migrate
test:
	docker compose run --rm -v "$(CURDIR)/tests:/code/tests:ro" api python -m pytest -q tests/
logs:
	docker compose logs --tail=80 api worker migrate
down:
	docker compose down
smoke:
	@echo "Run: python3 scripts/e2e_smoke.py --radiologist <email> --admin <email>"
