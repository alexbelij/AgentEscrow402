"""Gaming-reward escrow with Merkle proof of results (T3.2).

Enables trust-minimised prize distribution for on-chain gaming/tournament
scenarios:

  1. Game operator locks a prize pool in escrow.
  2. When the game ends, the operator commits to a *reward sheet* — the
     mapping of `player_id -> reward_amount` — by publishing the Merkle
     root only (not the full sheet).
  3. Each winner independently claims their share by presenting a Merkle
     inclusion proof of their `(player_id, reward_amount, rank)` leaf.
     Anyone can verify the proof against the published root without
     seeing the whole sheet — losers stay private, and no operator step
     is required to release each individual reward.
  4. The escrow release path validates the proof server-side against the
     locked root and disburses exactly the committed amount to the
     player.

Design goals:
  * Deterministic, dependency-free (only stdlib hashlib).
  * Reuses the same tree math as `merkle_provenance.py` so proofs are
     cross-verifiable in TS.
  * Reward-shaped leaves — the `(player_id, amount, rank)` triple is the
     natural key; two identical triples produce the same leaf hash so a
     claim can't be split, and any tampering (amount inflation, wrong
     rank, foreign player) fails verification.
  * Prize-pool integrity: `total_committed == sum(leaf.amount)` is
     surfaced by `commit_results()` so the escrow layer can refuse to
     lock a root whose sheet exceeds the pool.
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


@dataclass(frozen=True)
class RewardLeaf:
    """One winner's slot on the reward sheet.

    * `player_id` is the natural key (an agent id, wallet address, or a
      hashed handle — the caller decides).
    * `reward_amount` is expressed in the same unit as the escrow's
      prize pool (motes for Casper, satoshis for BTC, wei for EVM).
    * `rank` disambiguates repeated `(player, amount)` pairs and pins
      leaderboard position (1 = winner). It is part of the leaf so a
      claim commits to a specific placement.

    All fields are stringified into the leaf pre-image so the hash is
    unambiguous across languages (no int width surprises).
    """

    player_id: str
    reward_amount: int
    rank: int


@dataclass(frozen=True)
class ProofStep:
    """One sibling on the path from a leaf to the root.

    `position` says whether THIS sibling sits on the *left* or *right*
    of the running hash during verification.
    """

    hash: str
    position: str  # "left" | "right"


@dataclass(frozen=True)
class RewardInclusionProof:
    """The full proof a winner submits to claim their reward.

    Verifier recomputes `leaf_hash(RewardLeaf(player_id, reward_amount,
    rank))`, folds each `siblings` step, and must arrive at the root
    the escrow was locked against.
    """

    player_id: str
    reward_amount: int
    rank: int
    siblings: list[ProofStep]


@dataclass(frozen=True)
class RewardCommitment:
    """The public output of a game round.

    * `root` is what the escrow layer locks against — pinned on-chain
      (or in the escrow record).
    * `total_committed` is the sum of every leaf's `reward_amount`.
      Escrow layer refuses to accept a commitment whose total exceeds
      the locked prize pool.
    * `winners_count` is the number of leaves in the sheet — surfaced
      for UI without exposing the sheet itself.
    """

    root: str
    total_committed: int
    winners_count: int


# ---------------------------------------------------------------------------
# Core hash math (identical shape to merkle_provenance so tree layout
# is interchangeable, but the leaf pre-image is reward-shaped)
# ---------------------------------------------------------------------------


def leaf_hash(leaf: RewardLeaf) -> str:
    """sha256("<player_id>:<reward_amount>:<rank>").

    Distinct namespace from merkle_provenance's evidence leaves: even
    if two callers accidentally reused the same string keys, an
    evidence-leaf hash and a reward-leaf hash for the same triple
    would still differ because the pre-image field ordering is domain
    specific.
    """
    preimage = f"{leaf.player_id}:{leaf.reward_amount}:{leaf.rank}"
    return _sha256_hex(preimage)


def _build_levels(leaf_hashes: list[str]) -> list[list[str]]:
    """From leaves (level 0) up to a single root (last level).

    Empty sheet has a well-defined root (`sha256("empty-rewards")`) so
    a game with zero winners still produces a valid commitment the
    escrow layer can lock (and later refund).
    """
    if not leaf_hashes:
        return [[_sha256_hex("empty-rewards")]]

    levels: list[list[str]] = [list(leaf_hashes)]
    current = list(leaf_hashes)
    while len(current) > 1:
        nxt: list[str] = []
        for i in range(0, len(current), 2):
            left = current[i]
            right = current[i + 1] if i + 1 < len(current) else current[i]
            nxt.append(_sha256_hex(left + right))
        levels.append(nxt)
        current = nxt
    return levels


def commit_results(leaves: Iterable[RewardLeaf]) -> RewardCommitment:
    """Commit to a reward sheet.

    Returns the public commitment (root + integrity numbers) that the
    escrow layer can lock. The sheet itself stays with the operator —
    only winners get a proof, losers see nothing.
    """
    leaves_list = list(leaves)
    hashes = [leaf_hash(lf) for lf in leaves_list]
    levels = _build_levels(hashes)
    total = sum(lf.reward_amount for lf in leaves_list)
    return RewardCommitment(root=levels[-1][0], total_committed=total, winners_count=len(leaves_list))


def build_claim_proof(leaves: list[RewardLeaf], player_id: str) -> Optional[RewardInclusionProof]:
    """Proof that `player_id` is a winner on the sheet.

    Returns `None` if the player isn't on the sheet. If they appear
    more than once, the FIRST occurrence wins — the operator is
    expected to de-duplicate players before committing (a caller can
    still allow multi-slot winners by using distinct `rank` values;
    then `build_claim_proof` will return the top-rank slot and the
    caller can iterate for the rest).
    """
    hashes = [leaf_hash(lf) for lf in leaves]
    try:
        target_index = next(i for i, lf in enumerate(leaves) if lf.player_id == player_id)
    except StopIteration:
        return None

    target = leaves[target_index]
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
    return RewardInclusionProof(
        player_id=target.player_id,
        reward_amount=target.reward_amount,
        rank=target.rank,
        siblings=siblings,
    )


def verify_claim(proof: RewardInclusionProof, root: str) -> bool:
    """Fold the proof from leaf up; final hash must equal `root`.

    Rejects:
      * amount tampering (leaf hash changes)
      * wrong player_id (leaf hash changes)
      * rank swap (leaf hash changes)
      * sibling injection (folded hash diverges from root)
      * malformed proof (unknown position)
    """
    running = leaf_hash(RewardLeaf(player_id=proof.player_id, reward_amount=proof.reward_amount, rank=proof.rank))
    for step in proof.siblings:
        if step.position == "left":
            running = _sha256_hex(step.hash + running)
        elif step.position == "right":
            running = _sha256_hex(running + step.hash)
        else:
            return False
    return running == root


# ---------------------------------------------------------------------------
# Escrow-integration helpers (used by gaming_reward_api on release)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimResult:
    """Outcome of validating a claim against a locked escrow.

    * `ok` = proof verified against the escrow's locked root AND the
      player hasn't already claimed.
    * `amount_to_release` = the exact motes the escrow should disburse.
    * `reason` explains rejections (proof_invalid / already_claimed /
      exceeds_pool). Machine-readable so the API layer can return a
      typed error.
    """

    ok: bool
    amount_to_release: int
    reason: str


def evaluate_claim(
    proof: RewardInclusionProof,
    locked_root: str,
    already_claimed: set[str],
    prize_pool_remaining: int,
) -> ClaimResult:
    """One-shot claim validation the API layer calls on release.

    Does NOT mutate `already_claimed` — that's the caller's job under
    a proper transaction. Returns what the caller should do, plus the
    reason if it can't.
    """
    if not verify_claim(proof, locked_root):
        return ClaimResult(ok=False, amount_to_release=0, reason="proof_invalid")
    if proof.player_id in already_claimed:
        return ClaimResult(ok=False, amount_to_release=0, reason="already_claimed")
    if proof.reward_amount > prize_pool_remaining:
        return ClaimResult(ok=False, amount_to_release=0, reason="exceeds_pool")
    return ClaimResult(ok=True, amount_to_release=proof.reward_amount, reason="ok")


__all__ = [
    "RewardLeaf",
    "ProofStep",
    "RewardInclusionProof",
    "RewardCommitment",
    "ClaimResult",
    "leaf_hash",
    "commit_results",
    "build_claim_proof",
    "verify_claim",
    "evaluate_claim",
]
