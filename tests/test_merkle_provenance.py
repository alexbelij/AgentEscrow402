"""Tests for server/merkle_provenance.py — AE-8.

Covers:
  1. Determinism of the root.
  2. Sensitivity to any leaf change.
  3. Odd- and even-sized batches.
  4. Empty batch has a defined root.
  5. Every leaf produces a valid, independently-verifiable inclusion proof.
  6. Proofs don't verify against a tampered root or a different batch's root.
  7. Missing target returns None.
  8. Cross-language parity against RWA-Sentinel TS reference (golden vectors).
  9. Malformed proof step is rejected.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from server.merkle_provenance import (
    EvidenceLeaf,
    MerkleInclusionProof,
    ProofStep,
    build_inclusion_proof,
    compute_merkle_root,
    leaf_hash,
    verify_inclusion_proof,
)


def _mk_leaves(n: int) -> list[EvidenceLeaf]:
    return [
        EvidenceLeaf(
            claimant=f"alice-{i}",
            content_hash=f"hash-{i}",
            evidence_type=("text" if i % 2 == 0 else "hash"),
            timestamp=str(1_700_000_000 + i),
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# 1-4: shape / edge cases
# ---------------------------------------------------------------------------


def test_root_is_deterministic() -> None:
    leaves = _mk_leaves(5)
    assert compute_merkle_root(leaves) == compute_merkle_root(leaves)


def test_root_changes_when_any_leaf_changes() -> None:
    leaves = _mk_leaves(5)
    original_root = compute_merkle_root(leaves)
    mutated = list(leaves)
    mutated[2] = EvidenceLeaf(
        claimant=leaves[2].claimant,
        content_hash=leaves[2].content_hash,
        evidence_type=leaves[2].evidence_type,
        timestamp="9999999999",  # perturb timestamp only
    )
    assert compute_merkle_root(mutated) != original_root


@pytest.mark.parametrize("n", [1, 3, 5, 7, 9])
def test_odd_batch_sizes_do_not_throw(n: int) -> None:
    compute_merkle_root(_mk_leaves(n))  # must not raise


@pytest.mark.parametrize("n", [2, 4, 6, 8])
def test_even_batch_sizes_do_not_throw(n: int) -> None:
    compute_merkle_root(_mk_leaves(n))


def test_empty_batch_has_defined_root() -> None:
    # Matches TS ref: sha256('empty').
    r = compute_merkle_root([])
    import hashlib

    expected = hashlib.sha256(b"empty").hexdigest()
    assert r == expected


# ---------------------------------------------------------------------------
# 5-7: proof correctness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 2, 3, 5, 8, 10])
def test_every_leaf_has_a_valid_inclusion_proof(n: int) -> None:
    leaves = _mk_leaves(n)
    root = compute_merkle_root(leaves)
    for leaf in leaves:
        proof = build_inclusion_proof(leaves, leaf.content_hash)
        assert proof is not None
        assert verify_inclusion_proof(proof, root) is True


def test_proof_does_not_verify_against_tampered_root() -> None:
    leaves = _mk_leaves(4)
    root = compute_merkle_root(leaves)
    proof = build_inclusion_proof(leaves, "hash-1")
    assert proof is not None
    tampered = root[:-2] + "00" if not root.endswith("00") else root[:-2] + "ff"
    assert verify_inclusion_proof(proof, tampered) is False


def test_proof_from_one_batch_does_not_verify_against_a_different_root() -> None:
    leaves_a = _mk_leaves(6)
    leaves_b = [
        EvidenceLeaf(
            claimant=lf.claimant,
            content_hash=lf.content_hash + "-x",
            evidence_type=lf.evidence_type,
            timestamp=lf.timestamp,
        )
        for lf in leaves_a
    ]
    root_b = compute_merkle_root(leaves_b)
    proof_a = build_inclusion_proof(leaves_a, "hash-3")
    assert proof_a is not None
    assert verify_inclusion_proof(proof_a, root_b) is False


def test_missing_target_returns_none() -> None:
    leaves = _mk_leaves(4)
    assert build_inclusion_proof(leaves, "hash-not-present") is None


# ---------------------------------------------------------------------------
# 8: cross-language golden vectors (RWA-Sentinel TS reference)
# ---------------------------------------------------------------------------

_GOLDEN_PATH = pathlib.Path(__file__).parent / "fixtures" / "merkle_golden_vectors.json"


@pytest.mark.parametrize("vector_index", range(7))
def test_root_matches_ts_reference_golden_vectors(vector_index: int) -> None:
    """Roots computed by this module must byte-equal the RWA-Sentinel
    TypeScript implementation's roots on the same leaves.

    Vectors regenerated from `merkleProvenance.ts` via the tiny helper
    at tests/fixtures/README.md — never edit by hand.
    """
    vectors = json.loads(_GOLDEN_PATH.read_text())
    v = vectors[vector_index]
    leaves = [EvidenceLeaf(**lf) for lf in v["leaves"]]
    computed = compute_merkle_root(leaves)
    assert computed == v["root"], f"n={v['n']}: python root {computed} != ts root {v['root']}"


# ---------------------------------------------------------------------------
# 9: malformed proof rejection
# ---------------------------------------------------------------------------


def test_malformed_proof_step_position_is_rejected() -> None:
    """A proof whose step has a position that isn't 'left'/'right' must
    return False, not silently accept."""
    leaves = _mk_leaves(4)
    root = compute_merkle_root(leaves)
    real = build_inclusion_proof(leaves, "hash-0")
    assert real is not None
    bad = MerkleInclusionProof(
        leaf=real.leaf,
        siblings=[ProofStep(hash=real.siblings[0].hash, position="middle")] + list(real.siblings[1:]),
    )
    assert verify_inclusion_proof(bad, root) is False


def test_leaf_hash_is_stable() -> None:
    """Byte-exact leaf hash on a known leaf so the pre-image format never
    silently drifts."""
    import hashlib

    leaf = EvidenceLeaf(claimant="alice", content_hash="ch1", evidence_type="text", timestamp="1700000000")
    expected = hashlib.sha256(b"alice:ch1:text:1700000000").hexdigest()
    assert leaf_hash(leaf) == expected
