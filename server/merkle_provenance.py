"""Merkle provenance for arbitration evidence sets (AE-8).

Direct Python port of the RWA-Sentinel `merkleProvenance.ts` utility
(agent/src/data/merkleProvenance.ts). Semantics are identical:

  - Leaf hash: sha256("<claimant>:<content_hash>:<evidence_type>:<timestamp>")
  - Parent  : sha256(left || right)
  - If a level has an odd number of nodes, the last node is duplicated.
  - Empty batch has a well-defined root: sha256("empty").

A batch produces one root; anyone can independently verify that a
specific piece of evidence was part of the batch that the arbitrator
saw, given the root, without needing every individual evidence hash to
be pinned on-chain.

This module is intentionally dependency-free (only stdlib hashlib) and
deterministic — no wall-clock, no randomness, no I/O — so it can be
covered by golden vectors and be trivially reproduced in any language
(TS side is the RWA-S implementation).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Optional


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Leaf shape
# ---------------------------------------------------------------------------

# The arbitration domain differs from RWA-Sentinel invoices; we keep the
# same tree math but use an evidence-shaped leaf. A leaf's identity is
# `content_hash` — that's what makes two leaves "the same". This mirrors
# how the arbitration prompt de-duplicates by content_hash.


@dataclass(frozen=True)
class EvidenceLeaf:
    """One evidence item, minimally shaped for a Merkle leaf.

    All fields are strings so the leaf-hash pre-image is unambiguous
    across languages (no int width surprises). Timestamps come in as
    int, callers stringify.
    """

    claimant: str
    content_hash: str
    evidence_type: str
    timestamp: str


@dataclass(frozen=True)
class ProofStep:
    """One sibling on the path from a leaf to the root.

    `position` says whether THIS sibling sits on the left or right of
    the running hash during verification. Mirrors the TS port's
    'left' | 'right' union.
    """

    hash: str
    position: str  # "left" | "right"


@dataclass(frozen=True)
class MerkleInclusionProof:
    """Independently verifiable proof — the running hash starts at
    `leaf`, folds each step in, and must equal the claimed root."""

    leaf: str
    siblings: list[ProofStep]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def leaf_hash(leaf: EvidenceLeaf) -> str:
    """sha256("<claimant>:<content_hash>:<evidence_type>:<timestamp>")."""
    preimage = f"{leaf.claimant}:{leaf.content_hash}:{leaf.evidence_type}:{leaf.timestamp}"
    return _sha256_hex(preimage)


def _build_levels(leaf_hashes: list[str]) -> list[list[str]]:
    """From leaves (level 0) up to a single root (last level).

    Empty input yields [[sha256('empty')]] — matches TS reference so
    both sides agree on the "no evidence" root.
    """
    if not leaf_hashes:
        return [[_sha256_hex("empty")]]

    levels: list[list[str]] = [list(leaf_hashes)]
    current = list(leaf_hashes)
    while len(current) > 1:
        nxt: list[str] = []
        for i in range(0, len(current), 2):
            left = current[i]
            right = current[i + 1] if i + 1 < len(current) else current[i]  # duplicate last if odd
            nxt.append(_sha256_hex(left + right))
        levels.append(nxt)
        current = nxt
    return levels


def compute_merkle_root(leaves: Iterable[EvidenceLeaf]) -> str:
    hashes = [leaf_hash(lf) for lf in leaves]
    levels = _build_levels(hashes)
    return levels[-1][0]


def build_inclusion_proof(leaves: list[EvidenceLeaf], target_content_hash: str) -> Optional[MerkleInclusionProof]:
    """Proof that a leaf identified by its content_hash is in the batch.

    Returns None if the target is not present. Content_hash is the
    natural key on the arbitration side; two leaves with the same
    content_hash produce the same leaf hash and therefore the same
    position in the tree.
    """
    hashes = [leaf_hash(lf) for lf in leaves]
    try:
        target_index = next(i for i, lf in enumerate(leaves) if lf.content_hash == target_content_hash)
    except StopIteration:
        return None

    levels = _build_levels(hashes)
    siblings: list[ProofStep] = []
    index = target_index
    for level in range(len(levels) - 1):
        current_level = levels[level]
        is_right_node = index % 2 == 1
        sibling_index = index - 1 if is_right_node else index + 1
        if sibling_index < len(current_level):
            sibling_hash = current_level[sibling_index]
        else:
            sibling_hash = current_level[index]  # duplicated-last case
        siblings.append(ProofStep(hash=sibling_hash, position="left" if is_right_node else "right"))
        index //= 2
    return MerkleInclusionProof(leaf=hashes[target_index], siblings=siblings)


def verify_inclusion_proof(proof: MerkleInclusionProof, root: str) -> bool:
    """Fold the proof from leaf up; final hash must equal `root`.

    Runs the same math as the TS port; both must accept each other's
    proofs and reject tampered ones.
    """
    running = proof.leaf
    for step in proof.siblings:
        if step.position == "left":
            running = _sha256_hex(step.hash + running)
        elif step.position == "right":
            running = _sha256_hex(running + step.hash)
        else:
            return False  # malformed proof
    return running == root


__all__ = [
    "EvidenceLeaf",
    "ProofStep",
    "MerkleInclusionProof",
    "leaf_hash",
    "compute_merkle_root",
    "build_inclusion_proof",
    "verify_inclusion_proof",
]
