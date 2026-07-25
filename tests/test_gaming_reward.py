"""Tests for gaming-reward escrow (T3.2).

Coverage:
    * Deterministic commit + golden vectors.
    * Round-trip proof for every position (odd/even sheet sizes).
    * Empty sheet has stable well-defined root.
    * Tampering with amount / player / rank all fail verification.
    * Sibling injection / malformed proof fail cleanly.
    * `evaluate_claim` handles duplicate claim, over-pool, invalid proof.
    * Property test: any player from any random sheet always verifies.
"""

from __future__ import annotations

from dataclasses import replace

import hashlib

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from server.gaming_reward import (
    ClaimResult,
    ProofStep,
    RewardInclusionProof,
    RewardLeaf,
    build_claim_proof,
    commit_results,
    evaluate_claim,
    leaf_hash,
    verify_claim,
)


# ---------------------------------------------------------------------------
# Determinism / golden vectors
# ---------------------------------------------------------------------------


def test_leaf_hash_is_deterministic():
    lf = RewardLeaf("alice", 1000, 1)
    assert leaf_hash(lf) == leaf_hash(lf)
    assert leaf_hash(lf) == hashlib.sha256("alice:1000:1".encode()).hexdigest()


def test_leaf_hash_differs_by_field():
    a = leaf_hash(RewardLeaf("alice", 1000, 1))
    assert a != leaf_hash(RewardLeaf("alicE", 1000, 1))  # player_id
    assert a != leaf_hash(RewardLeaf("alice", 1001, 1))  # amount
    assert a != leaf_hash(RewardLeaf("alice", 1000, 2))  # rank


def test_commit_empty_sheet_stable_root():
    c = commit_results([])
    assert c.winners_count == 0
    assert c.total_committed == 0
    assert c.root == hashlib.sha256("empty-rewards".encode()).hexdigest()


def test_commit_totals_are_sum_of_amounts():
    leaves = [RewardLeaf(f"p{i}", i * 100, i) for i in range(1, 6)]
    c = commit_results(leaves)
    assert c.total_committed == 100 + 200 + 300 + 400 + 500
    assert c.winners_count == 5


def test_commit_root_is_stable_across_runs():
    leaves = [RewardLeaf("alice", 1000, 1), RewardLeaf("bob", 500, 2)]
    r1 = commit_results(leaves).root
    r2 = commit_results(leaves).root
    assert r1 == r2


# ---------------------------------------------------------------------------
# Round-trip proofs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("size", [1, 2, 3, 4, 5, 8, 9, 16, 17, 33])
def test_round_trip_every_position(size):
    leaves = [RewardLeaf(f"player{i}", (i + 1) * 10, i + 1) for i in range(size)]
    c = commit_results(leaves)
    for lf in leaves:
        proof = build_claim_proof(leaves, lf.player_id)
        assert proof is not None, f"missing proof for {lf.player_id}"
        assert verify_claim(proof, c.root), f"proof failed at size={size} player={lf.player_id}"


def test_single_winner_proof_has_no_siblings():
    leaves = [RewardLeaf("solo", 1000, 1)]
    c = commit_results(leaves)
    p = build_claim_proof(leaves, "solo")
    assert p is not None
    assert p.siblings == []
    assert verify_claim(p, c.root)


def test_missing_player_returns_none():
    leaves = [RewardLeaf("alice", 100, 1), RewardLeaf("bob", 50, 2)]
    assert build_claim_proof(leaves, "mallory") is None


def test_first_occurrence_wins_on_duplicate_player_id():
    # If a caller passes the same player twice, `build_claim_proof`
    # picks the first slot. Callers who want multi-slot claims should
    # use distinct player_ids per slot (documented in the module).
    leaves = [
        RewardLeaf("alice", 100, 1),
        RewardLeaf("alice", 50, 2),
    ]
    c = commit_results(leaves)
    p = build_claim_proof(leaves, "alice")
    assert p is not None
    assert p.reward_amount == 100
    assert p.rank == 1
    assert verify_claim(p, c.root)


# ---------------------------------------------------------------------------
# Tampering fails
# ---------------------------------------------------------------------------


def _sample_sheet():
    return [
        RewardLeaf("alice", 1000, 1),
        RewardLeaf("bob", 500, 2),
        RewardLeaf("carol", 250, 3),
        RewardLeaf("dave", 100, 4),
        RewardLeaf("erin", 50, 5),
    ]


def test_amount_inflation_fails():
    leaves = _sample_sheet()
    c = commit_results(leaves)
    p = build_claim_proof(leaves, "carol")
    tampered = replace(p, reward_amount=99999)
    assert verify_claim(tampered, c.root) is False


def test_player_id_swap_fails():
    leaves = _sample_sheet()
    c = commit_results(leaves)
    p = build_claim_proof(leaves, "carol")
    tampered = replace(p, player_id="mallory")
    assert verify_claim(tampered, c.root) is False


