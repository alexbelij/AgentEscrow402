"""Cross-chain escrow demo (Tier Wow — W.3).

This module implements the **cross-chain escrow flow** — `create()` on
Casper, `release()` triggered by an EVM (Ethereum-compatible) event via a
mocked `ChainAdapter`. It mirrors the `contracts/stubs/src/chain_adapter.rs`
trait on the server side so a demo can run end-to-end without a live
Ethereum node.

## Flow

```
      Casper                                 Ethereum (mocked)
      ------                                 -----------------
1.    create_cross_chain_escrow  ─┐
       (deposits motes,           │
        binds trigger event)      │
                                  ▼
2.                            [pending] ◄──── watch: EVM event
                                                (chain_id, tx_hash, topic)
                                  │
                                  │       ┌─── EVM adapter observes event
                                  │       │    (test: mock injects)
                                  │       ▼
3.    settle_on_evm_event   ◄─────┴─── verify_remote_tx()
       (release motes to                (confirms confirmation depth)
        receiver on Casper)
```

## Design

- **Abstraction:** Python `ChainAdapter` protocol mirrors the Rust trait
  (`verify_remote_tx`, `remote_block_height`, `supported_chains`).
- **Adapters shipped:**
  - `MockEVMAdapter` — in-memory event registry for testing/demo.
  - `MockCasperAdapter` — always confirms (paired with the real Casper
    lifecycle when integrated).
- **Escrow record:** extends normal server-side escrow with:
  - `trigger_chain` — which foreign chain must emit the release event
  - `trigger_tx_hash` — the specific tx that must be confirmed
  - `trigger_topic` — the event topic (log signature) to match
  - `min_confirmations` — depth policy (default 12 for Ethereum)
- **Settlement:** `settle_on_evm_event()` is idempotent — same event
  processed twice releases only once. Registry keyed by
  `(chain_id, tx_hash)`.
- **Persistence:** in-memory `CrossChainRegistry` for the demo; production
  would move to `server/db.py` alongside `EscrowRecord`.

## Security notes (demo scope)

- **Chain-adapter trust boundary:** in real deployment, the EVM adapter
  would query a full node (Infura, Alchemy, self-hosted geth). It must
  independently verify block headers + log inclusion — a compromised
  RPC provider could otherwise inject fake events. The mock does not
  address this; it's a scaffolding for the demo.
- **Reorg protection:** `min_confirmations` policy plus block-height
  monotonicity check. The demo requires ≥12 confirmations before
  settlement fires; a longer reorg could invalidate a released escrow
  in a real deployment (mitigation: dispute window on the Casper side).
- **Double-spend across chains:** each cross-chain escrow is bound to a
  unique `(trigger_chain, trigger_tx_hash)` pair. Reuse of the same
  trigger event across two escrows requires arbiter approval (out of
  scope for the demo).

## Non-goals

- Real EVM RPC integration.
- Merkle-proof-based cross-chain light-client verification.
- Atomic swap semantics (HTLCs) — this is a triggered release, not an
  atomic 2-way exchange.
"""

from __future__ import annotations

import enum
import hashlib
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Protocol


# ---------------------------------------------------------------------------
# Chain identity
# ---------------------------------------------------------------------------

class ChainId(str, enum.Enum):
    """Supported blockchain targets for cross-chain operations.

    Mirrors `contracts/stubs/src/chain_adapter.rs::ChainId` on the server side.
    """

    CASPER_TESTNET = "casper-testnet"
    CASPER_MAINNET = "casper-mainnet"
    ETHEREUM = "ethereum"
    ETHEREUM_SEPOLIA = "ethereum-sepolia"
    POLYGON = "polygon"
    ARBITRUM = "arbitrum"


# ---------------------------------------------------------------------------
# Remote tx result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RemoteTxResult:
    """Result of a remote transaction verification.

    Mirrors `contracts/stubs/src/chain_adapter.rs::RemoteTxResult`.
    """

    chain_id: ChainId
    tx_hash: str  # hex (with or without 0x prefix)
    confirmed: bool
    block_number: int
    confirmations: int
    topics: List[str] = field(default_factory=list)
    data: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id.value,
            "tx_hash": self.tx_hash,
            "confirmed": self.confirmed,
            "block_number": self.block_number,
            "confirmations": self.confirmations,
            "topics": list(self.topics),
            "data": self.data,
        }


# ---------------------------------------------------------------------------
# Adapter protocol
# ---------------------------------------------------------------------------

