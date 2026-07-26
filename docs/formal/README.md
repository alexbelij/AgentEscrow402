# AE402 formal specifications (C16)

TLA+ model of the escrow state machine at just enough resolution to prove
five safety invariants and one liveness property. This is the machine-
checked counterpart to the FSM diagram in `docs/ARCHITECTURE.md` — if the
two ever disagree, the diagram is wrong.

## Files

- `AE402Escrow.tla` — the model itself. Actions map 1-to-1 to the FSM
  edges in `server/app.py` (`release`, `refund`, `dispute`, tombstone,
  expire).
- `AE402Escrow.cfg` — finite-model bounds for TLC. Kept small so a full
  model check completes in seconds.

## Running TLC locally

```sh
# Grab the TLA+ toolbox jar (once):
curl -L -o /tmp/tla2tools.jar \
  https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar

# Model-check:
java -cp /tmp/tla2tools.jar tlc2.TLC \
    -config docs/formal/AE402Escrow.cfg \
    docs/formal/AE402Escrow.tla
```

A clean run ends with `Model checking completed. No error has been found.`.

## What it proves

| Invariant | Real-system claim |
|---|---|
| `Inv_ValidStatusTransition` | Every status change follows a declared FSM edge (no arbitrary jumps). |
| `Inv_NoDoubleRelease` | No escrow row can go through `released` twice. |
| `Inv_NoRefundAfterRelease` | `released` is terminal — no path back to refund/dispute. |
| `Inv_TombstonedNoReplay` | An insurance-tombstoned escrow can never be refunded again (AE-2 replay guard). |
| `Inv_AmountConservation` | Locked motes never mutate under an FSM edge (transfers happen at the outer layer). |
| `Live_PendingProgresses` | Under weak fairness, a `pending` escrow eventually reaches a terminal status — no forever-stuck rows. |

## What it does NOT model

Deliberately out of scope; covered by other test surfaces:

- Wall-clock timing / TTLs (Python property tests, `test_expiry.py`)
- Cryptographic signatures / VRF elections (Rust proptests, `contracts/tests`)
- Off-chain oracle latency (integration tests, `test_agent_sim.py`)
- Gas / cost accounting (mainnet playbook)

Adding these to the model would explode the state space without buying
better safety guarantees; keep them where they are.
