"""AE402 Governance DAO — Python SDK.

Byte-parity with `contracts/ae402-governance-dao/src/lib.rs`:

* ``encode_params`` produces the exact wire string the on-chain
  ``parse_params`` consumes; ``decode_params`` is its inverse.
* ``build_execution_message`` emits the identical bytes as the Rust
  ``build_execution_message`` — the hash of this string is what an
  arbiter Ed25519-signs (Phase 2 hardening) and what the contract
  writes to the on-chain exec log.
* Status codes, action codes, quorum/voting constants mirror the Rust
  library. Any drift here is a bug — see the byte-parity test in
  ``tests/test_governance_dao_parity.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Union

# ── Constants (must stay in lock-step with lib.rs) ───────────────────

EXECUTION_DOMAIN = "ae402:governance-dao:exec:v1"
QUORUM_PERCENT = 30
VOTING_PERIOD_SECONDS = 7 * 24 * 60 * 60


class Status(IntEnum):
    ACTIVE = 0
    PASSED = 1
    REJECTED = 2
    EXECUTED = 3
    VETOED = 4
    EXPIRED = 5


class Action(IntEnum):
    ADJUST_FEE_BPS = 0
    ROTATE_ARBITER_SET = 1
    UPDATE_INSURANCE_POOL_PARAMS = 2
    UPDATE_TIMELOCK_DELAY = 3
    UPDATE_RANGE_PROOF_PARAMS = 4
    PAUSE_PROTOCOL = 5


# ── Action-params dataclasses ────────────────────────────────────────


@dataclass(frozen=True)
class AdjustFeeBps:
    bps: int


@dataclass(frozen=True)
class RotateArbiterSet:
    op: str  # "add" | "remove" | "threshold"
    value: str  # hex-pk (66 chars) for add/remove; decimal u64 for threshold


@dataclass(frozen=True)
class UpdateInsurancePool:
    max_coverage_bps: int
    cooldown_sec: int


@dataclass(frozen=True)
class UpdateTimelockDelay:
    delay_sec: int


@dataclass(frozen=True)
class UpdateRangeProof:
    min_bits: int
    max_bits: int


@dataclass(frozen=True)
class PauseProtocol:
    pause: bool


ActionParams = Union[
    AdjustFeeBps,
    RotateArbiterSet,
    UpdateInsurancePool,
    UpdateTimelockDelay,
    UpdateRangeProof,
    PauseProtocol,
]

# ── Errors ───────────────────────────────────────────────────────────


class GovernanceError(ValueError):
    """Raised when params fail the on-chain schema check."""


# ── Encode / decode ──────────────────────────────────────────────────


def _hex_ok(s: str) -> bool:
    return all(c in "0123456789abcdefABCDEF" for c in s)


def encode_params(params: ActionParams) -> tuple[int, str]:
    """Serialize an ``ActionParams`` into the (action_code, params_str) tuple
    the on-chain ``create_proposal`` entry point accepts. Raises
    :class:`GovernanceError` if the params would be rejected by the
    contract's ``parse_params`` — validation runs client-side first so a
    caller never wastes gas on an invalid proposal.
    """
    if isinstance(params, AdjustFeeBps):
        if not (0 <= params.bps <= 10_000):
            raise GovernanceError(f"bps must be in [0, 10000]; got {params.bps}")
        return (Action.ADJUST_FEE_BPS, f"bps={params.bps}")

    if isinstance(params, RotateArbiterSet):
        if params.op not in ("add", "remove", "threshold"):
            raise GovernanceError(f"op must be add|remove|threshold; got {params.op!r}")
        if params.op == "threshold":
            try:
                t = int(params.value)
            except ValueError as e:
                raise GovernanceError(f"threshold value must be a decimal u64; got {params.value!r}") from e
            if not (1 <= t <= 64):
                raise GovernanceError(f"threshold must be in [1, 64]; got {t}")
        else:
            if len(params.value) != 66 or not _hex_ok(params.value):
                raise GovernanceError("add/remove value must be a 66-char hex pubkey")
        return (Action.ROTATE_ARBITER_SET, f"op={params.op};value={params.value}")

    if isinstance(params, UpdateInsurancePool):
        if not (0 <= params.max_coverage_bps <= 10_000):
            raise GovernanceError(f"max_coverage_bps must be in [0, 10000]; got {params.max_coverage_bps}")
        if params.cooldown_sec < 0:
            raise GovernanceError("cooldown_sec must be >= 0")
        return (
            Action.UPDATE_INSURANCE_POOL_PARAMS,
            f"max_coverage_bps={params.max_coverage_bps};cooldown_sec={params.cooldown_sec}",
        )

    if isinstance(params, UpdateTimelockDelay):
        if params.delay_sec < 3600:
            raise GovernanceError(f"delay_sec must be >= 3600; got {params.delay_sec}")
        return (Action.UPDATE_TIMELOCK_DELAY, f"delay_sec={params.delay_sec}")

    if isinstance(params, UpdateRangeProof):
        if not (1 <= params.min_bits <= 32) or not (1 <= params.max_bits <= 32):
            raise GovernanceError(f"min_bits/max_bits must be in [1, 32]; got ({params.min_bits}, {params.max_bits})")
        if params.min_bits > params.max_bits:
            raise GovernanceError(f"min_bits > max_bits: ({params.min_bits}, {params.max_bits})")
        return (
            Action.UPDATE_RANGE_PROOF_PARAMS,
            f"min_bits={params.min_bits};max_bits={params.max_bits}",
        )

    if isinstance(params, PauseProtocol):
        return (
            Action.PAUSE_PROTOCOL,
            f"mode={'pause' if params.pause else 'unpause'}",
        )

    raise GovernanceError(f"unknown params type: {type(params).__name__}")


def _kv_pairs(s: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    if not s:
        return pairs
    for seg in s.split(";"):
        if not seg or "=" not in seg:
            raise GovernanceError(f"malformed kv segment: {seg!r}")
        k, v = seg.split("=", 1)
        if not k or not v:
            raise GovernanceError(f"empty key or value: {seg!r}")
        pairs[k] = v
    return pairs


def decode_params(action_code: int, params_str: str) -> ActionParams:
    """Inverse of :func:`encode_params`. Raises :class:`GovernanceError` on
    any deviation from the contract's schema."""
    kv = _kv_pairs(params_str)

    if action_code == Action.ADJUST_FEE_BPS:
        try:
            bps = int(kv["bps"])
        except (KeyError, ValueError) as e:
            raise GovernanceError(f"missing/invalid bps: {kv}") from e
        return AdjustFeeBps(bps=bps)

    if action_code == Action.ROTATE_ARBITER_SET:
        op = kv.get("op")
        value = kv.get("value")
        if op is None or value is None:
            raise GovernanceError(f"missing op/value: {kv}")
        return RotateArbiterSet(op=op, value=value)

    if action_code == Action.UPDATE_INSURANCE_POOL_PARAMS:
        try:
            return UpdateInsurancePool(
                max_coverage_bps=int(kv["max_coverage_bps"]),
                cooldown_sec=int(kv["cooldown_sec"]),
            )
        except (KeyError, ValueError) as e:
            raise GovernanceError(f"malformed insurance-pool params: {kv}") from e

    if action_code == Action.UPDATE_TIMELOCK_DELAY:
        try:
            return UpdateTimelockDelay(delay_sec=int(kv["delay_sec"]))
        except (KeyError, ValueError) as e:
            raise GovernanceError(f"malformed timelock params: {kv}") from e

    if action_code == Action.UPDATE_RANGE_PROOF_PARAMS:
        try:
            return UpdateRangeProof(
                min_bits=int(kv["min_bits"]),
                max_bits=int(kv["max_bits"]),
            )
        except (KeyError, ValueError) as e:
            raise GovernanceError(f"malformed range-proof params: {kv}") from e

    if action_code == Action.PAUSE_PROTOCOL:
        mode = kv.get("mode")
        if mode == "pause":
            return PauseProtocol(pause=True)
        if mode == "unpause":
            return PauseProtocol(pause=False)
        raise GovernanceError(f"unknown pause mode: {mode!r}")

    raise GovernanceError(f"unknown action code: {action_code}")