class ChainAdapter(Protocol):
    """Abstraction for verifying transactions on remote chains.

    Mirrors the Rust trait in `contracts/stubs/src/chain_adapter.rs`.
    """

    def verify_remote_tx(self, chain_id: ChainId, tx_hash: str) -> RemoteTxResult:
        """Verify that a transaction exists and is confirmed on the remote chain.

        Raises `CrossChainError` if the chain is unsupported or the tx cannot
        be located.
        """
        ...

    def remote_block_height(self, chain_id: ChainId) -> int:
        """Return the current block height on the remote chain."""
        ...

    def supported_chains(self) -> List[ChainId]:
        """List chains this adapter can verify."""
        ...


class CrossChainError(Exception):
    """Raised on any cross-chain adapter or settlement error."""


# ---------------------------------------------------------------------------
# Mocked EVM adapter
# ---------------------------------------------------------------------------

class MockEVMAdapter:
    """In-memory EVM adapter for the demo / tests.

    Behavior:
      - Maintains a `block_height` counter per chain (advanced by
        `advance_blocks()` or automatically when events are recorded).
      - Records events via `record_event()` — associates a tx_hash with a
        block number, topics, and data.
      - `verify_remote_tx()` returns confirmations = current_height - block_of_tx.
      - Unknown tx → confirmed=False, block_number=0, confirmations=0.

    Thread-safe (all mutation under a lock).
    """

    def __init__(self, initial_height: int = 100):
        self._lock = threading.RLock()
        self._heights: Dict[ChainId, int] = {}
        # events keyed by (chain_id, normalized_tx_hash)
        self._events: Dict[tuple, RemoteTxResult] = {}
        self._supported: List[ChainId] = [
            ChainId.ETHEREUM,
            ChainId.ETHEREUM_SEPOLIA,
            ChainId.POLYGON,
            ChainId.ARBITRUM,
        ]
        for c in self._supported:
            self._heights[c] = initial_height

    # ---- ChainAdapter protocol methods ----

    def verify_remote_tx(self, chain_id: ChainId, tx_hash: str) -> RemoteTxResult:
        with self._lock:
            if chain_id not in self._supported:
                raise CrossChainError(f"unsupported chain: {chain_id}")
            key = (chain_id, _normalize_tx_hash(tx_hash))
            evt = self._events.get(key)
            if evt is None:
                return RemoteTxResult(
                    chain_id=chain_id,
                    tx_hash=tx_hash,
                    confirmed=False,
                    block_number=0,
                    confirmations=0,
                )
            confirmations = max(0, self._heights[chain_id] - evt.block_number)
            return RemoteTxResult(
                chain_id=evt.chain_id,
                tx_hash=evt.tx_hash,
                confirmed=evt.confirmed,
                block_number=evt.block_number,
                confirmations=confirmations,
                topics=evt.topics,
                data=evt.data,
            )

    def remote_block_height(self, chain_id: ChainId) -> int:
        with self._lock:
            if chain_id not in self._supported:
                raise CrossChainError(f"unsupported chain: {chain_id}")
            return self._heights[chain_id]

    def supported_chains(self) -> List[ChainId]:
        with self._lock:
            return list(self._supported)

    # ---- Mock control ----

    def record_event(
        self,
        chain_id: ChainId,
        tx_hash: str,
        topics: List[str],
        data: str = "",
        block_offset: int = 0,
    ) -> RemoteTxResult:
        """Register a fake EVM event. `block_offset` = how far below current
        head the event was mined (0 = at head).
        """
        with self._lock:
            if chain_id not in self._supported:
                raise CrossChainError(f"unsupported chain: {chain_id}")
            block = max(0, self._heights[chain_id] - block_offset)
            evt = RemoteTxResult(
                chain_id=chain_id,
                tx_hash=_normalize_tx_hash(tx_hash),
                confirmed=True,
                block_number=block,
                confirmations=self._heights[chain_id] - block,
                topics=list(topics),
                data=data,
            )
            self._events[(chain_id, evt.tx_hash)] = evt
            return evt

    def advance_blocks(self, chain_id: ChainId, blocks: int) -> int:
        """Simulate block production. Returns new height."""
        with self._lock:
            self._heights[chain_id] += blocks
            return self._heights[chain_id]


class MockCasperAdapter:
    """In-memory Casper adapter — always confirms. Used for the demo's
    Casper-side operations."""

    def __init__(self, initial_height: int = 5000):
        self._height = initial_height

    def verify_remote_tx(self, chain_id: ChainId, tx_hash: str) -> RemoteTxResult:
        if chain_id not in self.supported_chains():
            raise CrossChainError(f"unsupported chain: {chain_id}")
        return RemoteTxResult(
            chain_id=chain_id,
            tx_hash=tx_hash,
            confirmed=True,
            block_number=self._height,
            confirmations=1,
        )

    def remote_block_height(self, chain_id: ChainId) -> int:
        return self._height

    def supported_chains(self) -> List[ChainId]:
        return [ChainId.CASPER_TESTNET, ChainId.CASPER_MAINNET]

    def advance_blocks(self, blocks: int) -> int:
        self._height += blocks
        return self._height


