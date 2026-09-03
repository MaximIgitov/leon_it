.PHONY: backend-dev backend-test backend-lint migrate

backend-dev:
	cd backend && uv run uvicorn leonit.main:app --reload --host 0.0.0.0 --port 8000

backend-test:
	cd backend && uv run pytest -q

backend-lint:
	cd backend && uv run ruff check . && uv run ruff format --check .

migrate:
	cd backend && uv run alembic upgrade head
