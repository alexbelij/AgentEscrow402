# Cross-chain escrow demo (Tier Wow — W.3)

**Status:** implemented as a server-side demo (in-memory registry + mocked EVM adapter). Not yet wired to a real Ethereum RPC.

## What it is

`create()` on Casper, `release()` triggered by an event on an EVM chain
(Ethereum, Polygon, Arbitrum, Sepolia). The Casper-side escrow stays
`PENDING` until the specified `(trigger_chain, trigger_tx_hash)` event
achieves `min_confirmations` on the foreign chain, then settles
automatically to the receiver.

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

- **Abstraction:** Python `ChainAdapter` Protocol mirrors the Rust trait in
  `contracts/stubs/src/chain_adapter.rs` (`verify_remote_tx`,
  `remote_block_height`, `supported_chains`).
- **Adapters shipped:**
  - `MockEVMAdapter` — in-memory event registry. Records events via
    `record_event(chain, tx_hash, topics, data, block_offset)`; advances
    a per-chain block counter via `advance_blocks(chain, blocks)`.
    Verifier returns `confirmations = current_height - event_block`.
  - `MockCasperAdapter` — always confirms; paired with the real Casper
    lifecycle when integrated.
- **Registry:** `CrossChainRegistry` holds the escrows plus a
  `(chain_id, tx_hash) → escrow_id` index so the same trigger event
  cannot bind two escrows (double-spend prevention across chains).
- **Idempotent settlement:** `settle_on_evm_event()` called twice on the
  same settled escrow returns the same record without side effects.
- **Escrow ID:** deterministic — `cc-<sha256(sender|receiver|chain|tx)[:24]>`.
  Same binding data always yields the same id; helpful for replay-safe
  clients.

## Endpoints (`/crosschain/*`)

### `POST /crosschain/escrow` → 201

```json
{
  "sender": "0xSender",
  "receiver": "0xReceiver",
  "amount_motes": 1000000,
  "service_hash": "<64-hex>",
  "trigger_chain": "ethereum",
  "trigger_tx_hash": "0xabc123",
  "trigger_topic": "0xTransferSig",
  "min_confirmations": 12
}
```

Returns the created `CrossChainEscrow` (status `pending`, escrow_id).

### `POST /crosschain/settle`

```json
{"escrow_id": "cc-..."}
```

Verifies the trigger event on the foreign chain via the adapter. Returns
the settled escrow record with `trigger_verified` (event confirmation
data) and `settled_tx` (mocked Casper release tx hash).

Failures (400): trigger not seen, insufficient confirmations, topic
mismatch, wrong escrow status.

### `POST /crosschain/cancel`

```json
{"escrow_id": "cc-...", "caller": "0xSender"}
```

Cancels a `PENDING` escrow. Only the sender may cancel.

### `GET /crosschain/escrow/{id}` — fetch by id

### `GET /crosschain/escrows` — list all

### `GET /crosschain/chains` — supported EVM + Casper chains

### Demo helpers (mock-only)

- `POST /crosschain/mock/event` — inject a mock EVM event.
- `POST /crosschain/mock/advance` — advance mock block height.

## Confirmation policy

Default `min_confirmations` = 12 (Ethereum's typical finality-ish
threshold). Configurable per escrow, `[1, 100]`. The demo enforces this
strictly — settlement fails with 400 until the event has enough
confirmations.

## Security notes (demo scope)

- **Chain-adapter trust boundary:** in production the EVM adapter must
  independently verify block headers + log inclusion (not just trust an
  RPC provider's response). The mock does not; it's scaffolding.
- **Reorg protection:** `min_confirmations` policy plus block-height
  monotonicity check. A longer reorg than `min_confirmations` on the
  foreign chain could still invalidate a released escrow — production
  would add a dispute window on the Casper side.
- **Double-spend across chains:** the `(trigger_chain, trigger_tx_hash)`
  index guards against binding the same event to two escrows.

## Non-goals

- Real EVM RPC integration (Infura/Alchemy/self-hosted geth).
- Merkle-proof-based cross-chain light-client verification.
- Atomic swap semantics (HTLCs) — this is a triggered release, not an
  atomic 2-way exchange.

## Tests

- `tests/test_cross_chain.py` — 24 tests:
  - Mock adapter behavior (supported chains, unknown tx, event recording,
    confirmation growth, tx-hash normalization, unsupported chain).
  - Registry CRUD (create validation, deterministic id, double-binding
    rejection).
  - Settlement lifecycle (happy path, insufficient confirmations, missing
    event, topic mismatch, idempotency, unknown escrow).
  - Cancel/expire (sender-only cancel, cannot cancel settled, TTL expiry).
  - Full lifecycle E2E via FastAPI TestClient — create → try-settle-fails
    → inject event → settle-succeeds → idempotent-resettle → cancel-fails.

All 24 tests green.

## Future work

1. **Real EVM adapter** — swap `MockEVMAdapter` for a `Web3EVMAdapter`
   that hits Infura/Alchemy with local header validation.
2. **Persist to DB** — move `CrossChainRegistry` from in-memory to
   `server/db.py` alongside `EscrowRecord`.
3. **On-chain integration** — the Casper `escrow-manager` contract
   would gain a `cross_chain_release()` entry point that requires an
   arbiter's attestation of the foreign-chain event, replacing the
   server-side settlement path.
4. **HTLC mode** — full atomic-swap semantics with hash-lock and
   time-lock symmetry, closer to a bridge than a triggered escrow.
