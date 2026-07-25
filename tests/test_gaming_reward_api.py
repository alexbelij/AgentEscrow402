"""API tests for T3.2 gaming-reward escrow.

Covers the full HTTP flow:
    commit → lock → proof → claim (happy path)
    duplicate player in commit rejected
    lock without commit rejected
    lock with insolvent pool rejected
    double-claim rejected
    tampered claim rejected
    unknown escrow / unknown root rejected
    parallel claims for different players both succeed
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from server.app import app
from server.gaming_reward_api import _reset_state_for_tests


@pytest.fixture(autouse=True)
def _isolate_state():
    _reset_state_for_tests()
    yield
    _reset_state_for_tests()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _sample_leaves():
    return [
        {"player_id": "alice", "reward_amount": 1000, "rank": 1},
        {"player_id": "bob", "reward_amount": 500, "rank": 2},
        {"player_id": "carol", "reward_amount": 250, "rank": 3},
    ]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_full_flow_commit_lock_prove_claim(client: TestClient):
    # 1. Commit
    r = client.post("/gaming/commit", json={"round_id": "tournament-1", "leaves": _sample_leaves()})
    assert r.status_code == 200, r.text
    commit = r.json()
    assert commit["winners_count"] == 3
    assert commit["total_committed"] == 1750
    root = commit["root"]

    # 2. Lock prize pool
    r = client.post("/gaming/lock", json={"round_id": "tournament-1", "prize_pool_motes": 2000})
    assert r.status_code == 200, r.text
    lock = r.json()
    escrow_id = lock["escrow_id"]
    assert lock["root"] == root

    # 3. Alice fetches her proof
    r = client.get(f"/gaming/proof/{root}/alice")
    assert r.status_code == 200, r.text
    proof = r.json()
    assert proof["reward_amount"] == 1000

    # 4. Alice claims
    r = client.post("/gaming/claim", json={"escrow_id": escrow_id, "proof": proof})
    assert r.status_code == 200, r.text
    claim = r.json()
    assert claim["ok"] is True
    assert claim["amount_released"] == 1000
    assert claim["remaining_pool"] == 1000
    assert claim["reason"] == "ok"

    # 5. Escrow state reflects the claim
    r = client.get(f"/gaming/escrow/{escrow_id}")
    assert r.status_code == 200
    state = r.json()
    assert state["remaining_pool"] == 1000
    assert state["claimed_players"] == ["alice"]


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------


def test_commit_rejects_empty_sheet(client: TestClient):
    r = client.post("/gaming/commit", json={"round_id": "r", "leaves": []})
    assert r.status_code == 400


def test_commit_rejects_duplicate_player(client: TestClient):
    leaves = [
        {"player_id": "alice", "reward_amount": 100, "rank": 1},
        {"player_id": "alice", "reward_amount": 50, "rank": 2},
    ]
    r = client.post("/gaming/commit", json={"round_id": "r", "leaves": leaves})
    assert r.status_code == 400
    assert "duplicate" in r.json()["detail"]


def test_lock_without_commit_rejected(client: TestClient):
    r = client.post("/gaming/lock", json={"round_id": "ghost", "prize_pool_motes": 1000})
    assert r.status_code == 404


def test_lock_with_insolvent_pool_rejected(client: TestClient):
    client.post("/gaming/commit", json={"round_id": "r", "leaves": _sample_leaves()})  # 1750 total
    r = client.post("/gaming/lock", json={"round_id": "r", "prize_pool_motes": 1000})
    assert r.status_code == 400
    assert "insolvent" in r.json()["detail"]


def test_lock_twice_same_round_rejected(client: TestClient):
    client.post("/gaming/commit", json={"round_id": "r", "leaves": _sample_leaves()})
    r1 = client.post("/gaming/lock", json={"round_id": "r", "prize_pool_motes": 2000})
    assert r1.status_code == 200
    r2 = client.post("/gaming/lock", json={"round_id": "r", "prize_pool_motes": 2000})
    assert r2.status_code == 409


def test_proof_for_unknown_root_404(client: TestClient):
    r = client.get(f"/gaming/proof/{'f' * 64}/alice")
    assert r.status_code == 404


def test_proof_for_non_winner_404(client: TestClient):
    commit = client.post("/gaming/commit", json={"round_id": "r", "leaves": _sample_leaves()}).json()
    r = client.get(f"/gaming/proof/{commit['root']}/mallory")
    assert r.status_code == 404


def test_double_claim_rejected(client: TestClient):
    commit = client.post("/gaming/commit", json={"round_id": "r", "leaves": _sample_leaves()}).json()
    lock = client.post("/gaming/lock", json={"round_id": "r", "prize_pool_motes": 2000}).json()
    proof = client.get(f"/gaming/proof/{commit['root']}/bob").json()

    r1 = client.post("/gaming/claim", json={"escrow_id": lock["escrow_id"], "proof": proof})
    assert r1.status_code == 200
    assert r1.json()["ok"] is True

    r2 = client.post("/gaming/claim", json={"escrow_id": lock["escrow_id"], "proof": proof})
    assert r2.status_code == 200
    body = r2.json()
    assert body["ok"] is False
    assert body["reason"] == "already_claimed"


def test_tampered_claim_rejected(client: TestClient):
    commit = client.post("/gaming/commit", json={"round_id": "r", "leaves": _sample_leaves()}).json()
    lock = client.post("/gaming/lock", json={"round_id": "r", "prize_pool_motes": 2000}).json()
    proof = client.get(f"/gaming/proof/{commit['root']}/carol").json()
    proof["reward_amount"] = 99999  # inflate

    r = client.post("/gaming/claim", json={"escrow_id": lock["escrow_id"], "proof": proof})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["reason"] == "proof_invalid"


def test_claim_against_unknown_escrow_404(client: TestClient):
    commit = client.post("/gaming/commit", json={"round_id": "r", "leaves": _sample_leaves()}).json()
    proof = client.get(f"/gaming/proof/{commit['root']}/alice").json()
    r = client.post("/gaming/claim", json={"escrow_id": "ghost", "proof": proof})
    assert r.status_code == 404


def test_all_winners_can_claim_serially(client: TestClient):
    commit = client.post("/gaming/commit", json={"round_id": "r", "leaves": _sample_leaves()}).json()
    lock = client.post("/gaming/lock", json={"round_id": "r", "prize_pool_motes": 2000}).json()
    for player in ["alice", "bob", "carol"]:
        proof = client.get(f"/gaming/proof/{commit['root']}/{player}").json()
        r = client.post("/gaming/claim", json={"escrow_id": lock["escrow_id"], "proof": proof})
        assert r.status_code == 200
        assert r.json()["ok"] is True
    state = client.get(f"/gaming/escrow/{lock['escrow_id']}").json()
    assert state["remaining_pool"] == 250  # 2000 - 1750
    assert sorted(state["claimed_players"]) == ["alice", "bob", "carol"]


# ---------------------------------------------------------------------------
# Parallel claim safety (per-escrow lock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_claims_for_different_players_all_succeed(client: TestClient):
    commit = client.post("/gaming/commit", json={"round_id": "r", "leaves": _sample_leaves()}).json()
    lock = client.post("/gaming/lock", json={"round_id": "r", "prize_pool_motes": 2000}).json()
    escrow_id = lock["escrow_id"]

    proofs = {p: client.get(f"/gaming/proof/{commit['root']}/{p}").json() for p in ["alice", "bob", "carol"]}

    async def _claim(player: str):
        # TestClient is sync; call it from a thread so multiple claims
        # actually contend at the API layer.
        return await asyncio.to_thread(
            client.post, "/gaming/claim", json={"escrow_id": escrow_id, "proof": proofs[player]}
        )

    results = await asyncio.gather(_claim("alice"), _claim("bob"), _claim("carol"))
    for r in results:
        assert r.status_code == 200
        assert r.json()["ok"] is True

    state = client.get(f"/gaming/escrow/{escrow_id}").json()
    assert state["remaining_pool"] == 250
    assert sorted(state["claimed_players"]) == ["alice", "bob", "carol"]
