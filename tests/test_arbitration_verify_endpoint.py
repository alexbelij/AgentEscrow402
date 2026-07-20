"""End-to-end test for POST /arbitration/verify-evidence (AE-A2)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import app
from server.merkle_provenance import (
    EvidenceLeaf,
    build_inclusion_proof,
    compute_merkle_root,
    leaf_hash,
)


client = TestClient(app)


def _make_batch(n: int = 5) -> list[EvidenceLeaf]:
    return [
        EvidenceLeaf(
            claimant=("sender" if i % 2 == 0 else "receiver"),
            content_hash=f"c{i:02d}" * 16,  # 64 hex chars
            evidence_type="text",
            timestamp=str(1_700_000_000 + i),
        )
        for i in range(n)
    ]


def test_valid_proof_verifies():
    leaves = _make_batch(5)
    root = compute_merkle_root(leaves)
    proof = build_inclusion_proof(leaves, leaves[2].content_hash)
    assert proof is not None

    resp = client.post(
        "/arbitration/verify-evidence",
        json={
            "leaf": proof.leaf,
            "siblings": [{"hash": s.hash, "position": s.position} for s in proof.siblings],
            "expected_root": root,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["computed_root"] == root
    assert body["expected_root"] == root
    assert body["steps"] == len(proof.siblings)
    assert body["reason"] is None


def test_tampered_root_rejected():
    leaves = _make_batch(5)
    proof = build_inclusion_proof(leaves, leaves[1].content_hash)
    assert proof is not None
    bogus_root = "f" * 64

    resp = client.post(
        "/arbitration/verify-evidence",
        json={
            "leaf": proof.leaf,
            "siblings": [{"hash": s.hash, "position": s.position} for s in proof.siblings],
            "expected_root": bogus_root,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["expected_root"] == bogus_root
    assert body["reason"] == "computed_root != expected_root"


def test_wrong_leaf_rejected():
    leaves = _make_batch(5)
    root = compute_merkle_root(leaves)
    proof = build_inclusion_proof(leaves, leaves[2].content_hash)
    assert proof is not None

    # Swap leaf for something that's not in the batch:
    other_leaf = leaf_hash(EvidenceLeaf(claimant="x", content_hash="ff" * 32, evidence_type="text", timestamp="0"))

    resp = client.post(
        "/arbitration/verify-evidence",
        json={
            "leaf": other_leaf,
            "siblings": [{"hash": s.hash, "position": s.position} for s in proof.siblings],
            "expected_root": root,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False


def test_malformed_leaf_rejected():
    resp = client.post(
        "/arbitration/verify-evidence",
        json={"leaf": "not-hex", "siblings": [], "expected_root": "a" * 64},
    )
    assert resp.status_code == 400
    assert "leaf" in resp.json()["detail"]


def test_malformed_root_rejected():
    resp = client.post(
        "/arbitration/verify-evidence",
        json={"leaf": "a" * 64, "siblings": [], "expected_root": "short"},
    )
    assert resp.status_code == 400


def test_malformed_sibling_position_rejected():
    resp = client.post(
        "/arbitration/verify-evidence",
        json={
            "leaf": "a" * 64,
            "siblings": [{"hash": "b" * 64, "position": "middle"}],
            "expected_root": "c" * 64,
        },
    )
    assert resp.status_code == 400
    assert "position" in resp.json()["detail"]


def test_single_leaf_batch():
    """Edge case: a batch of one — root == leaf hash."""
    leaves = _make_batch(1)
    root = compute_merkle_root(leaves)
    proof = build_inclusion_proof(leaves, leaves[0].content_hash)
    assert proof is not None
    assert len(proof.siblings) == 0

    resp = client.post(
        "/arbitration/verify-evidence",
        json={"leaf": proof.leaf, "siblings": [], "expected_root": root},
    )
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


def test_all_positions_covered():
    """Batch of 4 exercises both 'left' and 'right' siblings."""
    leaves = _make_batch(4)
    root = compute_merkle_root(leaves)
    for i, lf in enumerate(leaves):
        proof = build_inclusion_proof(leaves, lf.content_hash)
        assert proof is not None
        resp = client.post(
            "/arbitration/verify-evidence",
            json={
                "leaf": proof.leaf,
                "siblings": [{"hash": s.hash, "position": s.position} for s in proof.siblings],
                "expected_root": root,
            },
        )
        assert resp.status_code == 200, f"leaf {i}: {resp.text}"
        assert resp.json()["valid"] is True, f"leaf {i} should verify"
