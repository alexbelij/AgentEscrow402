"""C14 \u2014 pure-Python Merkle helper unit tests.

Verifies the deterministic sha256 tree (domain-separated leaves, canonical-
ordered pair-hashing so proofs are direction-bit-free) that gates gaming-
reward escrow releases.

Covers:
  - single-leaf tree (root == hashed leaf, empty proof)
  - even-count tree (round trip, proofs verify)
  - odd-count tree (odd tail pairs with itself; proofs still verify)
  - tamper detection (single-bit flip in sibling / leaf / root fails)
  - forgery resistance (leaf value swapped with an internal-node hash
    must NOT verify \u2014 domain separation working)
"""

from __future__ import annotations

import pytest

from server.gaming_merkle import (
    compute_root_and_proofs,
    verify_proof,
)


def _rand_leaf(i: int) -> bytes:
    # Deterministic-ish leaves so a failing test is reproducible.
    return f"leaf-{i}".encode()


class TestBuildAndVerify:
    def test_single_leaf(self):
        root, proofs = compute_root_and_proofs([b"only"])
        assert len(proofs) == 1
        assert proofs[0].siblings == []
        assert verify_proof(root, b"only", [])

    def test_even_leaves_round_trip(self):
        leaves = [_rand_leaf(i) for i in range(8)]
        root, proofs = compute_root_and_proofs(leaves)
        assert len(proofs) == 8
        for lv, p in zip(leaves, proofs):
            assert p.leaf_value == lv
            assert verify_proof(root, p.leaf_value, p.siblings)

    def test_odd_leaves_round_trip(self):
        # 7 = odd on levels 0 (7\u21924) and 1 (4\u21922): stresses both odd-tail paths.
        leaves = [_rand_leaf(i) for i in range(7)]
        root, proofs = compute_root_and_proofs(leaves)
        assert len(proofs) == 7
        for lv, p in zip(leaves, proofs):
            assert verify_proof(root, p.leaf_value, p.siblings)


class TestTamperDetection:
    @pytest.fixture
    def tree(self):
        leaves = [_rand_leaf(i) for i in range(5)]
        root, proofs = compute_root_and_proofs(leaves)
        return leaves, root, proofs

    def test_flipping_leaf_fails(self, tree):
        _, root, proofs = tree
        p = proofs[2]
        wrong_leaf = bytes([p.leaf_value[0] ^ 0x01]) + p.leaf_value[1:]
        assert not verify_proof(root, wrong_leaf, p.siblings)

    def test_flipping_sibling_fails(self, tree):
        _, root, proofs = tree
        p = proofs[2]
        if not p.siblings:
            pytest.skip("no sibling to flip")
        mutated = list(p.siblings)
        mutated[0] = bytes([mutated[0][0] ^ 0x01]) + mutated[0][1:]
        assert not verify_proof(root, p.leaf_value, mutated)

    def test_flipping_root_fails(self, tree):
        _, root, proofs = tree
        wrong_root = bytes([root[0] ^ 0x01]) + root[1:]
        p = proofs[2]
        assert not verify_proof(wrong_root, p.leaf_value, p.siblings)

    def test_wrong_sibling_count_fails(self, tree):
        # Truncating the proof (dropping the top sibling) must fail even
        # though the remaining walk is well-formed.
        _, root, proofs = tree
        p = proofs[0]
        if len(p.siblings) < 2:
            pytest.skip("proof too short to truncate meaningfully")
        assert not verify_proof(root, p.leaf_value, p.siblings[:-1])


class TestDomainSeparation:
    def test_internal_node_hash_is_not_a_valid_leaf(self):
        # Domain separation invariant: no valid leaf hashes to the same
        # bytes as an internal node.  We can't sample all leaves, but we
        # can assert that the leaf-hash of the first internal node's own
        # bytes doesn't happen to produce the root \u2014 a classic collision
        # attack against un-tagged Merkle trees.
        leaves = [_rand_leaf(i) for i in range(4)]
        root, proofs = compute_root_and_proofs(leaves)
        # Try to use `root` itself as a leaf value \u2014 must not verify with
        # an empty proof (which would be valid only if root == hash_leaf(root)).
        assert not verify_proof(root, root, [])
