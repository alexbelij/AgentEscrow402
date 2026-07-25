#!/usr/bin/env bash
# scripts/judge_demo.sh — one-command judge reproducibility demo (T1.1)
#
# Usage:
#   ./scripts/judge_demo.sh          # full demo (start network, deploy, run e2e, dump tx report)
#   ./scripts/judge_demo.sh --keep   # leave the local network running afterwards for inspection
#   ./scripts/judge_demo.sh --check  # preflight only — verify prerequisites, don't start network
#
# Time budget: ~5 minutes from clean clone (assuming Docker + Node + Python already installed).
# Output: a colored, judge-friendly report ending with a manifest of deploy hashes.

set -euo pipefail

# --------------------------------------------------------------------------
# 0. Colors & helpers (fall back to plain text if $NO_COLOR set / not a TTY)
# --------------------------------------------------------------------------
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  CLR_BOLD=$'\033[1m'; CLR_DIM=$'\033[2m'; CLR_GREEN=$'\033[32m'
  CLR_RED=$'\033[31m'; CLR_YELLOW=$'\033[33m'; CLR_BLUE=$'\033[34m'
  CLR_RESET=$'\033[0m'
else
  CLR_BOLD=""; CLR_DIM=""; CLR_GREEN=""; CLR_RED=""; CLR_YELLOW=""; CLR_BLUE=""; CLR_RESET=""
fi

hdr()   { echo; echo "${CLR_BOLD}${CLR_BLUE}== $* ==${CLR_RESET}"; }
ok()    { echo "${CLR_GREEN}✔${CLR_RESET} $*"; }
warn()  { echo "${CLR_YELLOW}⚠${CLR_RESET} $*"; }
fail()  { echo "${CLR_RED}✖${CLR_RESET} $*" >&2; }
info()  { echo "${CLR_DIM}$*${CLR_RESET}"; }

# --------------------------------------------------------------------------
# 1. Args
# --------------------------------------------------------------------------
KEEP_NETWORK=0
PREFLIGHT_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --keep)  KEEP_NETWORK=1 ;;
    --check) PREFLIGHT_ONLY=1 ;;
    -h|--help)
      grep -E '^# ' "$0" | sed 's/^# //'
      exit 0
      ;;
    *) fail "Unknown arg: $arg"; exit 2 ;;
  esac
done

# --------------------------------------------------------------------------
# 2. Preflight — every dependency we need with clear error messages
# --------------------------------------------------------------------------
hdr "Preflight — verifying host prerequisites"

MISSING=0
need() {
  if command -v "$1" >/dev/null 2>&1; then
    ok "$1 found ($(command -v "$1"))"
  else
    fail "$1 NOT FOUND — install: $2"
    MISSING=1
  fi
}

need docker         "https://docs.docker.com/get-docker/"
need docker-compose "https://docs.docker.com/compose/install/  (or use 'docker compose' plugin)"
need node           "https://nodejs.org  (v18 or v20 recommended)"
need python3        "https://www.python.org  (v3.10+ required)"
need pytest         "pip install -e '.[dev]'  (from repo root)"

# Repo layout sanity
for f in docker-compose.casper-nctl.yml scripts/nctl_keys.sh tests/integration/test_casper_nctl_e2e.py; do
  if [[ -f "$f" ]]; then
    ok "found $f"
  else
    fail "missing $f — are you at the repo root?"
    MISSING=1
  fi
done

# Node deps must be installed (casper-js-sdk)
if [[ -d node_modules/casper-js-sdk ]]; then
  ok "node_modules/casper-js-sdk installed"
else
  warn "casper-js-sdk not installed — running 'npm install' now"
  npm install --silent
  if [[ -d node_modules/casper-js-sdk ]]; then
    ok "casper-js-sdk installed"
  else
    fail "npm install did not produce node_modules/casper-js-sdk"
    MISSING=1
  fi
fi

if [[ $MISSING -eq 1 ]]; then
  fail "preflight failed — resolve above and re-run"
  exit 1
fi
ok "all prerequisites present"

if [[ $PREFLIGHT_ONLY -eq 1 ]]; then
  info "Preflight-only mode requested; exiting."
  exit 0
fi

# --------------------------------------------------------------------------
# 3. Start the local network
# --------------------------------------------------------------------------
hdr "Starting local Casper 2.0 network (NCTL)"

info "Compose file: docker-compose.casper-nctl.yml (5-node local network)"
docker-compose -f docker-compose.casper-nctl.yml up -d
info "Waiting up to 90s for the first block to be produced…"

