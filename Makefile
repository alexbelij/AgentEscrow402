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