def test_rank_swap_fails():
    leaves = _sample_sheet()
    c = commit_results(leaves)
    p = build_claim_proof(leaves, "carol")
    tampered = replace(p, rank=1)
    assert verify_claim(tampered, c.root) is False


def test_sibling_injection_fails():
    leaves = _sample_sheet()
    c = commit_results(leaves)
    p = build_claim_proof(leaves, "bob")
    # Inject a bogus sibling at position 0
    bad = replace(p, siblings=[ProofStep(hash="0" * 64, position="left")] + list(p.siblings)[1:])
    assert verify_claim(bad, c.root) is False


def test_malformed_position_fails():
    leaves = _sample_sheet()
    c = commit_results(leaves)
    p = build_claim_proof(leaves, "bob")
    if not p.siblings:
        pytest.skip("no siblings to malform")
    bad = replace(p, siblings=[replace(p.siblings[0], position="middle")] + list(p.siblings[1:]))
    assert verify_claim(bad, c.root) is False


def test_wrong_root_fails():
    leaves = _sample_sheet()
    p = build_claim_proof(leaves, "alice")
    assert verify_claim(p, "f" * 64) is False


def test_cross_sheet_proof_fails():
    """A proof from sheet A must not verify against root of sheet B."""
    sheet_a = _sample_sheet()
    sheet_b = [RewardLeaf("alice", 1000, 1), RewardLeaf("bob", 500, 2)]
    c_b = commit_results(sheet_b)
    p_a = build_claim_proof(sheet_a, "alice")
    assert verify_claim(p_a, c_b.root) is False


# ---------------------------------------------------------------------------
# evaluate_claim (escrow-integration surface)
# ---------------------------------------------------------------------------


def test_evaluate_claim_happy_path():
    leaves = _sample_sheet()
    c = commit_results(leaves)
    p = build_claim_proof(leaves, "bob")
    r = evaluate_claim(p, c.root, set(), 5000)
    assert r.ok is True
    assert r.amount_to_release == 500
    assert r.reason == "ok"


def test_evaluate_claim_double_claim():
    leaves = _sample_sheet()
    c = commit_results(leaves)
    p = build_claim_proof(leaves, "bob")
    r = evaluate_claim(p, c.root, {"bob"}, 5000)
    assert r.ok is False
    assert r.reason == "already_claimed"


def test_evaluate_claim_exceeds_pool():
    leaves = _sample_sheet()
    c = commit_results(leaves)
    p = build_claim_proof(leaves, "alice")  # amount 1000
    r = evaluate_claim(p, c.root, set(), 500)  # pool only 500 left
    assert r.ok is False
    assert r.reason == "exceeds_pool"


def test_evaluate_claim_invalid_proof():
    leaves = _sample_sheet()
    c = commit_results(leaves)
    p = build_claim_proof(leaves, "alice")
    bad = replace(p, reward_amount=9999)
    r = evaluate_claim(bad, c.root, set(), 100000)
    assert r.ok is False
    assert r.reason == "proof_invalid"


# ---------------------------------------------------------------------------
# Property: random sheet → every player verifies
# ---------------------------------------------------------------------------


@given(
    players=st.lists(
        st.tuples(
            st.text(min_size=1, max_size=32, alphabet=st.characters(min_codepoint=33, max_codepoint=126)),
            st.integers(min_value=1, max_value=10**9),
            st.integers(min_value=1, max_value=1000),
        ),
        min_size=1,
        max_size=30,
        unique_by=lambda t: t[0],  # unique player_id
    )
)
@settings(max_examples=50, deadline=None)
def test_property_all_winners_verify(players):
    leaves = [RewardLeaf(pid, amt, rk) for (pid, amt, rk) in players]
    c = commit_results(leaves)
    for lf in leaves:
        p = build_claim_proof(leaves, lf.player_id)
        assert p is not None
        assert verify_claim(p, c.root)


@given(
    players=st.lists(
        st.tuples(
            st.text(min_size=1, max_size=8, alphabet=st.characters(min_codepoint=97, max_codepoint=122)),
            st.integers(min_value=1, max_value=1000),
            st.integers(min_value=1, max_value=100),
        ),
        min_size=2,
        max_size=15,
        unique_by=lambda t: t[0],
    ),
    tamper_amount=st.integers(min_value=1, max_value=10**9),
)
@settings(max_examples=30, deadline=None)
def test_property_amount_tampering_always_fails(players, tamper_amount):
    leaves = [RewardLeaf(pid, amt, rk) for (pid, amt, rk) in players]
    c = commit_results(leaves)
    p = build_claim_proof(leaves, leaves[0].player_id)
    if p.reward_amount == tamper_amount:
        return  # not a tamper if amount matches
    tampered = replace(p, reward_amount=tamper_amount)
    assert verify_claim(tampered, c.root) is False
