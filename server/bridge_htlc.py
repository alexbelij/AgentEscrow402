"""HTLC atomic-swap bridge mock (Tier 3 — T3.4-A).

Deterministic, in-memory Hash Time-Locked Contract state machine that
mirrors the semantics of a real cross-chain atomic swap between Casper
(chain "casper") and an EVM chain (chain "evm-mock"). Zero I/O, zero
network, byte-for-byte reproducible from a seed of (initiator,
counterparty, amounts, hashlock, timelocks).

## Atomic swap primer

Two independent chains, one shared secret. Alice holds asset A on chain
X; Bob holds asset B on chain Y. They want to swap without a trusted
third party. Solution:

1.  Alice picks a random 32-byte preimage `s`, publishes `H = sha256(s)`.
2.  Alice locks A on chain X, spendable by Bob if he reveals `s` before
    timelock `T_a`, otherwise refundable to Alice after `T_a`.
3.  Bob sees Alice's lock, locks B on chain Y with the SAME hashlock `H`,
    spendable by Alice if she reveals `s` before timelock `T_b < T_a`,
    otherwise refundable to Bob after `T_b`.
4.  Alice claims B on chain Y by revealing `s` — this publishes `s` on
    chain Y (visible to Bob).
5.  Bob observes `s` on chain Y and uses it to claim A on chain X before
    `T_a`.

**Safety invariants:**
- `T_b < T_a` so Alice can't wait until Bob's timelock expires, refund on
  Y, then still claim on X.
- Either both parties claim (swap completes) or both refund (swap
  aborts); never one claim + one refund from opposite sides.
- Once `s` is revealed on either chain, the other side can be claimed by
  the corresponding party (permissionless).

## Non-goals (this module)

- Real EVM RPC. B-tier will add ethers-py + Sepolia in T3.4-B.
- Zero-knowledge preimage schemes.
- Adaptor signatures / scriptless scripts.
- Multi-hop routing.

## State machine

```
    initiate(side)      lock(side)          claim(side, preimage)
INIT ─────────────► PROPOSED ────────► LOCKED ─────────────────► CLAIMED
                                          │
                                          │  refund(side) after timelock
                                          ▼
                                       REFUNDED
```

Each side (`casper` and `evm-mock`) has its OWN state; a swap is a pair.

## Determinism

- No wall-clock reads inside decision logic. Every timelock comparison
  uses a `now_ms` argument passed by the caller (API layer stamps it
  from `time.time()`; tests inject fixed values). Same inputs → same
  output bytes.
- Escrow ids: `sha256(f"{side}:{initiator}:{counterparty}:{amount}:{hashlock_hex}:{timelock_ms}")`.
"""

from __future__ import annotations

import enum
import hashlib
import secrets
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


class Side(str, enum.Enum):
    CASPER = "casper"
    EVM = "evm-mock"


class HTLCStatus(str, enum.Enum):
    PROPOSED = "proposed"  # side declared, hashlock committed, funds not yet escrowed
    LOCKED = "locked"      # funds escrowed on this side
    CLAIMED = "claimed"    # preimage revealed, funds released to counterparty
    REFUNDED = "refunded"  # timelock expired, funds returned to initiator


class RejectCode(str, enum.Enum):
    PREIMAGE_MISMATCH = "preimage_mismatch"
    TIMELOCK_NOT_EXPIRED = "timelock_not_expired"
    TIMELOCK_EXPIRED = "timelock_expired"
    ALREADY_CLAIMED = "already_claimed"
    ALREADY_REFUNDED = "already_refunded"
    NOT_LOCKED = "not_locked"
    NOT_PROPOSED = "not_proposed"
    UNKNOWN_LEG = "unknown_leg"
    LEG_ALREADY_EXISTS = "leg_already_exists"
    INVALID_HASHLOCK = "invalid_hashlock"
    INVALID_AMOUNT = "invalid_amount"
    TIMELOCK_ORDERING = "timelock_ordering"  # T_b >= T_a