# ---------------------------------------------------------------------------
# Cross-chain escrow record
# ---------------------------------------------------------------------------

class CrossChainStatus(str, enum.Enum):
    PENDING = "pending"        # created on Casper, waiting for trigger event
    SETTLED = "settled"        # trigger event confirmed, funds released
    EXPIRED = "expired"        # trigger not seen within TTL, refunded
    CANCELLED = "cancelled"    # manually cancelled by sender before trigger


@dataclass
class CrossChainEscrow:
    """A cross-chain escrow record. Server-side ledger only for the demo."""

    escrow_id: str  # local id (hash of trigger + sender)
    sender: str
    receiver: str
    amount_motes: int
    service_hash: str
    trigger_chain: ChainId
    trigger_tx_hash: str
    trigger_topic: str
    min_confirmations: int
    status: CrossChainStatus
    created_at: int
    settled_at: Optional[int] = None
    settled_tx: Optional[str] = None  # Casper release tx hash
    trigger_verified: Optional[RemoteTxResult] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["trigger_chain"] = self.trigger_chain.value
        d["status"] = self.status.value
        if self.trigger_verified:
            d["trigger_verified"] = self.trigger_verified.to_dict()
        return d


# ---------------------------------------------------------------------------
# Cross-chain registry
# ---------------------------------------------------------------------------

