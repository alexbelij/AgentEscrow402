.PHONY: run test lint format contracts clean judge-demo judge-demo-check judge-demo-keep

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
	cd contracts/agent-identity-registry && cargo build --release --target wasm32-unknown-unknown

contracts-test:
	cd contracts && cargo test

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage

# --- Judge / auditor reproducibility ---------------------------------------
# Boots a local Casper 2.0 NCTL network, deploys escrow_funder.wasm, runs the
# full escrow lifecycle end-to-end (create → release, create → refund), and
# emits a summary manifest. ~5 minutes on a clean clone.
#
#   make judge-demo         # full run: boot → deploy → e2e → summary → teardown
#   make judge-demo-keep    # same, but leave the local network running for inspection
#   make judge-demo-check   # preflight only: verify Docker + Node + Python are ready
judge-demo:
	./scripts/judge_demo.sh

judge-demo-keep:
	./scripts/judge_demo.sh --keep

judge-demo-check:
	./scripts/judge_demo.sh --check

# --- C16: TLA+ formal spec ------------------------------------------------
# Downloads the TLA+ toolbox to /tmp on first run then model-checks the
# escrow FSM (docs/formal/AE402Escrow.tla). Requires a JDK on PATH.
tla-check:
	@if [ ! -f /tmp/tla2tools.jar ]; then \
	    echo '>>> downloading TLA+ toolbox'; \
	    curl -sL -o /tmp/tla2tools.jar \
	      https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar; \
	fi
	cd docs/formal && java -cp /tmp/tla2tools.jar tlc2.TLC \
	    -config AE402Escrow.cfg AE402Escrow.tla | tee /tmp/tlc.log; \
	grep -q "Model checking completed. No error has been found." /tmp/tlc.log