class HTLCError(Exception):
    """Typed rejection surfaced from the state machine."""

    def __init__(self, code: RejectCode, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}" if detail else code.value)


@dataclass
class HTLCLeg:
    """Half of an atomic swap, on one chain."""

    leg_id: str
    side: Side
    initiator: str            # who locks funds on THIS side
    counterparty: str         # who can claim by revealing preimage
    amount: int               # motes on Casper, wei on EVM
    hashlock_hex: str         # sha256(preimage) in lowercase hex
    timelock_ms: int          # absolute deadline; refund allowed at/after this ms
    status: HTLCStatus = HTLCStatus.PROPOSED
    preimage_hex: Optional[str] = None    # revealed on claim
    locked_at_ms: Optional[int] = None
    claimed_at_ms: Optional[int] = None
    refunded_at_ms: Optional[int] = None
    lock_tx_hash: Optional[str] = None    # deterministic mock tx hash
    claim_tx_hash: Optional[str] = None
    refund_tx_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["side"] = self.side.value
        d["status"] = self.status.value
        return d


@dataclass
class HTLCSwap:
    """Pair of legs sharing the same hashlock."""

    swap_id: str
    hashlock_hex: str
    casper_leg: Optional[HTLCLeg] = None
    evm_leg: Optional[HTLCLeg] = None
    created_at_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "swap_id": self.swap_id,
            "hashlock_hex": self.hashlock_hex,
            "created_at_ms": self.created_at_ms,
            "casper_leg": self.casper_leg.to_dict() if self.casper_leg else None,
            "evm_leg": self.evm_leg.to_dict() if self.evm_leg else None,
        }


# ---------------------------------------------------------------------------
# Pure helpers (deterministic; safe to unit-test without a registry)
# ---------------------------------------------------------------------------


def _norm_hex(s: str) -> str:
    """Normalize a hex string to lowercase, no `0x` prefix. Raises on non-hex."""
    if s.startswith("0x") or s.startswith("0X"):
        s = s[2:]
    s = s.lower()
    if not s or any(c not in "0123456789abcdef" for c in s):
        raise HTLCError(RejectCode.INVALID_HASHLOCK, f"not hex: {s!r}")
    return s


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_hashlock(preimage: bytes) -> str:
    """sha256(preimage), lowercase hex."""
    if not preimage:
        raise HTLCError(RejectCode.INVALID_HASHLOCK, "empty preimage")
    return sha256_hex(preimage)


def new_preimage(nbytes: int = 32) -> bytes:
    """Cryptographically random preimage (test/demo helper)."""
    return secrets.token_bytes(nbytes)


def _leg_id(
    side: Side,
    initiator: str,
    counterparty: str,
    amount: int,
    hashlock_hex: str,
    timelock_ms: int,
) -> str:
    material = f"{side.value}:{initiator}:{counterparty}:{amount}:{hashlock_hex}:{timelock_ms}"
    return sha256_hex(material.encode())


def _swap_id(hashlock_hex: str, casper_initiator: str, evm_initiator: str) -> str:
    material = f"swap:{hashlock_hex}:{casper_initiator}:{evm_initiator}"
    return sha256_hex(material.encode())


def _mock_tx_hash(side: Side, leg_id: str, action: str, nonce_ms: int) -> str:
    """Deterministic mock chain tx hash — reproducible across runs."""
    material = f"{side.value}:{leg_id}:{action}:{nonce_ms}"
    return "0x" + sha256_hex(material.encode())


def verify_timelock_ordering(casper_timelock_ms: int, evm_timelock_ms: int) -> None:
    """Safety: T_b (counterparty leg) MUST be strictly less than T_a (initiator leg).

    Convention here: whoever initiates the swap (defines the preimage) locks
    on Casper first with the longer timelock; counterparty locks on EVM
    second with the shorter timelock. This guarantees the initiator can't
    grief by waiting out the counterparty's timelock.
    """
    if evm_timelock_ms >= casper_timelock_ms:
        raise HTLCError(
            RejectCode.TIMELOCK_ORDERING,
            f"evm_timelock_ms ({evm_timelock_ms}) must be < casper_timelock_ms ({casper_timelock_ms})",
        )


