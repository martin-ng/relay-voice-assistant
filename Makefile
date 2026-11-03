.PHONY: setup run test evaluate check
setup:
	uv sync --frozen --extra test
run:
	uv run --frozen uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8765
test:
	uv run --frozen --extra test python -m pytest tests -q
evaluate:
	uv run --frozen python scripts/evaluate.py
check: test evaluate
	node --check app/static/app.js