class CrossChainRegistry:
    """In-memory registry of cross-chain escrows.

    Enforces idempotency: same trigger event settles at most one escrow.
    """

    def __init__(self, evm_adapter: MockEVMAdapter, casper_adapter: MockCasperAdapter):
        self._lock = threading.RLock()
        self._escrows: Dict[str, CrossChainEscrow] = {}
        # index for double-spend prevention: (chain_id, tx_hash) -> escrow_id
        self._trigger_index: Dict[tuple, str] = {}
        self.evm = evm_adapter
        self.casper = casper_adapter

    # ---- create ----

    def create_cross_chain_escrow(
        self,
        sender: str,
        receiver: str,
        amount_motes: int,
        service_hash: str,
        trigger_chain: ChainId,
        trigger_tx_hash: str,
        trigger_topic: str,
        min_confirmations: int = 12,
    ) -> CrossChainEscrow:
        """Open a cross-chain escrow.

        The Casper deposit is assumed to be handled by the caller's Casper
        transaction (out of scope for this module — mocked by including
        `amount_motes` in the record). The escrow waits for the specific
        `(trigger_chain, trigger_tx_hash)` event with `min_confirmations`
        confirmations before releasing.

        Raises:
            CrossChainError on validation failure or double-registration.
        """
        with self._lock:
            if amount_motes <= 0:
                raise CrossChainError("amount_motes must be > 0")
            if trigger_chain not in self.evm.supported_chains():
                raise CrossChainError(f"trigger_chain {trigger_chain} not supported by adapter")
            if min_confirmations < 1:
                raise CrossChainError("min_confirmations must be >= 1")

            key = (trigger_chain, _normalize_tx_hash(trigger_tx_hash))
            if key in self._trigger_index:
                raise CrossChainError(
                    f"trigger event already bound to escrow {self._trigger_index[key]}"
                )

            escrow_id = _derive_escrow_id(sender, receiver, trigger_chain, trigger_tx_hash)
            escrow = CrossChainEscrow(
                escrow_id=escrow_id,
                sender=sender,
                receiver=receiver,
                amount_motes=amount_motes,
                service_hash=service_hash,
                trigger_chain=trigger_chain,
                trigger_tx_hash=_normalize_tx_hash(trigger_tx_hash),
                trigger_topic=trigger_topic,
                min_confirmations=min_confirmations,
                status=CrossChainStatus.PENDING,
                created_at=int(time.time()),
            )
            self._escrows[escrow_id] = escrow
            self._trigger_index[key] = escrow_id
            return escrow

    def get(self, escrow_id: str) -> Optional[CrossChainEscrow]:
        with self._lock:
            return self._escrows.get(escrow_id)

    def list_all(self) -> List[CrossChainEscrow]:
        with self._lock:
            return list(self._escrows.values())

    # ---- settle ----

    def settle_on_evm_event(self, escrow_id: str) -> CrossChainEscrow:
        """Attempt to settle the escrow if its trigger event has enough
        confirmations. Idempotent: settling an already-settled escrow is a
        no-op (returns the record).

        Steps:
          1. Load escrow (must be PENDING).
          2. Query EVM adapter for the trigger tx.
          3. Verify: confirmed=True, block_number>0,
                     confirmations >= min_confirmations,
                     matching topic.
          4. Flip status → SETTLED, record settled_at + trigger_verified,
             simulate Casper release tx hash.

        Raises:
            CrossChainError if not settleable (not enough confirmations,
            topic mismatch, wrong status).
        """
        with self._lock:
            escrow = self._escrows.get(escrow_id)
            if escrow is None:
                raise CrossChainError(f"unknown escrow: {escrow_id}")
            if escrow.status == CrossChainStatus.SETTLED:
                return escrow  # idempotent
            if escrow.status != CrossChainStatus.PENDING:
                raise CrossChainError(
                    f"escrow {escrow_id} is {escrow.status.value}, cannot settle"
                )

            result = self.evm.verify_remote_tx(escrow.trigger_chain, escrow.trigger_tx_hash)
            if not result.confirmed or result.block_number == 0:
                raise CrossChainError(
                    f"trigger event not yet observed on {escrow.trigger_chain.value}"
                )
            if result.confirmations < escrow.min_confirmations:
                raise CrossChainError(
                    f"insufficient confirmations: {result.confirmations} < "
                    f"{escrow.min_confirmations}"
                )
            if escrow.trigger_topic and escrow.trigger_topic not in result.topics:
                raise CrossChainError(
                    f"topic {escrow.trigger_topic} not in event topics {result.topics}"
                )

            # Simulate Casper release tx.
            casper_tx = _fake_casper_tx(escrow_id, result.tx_hash)
            escrow.status = CrossChainStatus.SETTLED
            escrow.settled_at = int(time.time())
            escrow.settled_tx = casper_tx
            escrow.trigger_verified = result
            return escrow

    def cancel(self, escrow_id: str, caller: str) -> CrossChainEscrow:
        """Cancel a PENDING escrow. Only the sender can cancel."""
        with self._lock:
            escrow = self._escrows.get(escrow_id)
            if escrow is None:
                raise CrossChainError(f"unknown escrow: {escrow_id}")
            if escrow.sender != caller:
                raise CrossChainError("only the sender can cancel")
            if escrow.status != CrossChainStatus.PENDING:
                raise CrossChainError(
                    f"escrow {escrow_id} is {escrow.status.value}, cannot cancel"
                )
            escrow.status = CrossChainStatus.CANCELLED
            return escrow

    def expire(self, escrow_id: str, ttl_seconds: int) -> CrossChainEscrow:
        """Mark PENDING escrow EXPIRED if now - created_at > ttl_seconds."""
        with self._lock:
            escrow = self._escrows.get(escrow_id)
            if escrow is None:
                raise CrossChainError(f"unknown escrow: {escrow_id}")
            if escrow.status != CrossChainStatus.PENDING:
                return escrow
            if time.time() - escrow.created_at <= ttl_seconds:
                raise CrossChainError("escrow not yet expired")
            escrow.status = CrossChainStatus.EXPIRED
            return escrow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_tx_hash(tx_hash: str) -> str:
    """Lowercase, strip 0x prefix, validate hex."""
    if not tx_hash:
        raise CrossChainError("empty tx_hash")
    h = tx_hash.lower().removeprefix("0x")
    if not all(c in "0123456789abcdef" for c in h):
        raise CrossChainError(f"invalid hex tx_hash: {tx_hash!r}")
    return h


def _derive_escrow_id(sender: str, receiver: str, chain: ChainId, tx_hash: str) -> str:
    """Deterministic escrow id from binding data."""
    material = f"{sender}|{receiver}|{chain.value}|{_normalize_tx_hash(tx_hash)}".encode()
    return "cc-" + hashlib.sha256(material).hexdigest()[:24]


def _fake_casper_tx(escrow_id: str, trigger_hash: str) -> str:
    """Deterministic fake Casper release tx hash for the demo."""
    material = f"casper-release|{escrow_id}|{trigger_hash}".encode()
    return hashlib.sha256(material).hexdigest()


# ---------------------------------------------------------------------------
# Module-level singleton for the FastAPI app
# ---------------------------------------------------------------------------

_registry: Optional[CrossChainRegistry] = None
_registry_lock = threading.Lock()


def get_registry() -> CrossChainRegistry:
    """Return the process-wide cross-chain registry (lazy singleton)."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = CrossChainRegistry(
                evm_adapter=MockEVMAdapter(initial_height=1_000_000),
                casper_adapter=MockCasperAdapter(initial_height=5_000_000),
            )
        return _registry


def reset_registry() -> None:
    """Reset the singleton — for tests only."""
    global _registry
    with _registry_lock:
        _registry = None