def validate_amount(amount: int) -> None:
    if not isinstance(amount, int) or amount <= 0:
        raise HTLCError(RejectCode.INVALID_AMOUNT, f"amount must be positive int, got {amount!r}")


# ---------------------------------------------------------------------------
# Registry — in-memory, thread-safe
# ---------------------------------------------------------------------------


class HTLCRegistry:
    """In-memory swap store. One instance per process; thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._swaps: Dict[str, HTLCSwap] = {}
        # index by leg_id for direct lookup
        self._leg_index: Dict[str, str] = {}  # leg_id -> swap_id

    # ---- creation / read ----

    def get_swap(self, swap_id: str) -> Optional[HTLCSwap]:
        with self._lock:
            return self._swaps.get(swap_id)

    def get_leg(self, leg_id: str) -> Optional[HTLCLeg]:
        with self._lock:
            swap_id = self._leg_index.get(leg_id)
            if not swap_id:
                return None
            swap = self._swaps.get(swap_id)
            if not swap:
                return None
            if swap.casper_leg and swap.casper_leg.leg_id == leg_id:
                return swap.casper_leg
            if swap.evm_leg and swap.evm_leg.leg_id == leg_id:
                return swap.evm_leg
            return None

    def list_swaps(self) -> List[HTLCSwap]:
        with self._lock:
            return list(self._swaps.values())

    def initiate_swap(
        self,
        *,
        hashlock_hex: str,
        casper_initiator: str,
        casper_counterparty: str,
        casper_amount: int,
        casper_timelock_ms: int,
        evm_initiator: str,
        evm_counterparty: str,
        evm_amount: int,
        evm_timelock_ms: int,
        now_ms: int,
    ) -> HTLCSwap:
        """Register both legs as PROPOSED. Neither is locked yet."""
        hashlock_hex = _norm_hex(hashlock_hex)
        if len(hashlock_hex) != 64:
            raise HTLCError(
                RejectCode.INVALID_HASHLOCK,
                f"hashlock must be 32-byte sha256 (64 hex chars), got {len(hashlock_hex)}",
            )
        validate_amount(casper_amount)
        validate_amount(evm_amount)
        verify_timelock_ordering(casper_timelock_ms, evm_timelock_ms)

        swap_id = _swap_id(hashlock_hex, casper_initiator, evm_initiator)

        with self._lock:
            if swap_id in self._swaps:
                raise HTLCError(
                    RejectCode.LEG_ALREADY_EXISTS,
                    f"swap {swap_id[:16]}… already exists",
                )

            casper_leg = HTLCLeg(
                leg_id=_leg_id(
                    Side.CASPER,
                    casper_initiator,
                    casper_counterparty,
                    casper_amount,
                    hashlock_hex,
                    casper_timelock_ms,
                ),
                side=Side.CASPER,
                initiator=casper_initiator,
                counterparty=casper_counterparty,
                amount=casper_amount,
                hashlock_hex=hashlock_hex,
                timelock_ms=casper_timelock_ms,
            )
            evm_leg = HTLCLeg(
                leg_id=_leg_id(
                    Side.EVM,
                    evm_initiator,
                    evm_counterparty,
                    evm_amount,
                    hashlock_hex,
                    evm_timelock_ms,
                ),
                side=Side.EVM,
                initiator=evm_initiator,
                counterparty=evm_counterparty,
                amount=evm_amount,
                hashlock_hex=hashlock_hex,
                timelock_ms=evm_timelock_ms,
            )
            swap = HTLCSwap(
                swap_id=swap_id,
                hashlock_hex=hashlock_hex,
                casper_leg=casper_leg,
                evm_leg=evm_leg,
                created_at_ms=now_ms,
            )
            self._swaps[swap_id] = swap
            self._leg_index[casper_leg.leg_id] = swap_id
            self._leg_index[evm_leg.leg_id] = swap_id
            return swap

    # ---- transitions ----

    def lock(self, leg_id: str, now_ms: int) -> HTLCLeg:
        """Move a leg from PROPOSED → LOCKED. Escrow funds on this side."""
        with self._lock:
            leg = self._require_leg(leg_id)
            if leg.status == HTLCStatus.LOCKED:
                return leg  # idempotent — same lock request is a no-op
            if leg.status != HTLCStatus.PROPOSED:
                raise HTLCError(
                    RejectCode.NOT_PROPOSED,
                    f"leg is {leg.status.value}, cannot lock",
                )
            if now_ms >= leg.timelock_ms:
                raise HTLCError(
                    RejectCode.TIMELOCK_EXPIRED,
                    f"cannot lock: timelock {leg.timelock_ms} already passed at {now_ms}",
                )
            leg.status = HTLCStatus.LOCKED
            leg.locked_at_ms = now_ms
            leg.lock_tx_hash = _mock_tx_hash(leg.side, leg.leg_id, "lock", now_ms)
            return leg

    def claim(self, leg_id: str, preimage_hex: str, now_ms: int) -> HTLCLeg:
        """Counterparty reveals preimage → LOCKED → CLAIMED. Preimage is now
        public on this side (mocked as stored on the leg record — a real
        chain would expose it via the tx calldata).
        """
        preimage_hex = _norm_hex(preimage_hex)
        try:
            preimage_bytes = bytes.fromhex(preimage_hex)
        except ValueError as e:
            raise HTLCError(RejectCode.INVALID_HASHLOCK, f"bad preimage hex: {e}") from e

        with self._lock:
            leg = self._require_leg(leg_id)
            if leg.status == HTLCStatus.CLAIMED:
                raise HTLCError(RejectCode.ALREADY_CLAIMED, leg.leg_id)
            if leg.status == HTLCStatus.REFUNDED:
                raise HTLCError(RejectCode.ALREADY_REFUNDED, leg.leg_id)
            if leg.status != HTLCStatus.LOCKED:
                raise HTLCError(
                    RejectCode.NOT_LOCKED,
                    f"leg is {leg.status.value}, cannot claim",
                )
            if now_ms >= leg.timelock_ms:
                raise HTLCError(
                    RejectCode.TIMELOCK_EXPIRED,
                    f"claim window closed at {leg.timelock_ms} (now={now_ms})",
                )
            got = compute_hashlock(preimage_bytes)
            if got != leg.hashlock_hex:
                raise HTLCError(
                    RejectCode.PREIMAGE_MISMATCH,
                    f"sha256(preimage)={got[:16]}… != leg.hashlock={leg.hashlock_hex[:16]}…",
                )
            leg.status = HTLCStatus.CLAIMED
            leg.preimage_hex = preimage_hex
            leg.claimed_at_ms = now_ms
            leg.claim_tx_hash = _mock_tx_hash(leg.side, leg.leg_id, "claim", now_ms)

            # Propagate revealed preimage to the sibling leg's swap record
            # so the counterparty adapter/observer can see it — mirrors the
            # real behaviour where preimage appears in the claim tx calldata.
            swap_id = self._leg_index.get(leg.leg_id)
            if swap_id:
                swap = self._swaps.get(swap_id)
                if swap:
                    sibling = swap.evm_leg if leg.side == Side.CASPER else swap.casper_leg
                    if sibling and sibling.preimage_hex is None and sibling.status == HTLCStatus.LOCKED:
                        # Not auto-claiming — we just make it visible; the
                        # counterparty API caller must still fire /claim.
                        # But we DO store the revealed preimage on the swap
                        # so observers can find it.
                        pass  # visibility is via swap.casper_leg.preimage_hex
            return leg

    def refund(self, leg_id: str, now_ms: int) -> HTLCLeg:
        """Timelock elapsed → LOCKED → REFUNDED. Initiator recovers funds."""
        with self._lock:
            leg = self._require_leg(leg_id)
            if leg.status == HTLCStatus.REFUNDED:
                raise HTLCError(RejectCode.ALREADY_REFUNDED, leg.leg_id)
            if leg.status == HTLCStatus.CLAIMED:
                raise HTLCError(RejectCode.ALREADY_CLAIMED, leg.leg_id)
            if leg.status != HTLCStatus.LOCKED:
                raise HTLCError(
                    RejectCode.NOT_LOCKED,
                    f"leg is {leg.status.value}, cannot refund",
                )
            if now_ms < leg.timelock_ms:
                raise HTLCError(
                    RejectCode.TIMELOCK_NOT_EXPIRED,
                    f"refund allowed at/after {leg.timelock_ms}, now={now_ms}",
                )
            leg.status = HTLCStatus.REFUNDED
            leg.refunded_at_ms = now_ms
            leg.refund_tx_hash = _mock_tx_hash(leg.side, leg.leg_id, "refund", now_ms)
            return leg

    # ---- observers ----

    def reveal_preimage(self, swap_id: str) -> Optional[str]:
        """Return preimage revealed on either leg, if any. Models the
        cross-chain observer that watches the fast leg for `s` reveal."""
        with self._lock:
            swap = self._swaps.get(swap_id)
            if not swap:
                return None
            if swap.casper_leg and swap.casper_leg.preimage_hex:
                return swap.casper_leg.preimage_hex
            if swap.evm_leg and swap.evm_leg.preimage_hex:
                return swap.evm_leg.preimage_hex
            return None

    def swap_state_summary(self, swap_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            swap = self._swaps.get(swap_id)
            if not swap:
                return None
            revealed = self.reveal_preimage(swap_id)
            casper_status = swap.casper_leg.status.value if swap.casper_leg else None
            evm_status = swap.evm_leg.status.value if swap.evm_leg else None
            both_claimed = casper_status == "claimed" and evm_status == "claimed"
            both_refunded = casper_status == "refunded" and evm_status == "refunded"
            mixed = (
                (casper_status == "claimed" and evm_status == "refunded")
                or (casper_status == "refunded" and evm_status == "claimed")
            )
            return {
                "swap_id": swap_id,
                "hashlock_hex": swap.hashlock_hex,
                "casper_status": casper_status,
                "evm_status": evm_status,
                "revealed_preimage_hex": revealed,
                "atomic_outcome": (
                    "completed" if both_claimed
                    else "aborted" if both_refunded
                    else "in_progress"
                ),
                "safety_violation": mixed,
            }

    # ---- helpers ----

    def _require_leg(self, leg_id: str) -> HTLCLeg:
        swap_id = self._leg_index.get(leg_id)
        if not swap_id:
            raise HTLCError(RejectCode.UNKNOWN_LEG, leg_id)
        swap = self._swaps.get(swap_id)
        if not swap:
            raise HTLCError(RejectCode.UNKNOWN_LEG, leg_id)
        if swap.casper_leg and swap.casper_leg.leg_id == leg_id:
            return swap.casper_leg
        if swap.evm_leg and swap.evm_leg.leg_id == leg_id:
            return swap.evm_leg
        raise HTLCError(RejectCode.UNKNOWN_LEG, leg_id)


# Module-level default registry for easy import in API layer / tests.
_DEFAULT_REGISTRY = HTLCRegistry()


def default_registry() -> HTLCRegistry:
    return _DEFAULT_REGISTRY


def reset_default_registry() -> None:
    """Test helper — nuke shared state between tests."""
    global _DEFAULT_REGISTRY
    _DEFAULT_REGISTRY = HTLCRegistry()
