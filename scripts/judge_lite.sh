#!/usr/bin/env bash
# scripts/judge_lite.sh — 60-second Python-only reproducibility demo (C1)
#
# Complements scripts/judge_demo.sh:
#   - judge_demo.sh → full on-chain flow (Docker + NCTL + WASM, ~5 min).
#   - judge_lite.sh → sandbox backend + SDK/CLI flow (Python only, ~60 s).
#
# Purpose: give a judge/reviewer/CI a way to prove the AE402 backend and CLI
# are wired end-to-end without any Docker, without any Casper node, without
# any testnet secrets. Just Python + pip + a free TCP port.
#
# Usage:
#   ./scripts/judge_lite.sh          # boot sandbox → run 5 CLI checks → tear down
#   ./scripts/judge_lite.sh --keep   # same, but leave uvicorn running for inspection
#   ./scripts/judge_lite.sh --check  # preflight only (Python + venv reachable)
#
# Exit codes:
#   0  everything green
#   1  a check failed (see stderr for which)
#   2  bad argument
#   3  preflight failed (missing Python 3.11+ / pip / uvicorn)

set -euo pipefail

# --------------------------------------------------------------------------
# 0. Colors
# --------------------------------------------------------------------------
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  CLR_BOLD=$'\033[1m'; CLR_DIM=$'\033[2m'; CLR_GREEN=$'\033[32m'
  CLR_RED=$'\033[31m'; CLR_YELLOW=$'\033[33m'; CLR_BLUE=$'\033[34m'
  CLR_RESET=$'\033[0m'
else
  CLR_BOLD=""; CLR_DIM=""; CLR_GREEN=""; CLR_RED=""; CLR_YELLOW=""; CLR_BLUE=""; CLR_RESET=""
fi

hdr()  { echo; echo "${CLR_BOLD}${CLR_BLUE}== $* ==${CLR_RESET}"; }
ok()   { echo "${CLR_GREEN}✔${CLR_RESET} $*"; }
warn() { echo "${CLR_YELLOW}⚠${CLR_RESET} $*"; }
fail() { echo "${CLR_RED}✖${CLR_RESET} $*" >&2; }
info() { echo "${CLR_DIM}$*${CLR_RESET}"; }

# --------------------------------------------------------------------------
# 1. Args
# --------------------------------------------------------------------------
KEEP=0
PREFLIGHT_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --keep)  KEEP=1 ;;
    --check) PREFLIGHT_ONLY=1 ;;
    -h|--help)
      grep -E '^# ' "$0" | sed 's/^# //'
      exit 0
      ;;
    *) fail "Unknown arg: $arg"; exit 2 ;;
  esac
done

# --------------------------------------------------------------------------
# 2. Preflight
# --------------------------------------------------------------------------
hdr "1/5  Preflight"

