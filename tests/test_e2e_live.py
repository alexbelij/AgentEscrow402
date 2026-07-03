"""
E2E integration tests against live Render backend.
Non-sandbox mode: POST /escrow requires X-Payment header → 401 is expected.
All other endpoints tested for correct response.
"""
import hashlib
import time
import httpx

BASE = "https://agentescrow402-api.onrender.com"
client = httpx.Client(timeout=45)

passed = 0
failed = 0
errors: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        msg = f"FAIL {name}: {detail}"
        errors.append(msg)
        print(f"  ❌ {msg}")


def api(method, path, **kwargs):
    r = client.request(method, BASE + path, **kwargs)
    ct = r.headers.get("content-type", "")
    body = r.json() if "application/json" in ct else r.text
    return r.status_code, body


# ── 1. Health ─────────────────────────────────────────────────────────────────
print("\n=== 1. Health ===")
code, body = api("GET", "/health")
check("GET /health → 200", code == 200, f"got {code}")
check("health.status = ok", isinstance(body, dict) and body.get("status") == "ok", str(body)[:80])
check("health.sandbox = false", isinstance(body, dict) and body.get("sandbox") is False)
check("health.chain = casper-test", isinstance(body, dict) and body.get("chain") == "casper-test")
check("health.contract_hash present", isinstance(body, dict) and bool(body.get("contract_hash")))


# ── 2. Stats endpoint ─────────────────────────────────────────────────────────
print("\n=== 2. Stats ===")
code, body = api("GET", "/stats")
check("GET /stats → 200", code == 200, f"got {code} body={str(body)[:120]}")


# ── 3. Escrow create — non-sandbox requires X-Payment → 401 expected ──────────
print("\n=== 3. POST /escrow (auth) ===")
sh = hashlib.sha256(f"e2e-{int(time.time())}".encode()).hexdigest()
payload = {
    "receiver": "account-hash-" + "b" * 64,
    "amount": 5_000_000_000,
    "service_hash": sh,
    "ttl": 3600,
}
code, body = api("POST", "/escrow", json=payload)
# Non-sandbox: no X-Payment header → 401 Unauthorized (expected)
check("POST /escrow without auth → 401", code == 401,
      f"got {code} (expected 401 in live non-sandbox mode) body={str(body)[:120]}")


# ── 4. GET /escrow (list) ─────────────────────────────────────────────────────
print("\n=== 4. GET /escrows ===")
code, body = api("GET", "/escrows")
check("GET /escrows → 200", code == 200, f"got {code} body={str(body)[:120]}")
check("GET /escrows returns list", isinstance(body, (list, dict)), str(type(body)))


# ── 5. Compute hash ───────────────────────────────────────────────────────────
print("\n=== 5. Compute hash ===")
code, body = api("POST", "/compute-hash", params={
    "sender": "account-hash-" + "a" * 64,
    "receiver": "account-hash-" + "b" * 64,
    "amount": 1000000000,
    "nonce": "e2e-nonce-001"
})
check("GET /compute-hash → 200", code == 200, f"got {code}")
check("compute-hash.service_hash is hex64",
      isinstance(body, dict) and len(body.get("service_hash", "")) == 64)


# ── 6. VRF Election ───────────────────────────────────────────────────────────
print("\n=== 6. VRF Election ===")
vrf_payload = {
    "dispute_id": f"e2e-dispute-{int(time.time())}",
    "sender": "account-hash-" + "a" * 64,
    "receiver": "account-hash-" + "b" * 64,
    "seed_hash": hashlib.sha256(b"e2e-seed").hexdigest(),
}
code, body = api("POST", "/vrf/elect", json=vrf_payload)
check("POST /vrf/elect → 201", code == 201, f"got {code} body={str(body)[:200]}")
check("vrf.elected_arbiter present",
      isinstance(body, dict) and "elected_arbiter" in body, str(list(body.keys()) if isinstance(body, dict) else body))
check("vrf.dispute_id matches",
      isinstance(body, dict) and body.get("dispute_id") == vrf_payload["dispute_id"])
check("vrf.election_proof present",
      isinstance(body, dict) and bool(body.get("election_proof")))


# ── 7. Risk score ─────────────────────────────────────────────────────────────
print("\n=== 7. Risk Score ===")
agent = "account-hash-" + "a" * 64
code, body = api("GET", f"/risk/score/{agent}")
check("GET /risk/score/{agent} → 200", code == 200, f"got {code} body={str(body)[:200]}")
if isinstance(body, dict):
    check("risk.risk_score 0-100",
          isinstance(body.get("risk_score"), int) and 0 <= body["risk_score"] <= 100,
          str(body.get("risk_score")))
    check("risk.agent matches", body.get("agent") == agent)


# ── 8. Risk dashboard ─────────────────────────────────────────────────────────
print("\n=== 8. Risk Dashboard ===")
code, body = api("GET", "/risk/dashboard")
check("GET /risk/dashboard → 200", code == 200, f"got {code} body={str(body)[:200]}")
if isinstance(body, dict):
    check("dashboard.total_agents present", "total_agents" in body)
    check("dashboard.avg_risk_score present", "avg_risk_score" in body)


# ── 9. Reputation ─────────────────────────────────────────────────────────────
print("\n=== 9. Reputation ===")
code, body = api("GET", f"/reputation/{agent}")
check("GET /reputation/{agent} → 200", code == 200, f"got {code} body={str(body)[:200]}")
if isinstance(body, dict):
    check("reputation.score present", "score" in body or "completed" in body)


# ── 10. Agents list ──────────────────────────────────────────────────────────
print("\n=== 10. Agents ===")
code, body = api("GET", "/agents")
check("GET /agents → 200", code == 200, f"got {code}")


# ── 11. Arbitration — requires auth in non-sandbox ────────────────────────────
print("\n=== 11. POST /arbitration/analyze (auth) ===")
arb_payload = {
    "dispute_id": f"e2e-arb-{int(time.time())}",
    "service_hash": hashlib.sha256(b"svc-arb").hexdigest(),
    "sender_evidence": ["Paid full amount on time"],
    "receiver_evidence": ["Delivered all deliverables"],
    "escrow_amount": 500_000_000_000,
}
code, body = api("POST", "/arbitration/analyze", json=arb_payload)
# May be 200 (auth not required for arbitration) or 401/422
check("POST /arbitration/analyze → 200 or 401",
      code in (200, 201, 401, 422),
      f"got {code} body={str(body)[:200]}")
if code in (200, 201) and isinstance(body, dict):
    check("arbitration.recommendation present",
          "recommendation" in body or "dispute_id" in body,
          str(list(body.keys())))


# ── Summary ───────────────────────────────────────────────────────────────────
total = passed + failed
print(f"\n{'=' * 60}")
print(f"  E2E RESULTS: {passed}/{total} PASSED  |  {failed} FAILED")
print(f"{'=' * 60}")
if errors:
    print("\nFailed:")
    for e in errors:
        print(f"  {e}")

# Exit 1 if any failures
if failed:
    import sys
    sys.exit(1)