# ── Execution message — byte-parity with lib.rs::build_execution_message ─


def build_execution_message(proposal_id: int, action_code: int, params_str: str) -> str:
    """Deterministic string that binds (proposal_id, action, params) into
    the on-chain exec log. An arbiter's Ed25519 signature over this exact
    string is what the on-chain execute pathway may check in Phase 2
    hardening — off-chain SDK MUST produce these bytes identically to the
    Rust library."""
    if proposal_id < 0:
        raise GovernanceError("proposal_id must be non-negative")
    if action_code < 0:
        raise GovernanceError("action_code must be non-negative")
    return f"{EXECUTION_DOMAIN}:{proposal_id}:{action_code}:{params_str}"


# ── Quorum math ──────────────────────────────────────────────────────


def quorum_threshold(total_staked: int, quorum_percent: int = QUORUM_PERCENT) -> int:
    """Byte-parity with ``lib.rs::quorum_threshold`` (u128 intermediate)."""
    if total_staked < 0 or quorum_percent < 0:
        raise GovernanceError("stakes/percentages must be non-negative")
    return (total_staked * quorum_percent) // 100


def resolve_status(
    votes_for: int,
    votes_against: int,
    total_staked: int,
    current_time: int,
    voting_end: int,
    quorum_percent: int = QUORUM_PERCENT,
) -> Status:
    """Byte-parity with ``lib.rs::resolve_status``."""
    threshold = quorum_threshold(total_staked, quorum_percent)
    quorum_met = votes_for + votes_against >= threshold
    window_closed = current_time > voting_end
    if window_closed:
        if quorum_met:
            return Status.PASSED if votes_for > votes_against else Status.REJECTED
        return Status.EXPIRED
    if quorum_met:
        return Status.PASSED if votes_for > votes_against else Status.REJECTED
    return Status.ACTIVE