# Locate a Python 3.11+ that the project supports.
PY=""
for candidate in python3.11 python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    VER=$("$candidate" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
    MAJOR=${VER%.*}; MINOR=${VER#*.}
    if [[ "$MAJOR" -eq 3 && "$MINOR" -ge 11 ]]; then
      PY="$candidate"
      ok "Python: $candidate ($VER)"
      break
    fi
  fi
done
if [[ -z "$PY" ]]; then
  fail "Python 3.11+ not found on PATH. Install it (e.g. 'brew install python@3.11') and re-run."
  exit 3
fi

# Ensure server.app + sdk.cli import (they're pure-Python — if this fails the
# venv is not set up).
if ! "$PY" -c "import server.app, sdk.cli" 2>/dev/null; then
  warn "server / sdk not importable — installing requirements now."
  "$PY" -m pip install -q -r requirements.txt || {
    fail "pip install failed. Run 'pip install -r requirements.txt' manually and re-run."
    exit 3
  }
  ok "requirements installed"
else
  ok "server.app + sdk.cli importable"
fi

if [[ "$PREFLIGHT_ONLY" -eq 1 ]]; then
  ok "Preflight OK. Re-run without --check to boot the sandbox."
  exit 0
fi

# --------------------------------------------------------------------------
# 3. Pick a free port + boot sandbox uvicorn
# --------------------------------------------------------------------------
hdr "2/5  Boot sandbox backend"

PORT="${AE402_JUDGE_LITE_PORT:-}"
if [[ -z "$PORT" ]]; then
  PORT=$("$PY" - <<'PYEOF'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PYEOF
)
fi
info "Chosen port: $PORT"

LOGFILE=$(mktemp -t ae402-judge-lite.XXXXXX.log)
info "uvicorn log: $LOGFILE"

# Start in background. SANDBOX=true keeps /health sandbox=true (default anyway).
SANDBOX=true "$PY" -m uvicorn server.app:app \
  --host 127.0.0.1 --port "$PORT" --log-level warning \
  >"$LOGFILE" 2>&1 &
PID=$!
info "uvicorn pid: $PID"

cleanup() {
  if [[ "$KEEP" -eq 1 ]]; then
    warn "Leaving uvicorn running on http://127.0.0.1:$PORT (pid $PID)"
    warn "Kill it with:  kill $PID"
    return 0
  fi
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# Wait for /health to answer 200 (up to 15s).
BASE_URL="http://127.0.0.1:$PORT"
for i in {1..30}; do
  if "$PY" - "$BASE_URL" <<'PYEOF' >/dev/null 2>&1
import sys, urllib.request
u = sys.argv[1] + "/health"
try:
    with urllib.request.urlopen(u, timeout=1) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
PYEOF
  then
    ok "Sandbox ready on $BASE_URL"
    break
  fi
  sleep 0.5
  if [[ $i -eq 30 ]]; then
    fail "Sandbox never became healthy. Last 40 log lines:"
    tail -40 "$LOGFILE" >&2 || true
    exit 1
  fi
done

# --------------------------------------------------------------------------
# 4. Run 5 CLI checks
# --------------------------------------------------------------------------
hdr "3/5  CLI checks"

# Use `python -m sdk.cli` from the venv/PATH so we always test the current
# checkout, not a stale globally-installed `ae402` binary. The `ae402`
# entrypoint is a thin wrapper over the exact same module, so this is
# byte-equivalent to what a judge would run after `pip install -e .`.
CLI=("$PY" -m sdk.cli)
info "CLI: ${CLI[*]}"

# NOTE: `ae402` argparse requires global flags BEFORE the subcommand.
check() {
  local label="$1"; shift
  local out
  if out=$("${CLI[@]}" --api-url "$BASE_URL" --sandbox "$@" 2>&1); then
    ok "$label"
    echo "$out" | head -3 | sed 's/^/    /'
    return 0
  else
    fail "$label"
    echo "$out" | tail -20 | sed 's/^/    /' >&2
    return 1
  fi
}

FAIL=0
check "health         " health                                     || FAIL=1
check "stats          " stats                                      || FAIL=1
check "list-escrows   " list-escrows --limit 5                     || FAIL=1
check "mcp-tools      " mcp-tools                                  || FAIL=1
check "compute-hash   " compute-hash \
  --sender ab$(printf 'cd%.0s' {1..31}) \
  --receiver 12$(printf '34%.0s' {1..31}) \
  --amount 1000000 \
  --nonce test-nonce                                               || FAIL=1

# --------------------------------------------------------------------------
# 5. Summary + teardown
# --------------------------------------------------------------------------
hdr "4/5  Result"

if [[ "$FAIL" -eq 0 ]]; then
  ok "5/5 CLI checks passed against sandbox backend."
else
  fail "One or more checks failed. See stderr above."
  echo
  info "uvicorn log tail (40 lines):"
  tail -40 "$LOGFILE" >&2 || true
  exit 1
fi

hdr "5/5  Done"
if [[ "$KEEP" -eq 1 ]]; then
  ok "Sandbox left running on $BASE_URL — inspect with:"
  info "    curl -s $BASE_URL/health | jq"
  info "    ${CLI[*]} --api-url $BASE_URL --sandbox mcp-tools | jq"
else
  ok "Backend stopped, log at $LOGFILE (safe to delete)."
fi
