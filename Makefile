.PHONY: run test lint lint-fix format check contracts clean judge-demo judge-demo-check judge-demo-keep judge-lite judge-lite-check judge-lite-keep

run:
	uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest -v

# Mirrors CI lint-and-test job's Ruff + Black gates exactly, so a green
# `make lint` locally guarantees a green CI lint gate. Black runs first
# because a formatter miss is the more common failure mode.
lint:
	python -m black --check --line-length 120 .
	python -m ruff check .

# Local auto-fix pass -- safe to run before committing; both tools are
# deterministic and only touch style, never semantics.
lint-fix:
	python -m black --line-length 120 .
	python -m ruff check . --fix

# Legacy alias kept for muscle memory. Prefer `make lint-fix`.
format: lint-fix

# Full pre-push gate: lint + tests. Matches the CI job's shape.
check: lint test

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

# --- Judge / auditor lite (Python only, ~60 s) -----------------------------
# Complements judge-demo: boots the sandbox backend + runs 5 CLI checks,
# no Docker, no NCTL, no testnet secrets required.
#
#   make judge-lite         # full 60-s pass: boot sandbox → 5 CLI checks → tear down
#   make judge-lite-keep    # leave uvicorn running on 127.0.0.1:<port> for inspection
#   make judge-lite-check   # preflight only (Python 3.11+, requirements)
judge-lite:
	./scripts/judge_lite.sh

judge-lite-keep:
	./scripts/judge_lite.sh --keep

judge-lite-check:
	./scripts/judge_lite.sh --check

# --- C12: libFuzzer smoke over pure-Rust stubs -----------------------------
# Each target runs for 30s. See contracts/fuzz/README.md for the target list
# and how to run longer campaigns.
fuzz:
	cd contracts/fuzz && for t in flash_guard_hold_period flash_guard_block_delay \
	                                flash_guard_both_halves escrow_types_status \
	                                threshold_config_validate; do \
	    echo "=== $$t ==="; \
	    cargo fuzz run "$$t" -- -max_total_time=30 -print_final_stats=1 || exit 1; \
	done

fuzz-build:
	cd contracts/fuzz && cargo fuzz build
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
