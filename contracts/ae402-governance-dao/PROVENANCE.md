# Provenance — ae402-governance-dao

This contract's proposal-lifecycle primitives (proposal record shape,
status state machine, weighted voting, delegation-aware voting power,
30% quorum with 7-day voting window, veto flow, `register_voter`
pattern) are **ported** from the RWA-Sentinel Governance DAO. The AE402
**action layer, execution-attestation message, cross-contract
integration points, and target-contract dispatch model** are net-new
and specific to AE402.

## Source

- **Upstream repo**: [`triumphkrug/RWA-Sentinel`](https://github.com/triumphkrug/RWA-Sentinel)
- **Upstream path**: `contracts/governance-dao/src/main.rs`
- **Upstream commit reviewed for this port**: `main` @ 2026-07-25
- **License**: Apache-2.0

## Reused primitives (structural port)

| Primitive | Upstream location | Notes |
|---|---|---|
| `ProposalRecord` nested-tuple shape | main.rs § "Record types" | Kept structurally identical so the storage format stays compatible with any future cross-DAO tooling. |
| Status codes 0–5 (ACTIVE/PASSED/REJECTED/EXECUTED/VETOED/EXPIRED) | main.rs § "Status codes" | Identical semantics. |
| `register_voter` + `total_staked` bookkeeping | main.rs § `register_voter` | Same installer-guarded pattern; identical stake-delta math. |
| `get_voting_power` delegation semantics (delegators forfeit power) | main.rs § `get_voting_power` | Same rule. |
| `vote` weighted-vote flow + `min(weight, voting_power)` clamp | main.rs § `vote` | Same. |
| Quorum math: `(total × percent) / 100`, threshold-then-decision | main.rs § `vote`, `execute_proposal` | Factored into pure `resolve_status()`; property-tested. |
| 30% quorum, 7-day voting window | main.rs constants | Kept as constants; AE402 governance surface may bump these via `UPDATE_TIMELOCK_DELAY` in a follow-up. |
| `veto_proposal` (installer-only) | main.rs § `veto_proposal` | Same. |
| `delegate` (self-delegation reject) | main.rs § `delegate` | Same. |
| Nested-tuple `get_proposal` return shape (3-elt cap) | main.rs § `get_proposal` | Same shape; extra field is our AE402-specific `target_contract`. |

## Net-new (AE402-specific, not from RWA-S)

- **Action codes** `ADJUST_FEE_BPS`, `ROTATE_ARBITER_SET`,
  `UPDATE_INSURANCE_POOL_PARAMS`, `UPDATE_TIMELOCK_DELAY`,
  `UPDATE_RANGE_PROOF_PARAMS`, `PAUSE_PROTOCOL` and the corresponding
  strongly-typed `ActionParams` enum + `parse_params()` schema
  validator. RWA-S ships oracle-focused actions (`UPDATE_WEIGHTS`,
  `ADD_ORACLE`, `REMOVE_ORACLE`, `UPDATE_THRESHOLD`, `PAUSE`) — these
  were dropped, not reused.
- **`target_contract` field** on the proposal-details record — the
  cross-contract dispatch target. Empty in RWA-S.
- **`build_execution_message()`** — domain-separated
  (`ae402:governance-dao:exec:v1`) binding message for arbiter
  attestations. Not present in RWA-S.
- **`get_exec_log()` entry point** + `exec_log` dictionary — records
  what was executed for the on-chain audit trail. Not present in RWA-S.
- **Pull-model execution semantics** — the DAO records a decision, the
  target contract reads it in its own admin path. RWA-S executes
  inline. This composes with the AE402 `timelock-admin` delay and
  avoids one-block re-entrancy.
- **Full Python SDK byte-parity** with the Rust library
  (`sdk/governance.py`), including the exec-message and quorum math.
- **Property + lifecycle test suite** (100 tests) covering the
  AE402-specific schema and the pure-function extraction — factored
  out of the WASM binary so std-only tests can consume them.

## Diff summary

| Metric | Value |
|---|---|
| Upstream LOC (main.rs) | 556 |
| This contract LOC (lib.rs + main.rs) | ~1,100 |
| Overlap (structurally similar) | ~30% |
| Net-new lines | ~750 |
| Rust tests | 49 property + unit (all pure-function coverage) |
| Python tests | 58 (51 parity + 7 lifecycle) |

## License

Both AE402 and RWA-Sentinel ship under **Apache-2.0**. This port keeps
the same license. When you use, copy, or redistribute this file, retain
this notice. See the AE402 `LICENSE` in the repo root.