deadline=$(( $(date +%s) + 90 ))
while :; do
  if curl -sS -X POST http://127.0.0.1:11101/rpc \
        -H 'content-type: application/json' \
        -d '{"jsonrpc":"2.0","id":1,"method":"info_get_status"}' \
        2>/dev/null | grep -q '"last_added_block_info"'; then
    ok "network is producing blocks"
    break
  fi
  if [[ $(date +%s) -ge $deadline ]]; then
    fail "network did not produce a block within 90s — check 'docker-compose logs casper-nctl'"
    exit 1
  fi
  echo -n "."
  sleep 3
done

# --------------------------------------------------------------------------
# 4. Pull faucet + user keys out of the container
# --------------------------------------------------------------------------
hdr "Extracting predefined faucet + user keys"

KEYS_DIR=$(mktemp -d)
info "Writing keys to $KEYS_DIR"
./scripts/nctl_keys.sh "$KEYS_DIR"
if [[ ! -f "$KEYS_DIR/faucet-secret_key.pem" ]]; then
  fail "faucet key not extracted — check scripts/nctl_keys.sh output"
  exit 1
fi
ok "faucet + user-1..user-3 keys ready in $KEYS_DIR"

# --------------------------------------------------------------------------
# 5. Run the end-to-end integration suite
# --------------------------------------------------------------------------
hdr "Running end-to-end escrow lifecycle against local network"

RESULTS=$(mktemp)
export NCTL_KEYS_DIR="$KEYS_DIR"
export NCTL_RPC_URL="http://127.0.0.1:11101/rpc"

if pytest tests/integration/ -m casper_net -v --tb=short 2>&1 | tee "$RESULTS"; then
  ok "all e2e tests passed"
else
  fail "e2e suite reported failures — see $RESULTS"
  if [[ $KEEP_NETWORK -eq 0 ]]; then
    docker-compose -f docker-compose.casper-nctl.yml down -v >/dev/null 2>&1 || true
  fi
  exit 1
fi

# --------------------------------------------------------------------------
# 6. Judge-facing summary report
# --------------------------------------------------------------------------
hdr "Reproducibility manifest — what you just verified"

cat <<EOF
${CLR_BOLD}Network:${CLR_RESET}   local Casper 2.0 (NCTL, 5-node, tmpfs-backed genesis)
${CLR_BOLD}RPC:${CLR_RESET}       $NCTL_RPC_URL
${CLR_BOLD}Keys:${CLR_RESET}      $NCTL_KEYS_DIR (faucet + user-1..user-3, predefined & deterministic)

${CLR_BOLD}Tests run:${CLR_RESET}
  1. RPC reachability (info_get_status)
  2. Block production (chain advances within 60s)
  3. Faucet balance parsing (Casper 2.0 main-purse read path)
  4. Predefined users are funded
  5. escrow_funder.wasm deploy → contract_hash returned
  6. Escrow lifecycle: create → get → release
  7. Escrow lifecycle: create → refund

${CLR_BOLD}What this proves:${CLR_RESET}
  ✔ The contracts in this repo build, deploy, and execute end-to-end on
    an unmodified Casper 2.0 network (same image the mainnet ships with).
  ✔ No mocks, no stubs — every RPC call is real.
  ✔ Same code path as the production API (server/casper_client.py).

${CLR_BOLD}For live testnet contracts (production evidence):${CLR_RESET}
  → see ${CLR_BLUE}TX_MANIFEST.md${CLR_RESET} for the 9 live contracts + 369+ deploys
  → see ${CLR_BLUE}docs/MOAT.md${CLR_RESET} for the "only-possible-on-Casper" argument
  → see ${CLR_BLUE}docs/CASPER_PRIMER.md${CLR_RESET} if you're new to Casper
EOF

# --------------------------------------------------------------------------
# 7. Teardown (or leave up)
# --------------------------------------------------------------------------
if [[ $KEEP_NETWORK -eq 1 ]]; then
  hdr "Leaving network up (--keep)"
  info "Stop it later with: docker-compose -f docker-compose.casper-nctl.yml down -v"
  info "RPC still open: $NCTL_RPC_URL"
  info "Keys still at: $KEYS_DIR"
else
  hdr "Tearing down local network"
  docker-compose -f docker-compose.casper-nctl.yml down -v >/dev/null 2>&1 || true
  rm -rf "$KEYS_DIR" || true
  ok "network stopped, keys wiped"
fi

echo
echo "${CLR_BOLD}${CLR_GREEN}Judge demo complete.${CLR_RESET}"
