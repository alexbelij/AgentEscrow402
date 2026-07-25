"""API tests for the HTLC bridge-mock (T3.4-A).

Uses FastAPI TestClient against `server.app.app`. Each test resets the
default in-memory registry to avoid cross-test bleed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server import bridge_htlc as htlc
from server.app import app


@pytest.fixture(autouse=True)
def _reset_registry():
    htlc.reset_default_registry()
    yield
    htlc.reset_default_registry()


client = TestClient(app)


T0 = 1_700_000_000_000


def _initiate_body(hashlock_hex: str, casper_t: int = T0 + 3600_000, evm_t: int = T0 + 1800_000):
    return {
        "hashlock_hex": hashlock_hex,
        "casper_initiator": "casper-alice",
        "casper_counterparty": "casper-bob",
        "casper_amount": 1_000_000,
        "casper_timelock_ms": casper_t,
        "evm_initiator": "0xEvmBob",
        "evm_counterparty": "0xEvmAlice",
        "evm_amount": 500_000,
        "evm_timelock_ms": evm_t,
        "now_ms": T0,
    }


# ── /preimage/new ─────────────────────────────────────────────────────


def test_preimage_new_endpoint_returns_matching_pair():
    r = client.post("/bridge/htlc/preimage/new")
    assert r.status_code == 200
    body = r.json()
    assert len(body["preimage_hex"]) == 64
    # sha256(preimage) == hashlock
    assert htlc.compute_hashlock(bytes.fromhex(body["preimage_hex"])) == body["hashlock_hex"]


# ── /initiate ─────────────────────────────────────────────────────────


def test_initiate_creates_swap_201():
    p = htlc.new_preimage()
    r = client.post("/bridge/htlc/initiate", json=_initiate_body(htlc.compute_hashlock(p)))
    assert r.status_code == 201
    body = r.json()
    assert body["casper_leg"]["status"] == "proposed"
    assert body["evm_leg"]["status"] == "proposed"
    assert body["hashlock_hex"] == htlc.compute_hashlock(p)


def test_initiate_rejects_bad_timelock_ordering_409():
    p = htlc.new_preimage()
    body = _initiate_body(htlc.compute_hashlock(p), casper_t=T0 + 1000, evm_t=T0 + 2000)
    r = client.post("/bridge/htlc/initiate", json=body)
    assert r.status_code == 400  # validation error → 400
    detail = r.json()["detail"]
    assert detail["code"] == "timelock_ordering"


def test_initiate_rejects_duplicate_409():
    p = htlc.new_preimage()
    body = _initiate_body(htlc.compute_hashlock(p))
    r1 = client.post("/bridge/htlc/initiate", json=body)
    assert r1.status_code == 201
    r2 = client.post("/bridge/htlc/initiate", json=body)
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "leg_already_exists"


def test_initiate_rejects_bad_hashlock_400():
    body = _initiate_body("dead")
    r = client.post("/bridge/htlc/initiate", json=body)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_hashlock"


def test_initiate_rejects_zero_amount_422():
    p = htlc.new_preimage()
    body = _initiate_body(htlc.compute_hashlock(p))
    body["casper_amount"] = 0
    r = client.post("/bridge/htlc/initiate", json=body)
    # pydantic gt=0 → 422
    assert r.status_code == 422


# ── /lock ─────────────────────────────────────────────────────────────


def test_lock_leg_ok():
    p = htlc.new_preimage()
    init = client.post("/bridge/htlc/initiate", json=_initiate_body(htlc.compute_hashlock(p))).json()
    leg_id = init["evm_leg"]["leg_id"]
    r = client.post(f"/bridge/htlc/legs/{leg_id}/lock", json={"now_ms": T0})
    assert r.status_code == 200
    assert r.json()["status"] == "locked"
    assert r.json()["lock_tx_hash"] is not None


def test_lock_unknown_leg_404():
    r = client.post("/bridge/htlc/legs/does-not-exist/lock", json={"now_ms": T0})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "unknown_leg"


def test_lock_after_timelock_409():
    p = htlc.new_preimage()
    body = _initiate_body(htlc.compute_hashlock(p), casper_t=T0 + 5000, evm_t=T0 + 3000)
    init = client.post("/bridge/htlc/initiate", json=body).json()
    leg_id = init["evm_leg"]["leg_id"]
    r = client.post(f"/bridge/htlc/legs/{leg_id}/lock", json={"now_ms": T0 + 10_000})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "timelock_expired"


# ── /claim ────────────────────────────────────────────────────────────


def test_claim_with_correct_preimage_ok():
    p = htlc.new_preimage()
    init = client.post("/bridge/htlc/initiate", json=_initiate_body(htlc.compute_hashlock(p))).json()
    leg_id = init["evm_leg"]["leg_id"]
    client.post(f"/bridge/htlc/legs/{leg_id}/lock", json={"now_ms": T0})
    r = client.post(
        f"/bridge/htlc/legs/{leg_id}/claim",
        json={"preimage_hex": p.hex(), "now_ms": T0 + 100},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "claimed"
    assert body["preimage_hex"] == p.hex()
    assert body["claim_tx_hash"] is not None


def test_claim_with_wrong_preimage_400():
    p = htlc.new_preimage()
    init = client.post("/bridge/htlc/initiate", json=_initiate_body(htlc.compute_hashlock(p))).json()
    leg_id = init["evm_leg"]["leg_id"]
    client.post(f"/bridge/htlc/legs/{leg_id}/lock", json={"now_ms": T0})
    r = client.post(
        f"/bridge/htlc/legs/{leg_id}/claim",
        json={"preimage_hex": "aa" * 32, "now_ms": T0 + 100},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "preimage_mismatch"


def test_double_claim_409():
    p = htlc.new_preimage()
    init = client.post("/bridge/htlc/initiate", json=_initiate_body(htlc.compute_hashlock(p))).json()
    leg_id = init["evm_leg"]["leg_id"]
    client.post(f"/bridge/htlc/legs/{leg_id}/lock", json={"now_ms": T0})
    client.post(f"/bridge/htlc/legs/{leg_id}/claim", json={"preimage_hex": p.hex(), "now_ms": T0 + 100})
    r = client.post(f"/bridge/htlc/legs/{leg_id}/claim", json={"preimage_hex": p.hex(), "now_ms": T0 + 200})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "already_claimed"


def test_claim_before_lock_409():
    p = htlc.new_preimage()
    init = client.post("/bridge/htlc/initiate", json=_initiate_body(htlc.compute_hashlock(p))).json()
    leg_id = init["evm_leg"]["leg_id"]
    r = client.post(f"/bridge/htlc/legs/{leg_id}/claim", json={"preimage_hex": p.hex(), "now_ms": T0})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "not_locked"


# ── /refund ───────────────────────────────────────────────────────────


def test_refund_after_timelock_ok():
    p = htlc.new_preimage()
    body = _initiate_body(htlc.compute_hashlock(p), casper_t=T0 + 5000, evm_t=T0 + 3000)
    init = client.post("/bridge/htlc/initiate", json=body).json()
    leg_id = init["evm_leg"]["leg_id"]
    client.post(f"/bridge/htlc/legs/{leg_id}/lock", json={"now_ms": T0})
    r = client.post(f"/bridge/htlc/legs/{leg_id}/refund", json={"now_ms": T0 + 3000})
    assert r.status_code == 200
    assert r.json()["status"] == "refunded"


def test_refund_before_timelock_409():
    p = htlc.new_preimage()
    body = _initiate_body(htlc.compute_hashlock(p), casper_t=T0 + 5000, evm_t=T0 + 3000)
    init = client.post("/bridge/htlc/initiate", json=body).json()
    leg_id = init["evm_leg"]["leg_id"]
    client.post(f"/bridge/htlc/legs/{leg_id}/lock", json={"now_ms": T0})
    r = client.post(f"/bridge/htlc/legs/{leg_id}/refund", json={"now_ms": T0 + 2999})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "timelock_not_expired"


# ── GET endpoints ────────────────────────────────────────────────────


def test_get_leg_ok_and_404():
    p = htlc.new_preimage()
    init = client.post("/bridge/htlc/initiate", json=_initiate_body(htlc.compute_hashlock(p))).json()
    leg_id = init["casper_leg"]["leg_id"]
    r = client.get(f"/bridge/htlc/legs/{leg_id}")
    assert r.status_code == 200
    assert r.json()["leg_id"] == leg_id
    r2 = client.get("/bridge/htlc/legs/nope")
    assert r2.status_code == 404


def test_get_swap_summary_and_atomic_outcome():
    p = htlc.new_preimage()
    init = client.post("/bridge/htlc/initiate", json=_initiate_body(htlc.compute_hashlock(p))).json()
    swap_id = init["swap_id"]
    # in_progress before any locks
    s0 = client.get(f"/bridge/htlc/swaps/{swap_id}/summary").json()
    assert s0["atomic_outcome"] == "in_progress"
    assert s0["safety_violation"] is False
    # after full happy path → completed
    client.post(f"/bridge/htlc/legs/{init['casper_leg']['leg_id']}/lock", json={"now_ms": T0})
    client.post(f"/bridge/htlc/legs/{init['evm_leg']['leg_id']}/lock", json={"now_ms": T0})
    client.post(
        f"/bridge/htlc/legs/{init['evm_leg']['leg_id']}/claim",
        json={"preimage_hex": p.hex(), "now_ms": T0 + 100},
    )
    client.post(
        f"/bridge/htlc/legs/{init['casper_leg']['leg_id']}/claim",
        json={"preimage_hex": p.hex(), "now_ms": T0 + 200},
    )
    s1 = client.get(f"/bridge/htlc/swaps/{swap_id}/summary").json()
    assert s1["atomic_outcome"] == "completed"
    assert s1["revealed_preimage_hex"] == p.hex()


def test_list_swaps():
    for i in range(3):
        p = bytes([i + 1]) * 32
        body = _initiate_body(htlc.compute_hashlock(p))
        client.post("/bridge/htlc/initiate", json=body)
    r = client.get("/bridge/htlc/swaps")
    assert r.status_code == 200
    assert len(r.json()) == 3


def test_get_unknown_swap_404():
    r = client.get("/bridge/htlc/swaps/does-not-exist")
    assert r.status_code == 404
    r2 = client.get("/bridge/htlc/swaps/does-not-exist/summary")
    assert r2.status_code == 404
