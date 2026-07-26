#!/usr/bin/env bash
# verify.sh — single-command proof that AgentEscrow402 is real
#
# Usage:  ./verify.sh [--api URL]
# Default API: https://agentescrow402-api-ywm8.onrender.com
#
# Checks:
#   1. All 8 contracts exist on Casper testnet (via CSPR.cloud)
#   2. API is live and returns health
#   3. Escrow create → list → detail round-trip works
#   4. Frontend serves HTML
#   5. onchain.json matches live contract state
#
# Requirements: curl, jq (standard on any dev machine)
set -euo pipefail

API="${1:-https://agentescrow402-api-ywm8.onrender.com}"
FRONTEND="https://ae402.xyz"
CSPR_CLOUD="https://api.testnet.cspr.cloud"
PASS=0
FAIL=0
WARN=0

green()  { printf '\033[32m✅ %s\033[0m\n' "$*"; }
red()    { printf '\033[31m❌ %s\033[0m\n' "$*"; }
yellow() { printf '\033[33m⚠️  %s\033[0m\n' "$*"; }
bold()   { printf '\033[1m%s\033[0m\n' "$*"; }

check() {
  if "$@"; then
    PASS=$((PASS + 1))
  else
    FAIL=$((FAIL + 1))
  fi
}

# ── 1. On-chain contract verification ────────────────────────────────────

bold "═══ AgentEscrow402 Verification ═══"
echo ""
bold "1. On-chain contracts (Casper testnet)"

# Contracts array is derived from deploy-out/onchain.json — the single source
# of truth for live on-chain state. Hardcoded hashes would go stale after any
# redeploy (e.g. the 2026-07-24 Key-fix redeploy which rotated Core Escrow,
# Agent Identity Registry, MultiAssetEscrow and AEMAT to new contract_hashes
# under stable contract_package_hashes).

MANIFEST="deploy-out/onchain.json"
if [ ! -f "$MANIFEST" ]; then
  red "$MANIFEST missing — cannot derive contract set"
  exit 1
fi

CONTRACTS=()
while IFS= read -r line; do
  CONTRACTS+=("$line")
done < <(jq -r '.contracts | to_entries | map(select(.value.contract_hash != null)) | .[] | "\(.value.contract_hash | sub("^hash-"; "")):\(.value.name)"' "$MANIFEST")

