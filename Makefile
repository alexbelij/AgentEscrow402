.PHONY: run test lint format contracts clean

run:
	uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest -v

lint:
	ruff check .

format:
	black .
	ruff check . --fix

contracts:
	cd contracts/escrow && cargo build --release --target wasm32-unknown-unknown

contracts-test:
	cd contracts && cargo test

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
