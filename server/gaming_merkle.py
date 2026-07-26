"""C14: Merkle-tree utilities for gaming-reward escrows.

Deterministic sha256 Merkle tree with the following, ossified conventions:

  * Leaves are hashed as `sha256(b"leaf:" || value)` \u2014 the prefix domain-
    separates leaves from internal nodes so a valid proof can never be
    forged by presenting a mid-tree hash as a leaf.
  * Internal nodes are `sha256(b"node:" || left || right)` and we always
    keep the pair in canonical order (`min(l, r) || max(l, r)`) so proofs
    do not have to carry a per-step direction bit.
  * When a level has an odd number of nodes the last one is paired with
    itself.  This is the same convention Bitcoin / Casper use.

The verifier is pure Python and streams the proof in one pass so it is
safe to call inline from a hot request handler.

The tree is small on purpose \u2014 gaming payouts rarely exceed a few hundred
winners \u2014 so we do not add persistence or caching here.  A caller that
needs to serve many proofs precomputes them once via `compute_root_and_proofs`.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

_LEAF_TAG = b"leaf:"
_NODE_TAG = b"node:"


def _hash_leaf(value: bytes) -> bytes:
    return sha256(_LEAF_TAG + value).digest()


def _hash_pair(a: bytes, b: bytes) -> bytes:
    lo, hi = (a, b) if a <= b else (b, a)
    return sha256(_NODE_TAG + lo + hi).digest()


@dataclass(frozen=True)
class MerkleProof:
    """One inclusion proof.  `siblings` is bottom-up."""

    leaf_value: bytes
    siblings: list[bytes]

    def to_hex_dict(self) -> dict[str, object]:
        return {
            "leaf_hex": self.leaf_value.hex(),
            "siblings_hex": [s.hex() for s in self.siblings],
        }


def compute_root_and_proofs(leaves: list[bytes]) -> tuple[bytes, list[MerkleProof]]:
    """Build the tree and every inclusion proof in one pass.

    Empty list \u2192 root is 32 zero bytes; no proofs.  Duplicate leaves are
    allowed \u2014 the caller keeps the semantics (e.g. a single receiver
    winning multiple payouts).
    """
    if not leaves:
        return b"\x00" * 32, []

    # Hash the leaves and remember original indices so we can build proofs.
    level = [_hash_leaf(v) for v in leaves]
    # For every node we keep the list of sibling hashes that will end up
    # in the proof for the ORIGINAL leaf whose sub-tree includes it.
    proof_siblings: list[list[bytes]] = [[] for _ in leaves]
    # Which original-leaf indices sit under each current-level node.
    covered: list[list[int]] = [[i] for i in range(len(leaves))]

    while len(level) > 1:
        next_level: list[bytes] = []
        next_covered: list[list[int]] = []
        for i in range(0, len(level), 2):
            left = level[i]
            left_owners = covered[i]
            if i + 1 < len(level):
                right = level[i + 1]
                right_owners = covered[i + 1]
            else:
                right = left  # odd tail: pair with self
                right_owners = []  # nobody new
            parent = _hash_pair(left, right)
            # Each original leaf under `left` needs `right` as a sibling,
            # and vice-versa.
            for owner in left_owners:
                proof_siblings[owner].append(right)
            for owner in right_owners:
                proof_siblings[owner].append(left)
            next_level.append(parent)
            next_covered.append(left_owners + right_owners)
        level = next_level
        covered = next_covered

    root = level[0]
    proofs = [MerkleProof(leaf_value=leaves[i], siblings=proof_siblings[i]) for i in range(len(leaves))]
    return root, proofs


def verify_proof(root: bytes, leaf_value: bytes, siblings: list[bytes]) -> bool:
    """Constant-work verification of an inclusion proof.

    We do NOT need a direction bit thanks to the canonical `min || max`
    pair-hashing convention above.  A caller that mangles the proof \u2014
    reordering, injecting an extra hash, swapping a sibling \u2014 walks off
    the tree and computes a root that does not match.
    """
    h = _hash_leaf(leaf_value)
    for sib in siblings:
        h = _hash_pair(h, sib)
    return h == root