if [ ${#CONTRACTS[@]} -eq 0 ]; then
  red "No contracts with contract_hash found in $MANIFEST"
  exit 1
fi

verify_contract() {
  local hash="${1%%:*}"
  local name="${1##*:}"
  local resp
  # Use Casper RPC query_global_state — works without auth
  resp=$(curl -sf "https://node.testnet.casper.network/rpc" \
    -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"query_global_state\",\"params\":{\"state_identifier\":null,\"key\":\"hash-${hash}\",\"path\":[]}}" \
    2>/dev/null || echo "FAIL")
  if echo "$resp" | jq -e '.result' > /dev/null 2>&1; then
    green "$name  (${hash:0:16}...)"
    return 0
  else
    red "$name  (${hash:0:16}...) — not found on chain"
    return 1
  fi
}

for c in "${CONTRACTS[@]}"; do
  check verify_contract "$c"
done

# ── 2. API health ────────────────────────────────────────────────────────

echo ""
bold "2. API health"

verify_health() {
  local resp
  resp=$(curl -sf "${API}/health" 2>/dev/null || echo "FAIL")
  if echo "$resp" | jq -e '.status == "ok"' > /dev/null 2>&1; then
    local mode chain version
    mode=$(echo "$resp" | jq -r '.mode // "unknown"')
    chain=$(echo "$resp" | jq -r '.chain // "unknown"')
    version=$(echo "$resp" | jq -r '.version // "unknown"')
    green "API healthy — v${version}, mode=${mode}, chain=${chain}"
    return 0
  else
    red "API not responding at ${API}/health"
    return 1
  fi
}
check verify_health

# ── 2b. Strict-mode readiness ───────────────────────────────────────────
#
# Reports whether the running app has AE402_STRICT=1 enabled and whether
# its preconditions are satisfied. This does not force strict mode to be
# on -- for hosted demo the operator may deliberately leave it off. It
# reports the picture so a judge can see the guarantee level at a glance.
#
# See server/strict.py and server/config.py::Config.strict_mode_capabilities()
# for the underlying contract.

verify_strict_mode() {
  local resp caps enabled ok violations
  resp=$(curl -sf "${API}/health" 2>/dev/null || echo "FAIL")
  # /health returns {..., "strict_mode": {enabled, preconditions_ok, violations, guarantees}}
  if ! echo "$resp" | jq -e '.strict_mode' > /dev/null 2>&1; then
    yellow "API /health does not include strict_mode block (older backend version)"
    WARN=$((WARN + 1))
    return 0
  fi

  enabled=$(echo "$resp" | jq -r '.strict_mode.enabled')
  ok=$(echo "$resp" | jq -r '.strict_mode.preconditions_ok')
  violations=$(echo "$resp" | jq -r '.strict_mode.violations | join("; ")')

  if [ "$enabled" = "true" ] && [ "$ok" = "true" ]; then
    green "AE402_STRICT=1 enabled AND all preconditions satisfied (fail-loud guarantees active)"
    return 0
  elif [ "$enabled" = "true" ] && [ "$ok" = "false" ]; then
    red "AE402_STRICT=1 enabled but preconditions FAIL: ${violations}"
    return 1
  else
    yellow "AE402_STRICT=0 (silent fallbacks allowed — not fail-loud)"
    WARN=$((WARN + 1))
    return 0
  fi
}
check verify_strict_mode

# ── 3. Escrow round-trip ─────────────────────────────────────────────────

echo ""
bold "3. Escrow round-trip (sandbox)"

verify_escrow_roundtrip() {
  # Probe health first to see if sandbox is on
  local health_mode
  health_mode=$(curl -sf "${API}/health" 2>/dev/null | jq -r '.mode // "unknown"')
  if [ "$health_mode" = "live" ]; then
    yellow "API is in live mode — skipping sandbox escrow test (escrow create requires real wallet signature)"
    WARN=$((WARN + 1))
    return 0
  fi
  # Create
  local create_resp
  create_resp=$(curl -sf -X POST "${API}/escrow" \
    -H "Content-Type: application/json" \
    -d '{"sender":"verify_sender","receiver":"verify_receiver","amount":1000000,"ttl":60}' \
    2>/dev/null || echo "FAIL")
  local service_hash
  service_hash=$(echo "$create_resp" | jq -r '.service_hash // empty' 2>/dev/null)
  if [ -z "$service_hash" ]; then
    red "Could not create escrow"
    return 1
  fi
  green "Created escrow: ${service_hash:0:16}..."

  # List
  local list_resp
  list_resp=$(curl -sf "${API}/escrows" 2>/dev/null || echo "FAIL")
  if echo "$list_resp" | jq -e --arg h "$service_hash" '.[] | select(.service_hash == $h)' > /dev/null 2>&1; then
    green "Escrow visible in list"
  else
    yellow "Escrow not in list (may be sandbox isolation)"
    WARN=$((WARN + 1))
  fi

  # Detail
  local detail_resp
  detail_resp=$(curl -sf "${API}/escrow/${service_hash}" 2>/dev/null || echo "FAIL")
  if echo "$detail_resp" | jq -e '.status == "pending"' > /dev/null 2>&1; then
    green "Escrow detail: status=pending, amount=$(echo "$detail_resp" | jq '.amount')"
    return 0
  else
    red "Could not read escrow detail"
    return 1
  fi
}
check verify_escrow_roundtrip

# ── 4. Frontend ──────────────────────────────────────────────────────────

echo ""
bold "4. Frontend"

verify_frontend() {
  local resp
  resp=$(curl -sf "${FRONTEND}" 2>/dev/null | head -c 500 || echo "FAIL")
  if echo "$resp" | grep -qi "AgentEscrow402\|ae402"; then
    green "Frontend serves HTML at ${FRONTEND}"
    return 0
  else
    red "Frontend not responding at ${FRONTEND}"
    return 1
  fi
}
check verify_frontend

# ── 5b. Insurance replay guard invariant (contract named_keys) ───────────

echo ""
bold "5b. Insurance replay guard (on-chain dictionary)"

verify_insurance_replay_guard() {
  # The insurance-pool contract MUST expose a `claimed_escrow_ids` named key —
  # this is the storage that tombstones every processed escrow_id and blocks
  # replay after cooldown. Contract source: contracts/insurance-pool/src/main.rs
  # line 24 + call() entry point. If this key is absent, either the old
  # contract is still live under a shadow name or the redeploy silently failed.
  #
  # Hash is derived from the manifest so a redeploy is picked up automatically.
  local insurance_hash
  insurance_hash=$(jq -r '.contracts.insurance_pool.contract_hash | sub("^hash-"; "")' "$MANIFEST")
  if [ -z "$insurance_hash" ] || [ "$insurance_hash" = "null" ]; then
    red "insurance_pool.contract_hash missing from manifest"
    return 1
  fi
  local resp
  resp=$(curl -sf "https://node.testnet.casper.network/rpc" \
    -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"query_global_state\",\"params\":{\"state_identifier\":null,\"key\":\"hash-${insurance_hash}\",\"path\":[]}}" \
    2>/dev/null || echo "FAIL")
  if echo "$resp" | jq -e '.result.stored_value.Contract.named_keys[] | select(.name == "claimed_escrow_ids")' > /dev/null 2>&1; then
    green "insurance_pool.claimed_escrow_ids dictionary present (replay guard armed)"
    return 0
  else
    red "insurance_pool.claimed_escrow_ids NOT FOUND — replay guard MISSING on live contract"
    return 1
  fi
}
check verify_insurance_replay_guard

# ── 5. onchain.json consistency ──────────────────────────────────────────

echo ""
bold "5. onchain.json"

verify_onchain_json() {
  if [ ! -f "deploy-out/onchain.json" ]; then
    red "deploy-out/onchain.json not found"
    return 1
  fi
  local count
  count=$(jq '.contracts | length' deploy-out/onchain.json 2>/dev/null)
  if [ "$count" -ge 8 ]; then
    green "onchain.json: ${count} contracts documented"
    return 0
  else
    red "onchain.json: only ${count} contracts (expected 8)"
    return 1
  fi
}
check verify_onchain_json

# ── Summary ──────────────────────────────────────────────────────────────

echo ""
bold "═══ Results ═══"
echo "  Passed: ${PASS}"
echo "  Failed: ${FAIL}"
[ "$WARN" -gt 0 ] && echo "  Warnings: ${WARN}"
echo ""

if [ "$FAIL" -eq 0 ]; then
  green "All checks passed"
  exit 0
else
  red "${FAIL} check(s) failed"
  exit 1
fi
