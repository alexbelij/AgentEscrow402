# AE402 Governance DAO

On-chain governance for the AE402 protocol. Weighted-vote proposals over
a 30% quorum and 7-day voting window drive updates to the AE402 admin
surface: fee, arbiter set, insurance-pool caps, timelock delay,
range-proof parameters, and the emergency pause switch. This document
covers the on-chain shape, the SDK, the execution model, and the
threat model.

- **Contract**: `contracts/ae402-governance-dao/`
- **WASM**: `ae402-governance-dao.wasm` (~155 KB release build)
- **Python SDK**: `sdk/governance.py`
- **Provenance**: Governance primitives are ported from RWA-Sentinel under
  Apache-2.0. Full attribution:
  [`contracts/ae402-governance-dao/PROVENANCE.md`](../contracts/ae402-governance-dao/PROVENANCE.md)

## TL;DR

1. Installer `register_voter`s every staker's voting power.
2. Any account calls `create_proposal(title, description, action_type, params, target_contract)`.
3. Registered voters call `vote(proposal_id, support, weight)` until quorum is met.
4. `execute_proposal(proposal_id)` writes the decision + params-hash into the on-chain `exec_log`.
5. The target AE402 contract (`timelock-admin`, `insurance-pool`, `challenge-arbiter`,
   `range-proof-registry`, `escrow`) reads the decision from `exec_log` in its own
   admin-guarded entry point and applies the change.

The full lifecycle is exercised end-to-end in
[`tests/test_governance_dao_lifecycle.py`](../tests/test_governance_dao_lifecycle.py).

## Actions & schemas

Params are encoded as `key=value;key=value` — a no-serde, gas-cheap wire
format enforced by `parse_params()` in the pure-logic library, so
malformed proposals are rejected at creation, not at execution.

| Code | Action | Params schema | Target contract |
|---|---|---|---|
| 0 | `ADJUST_FEE_BPS` | `bps=<u64>` (0..=10 000) | `escrow` |
| 1 | `ROTATE_ARBITER_SET` | `op=<add|remove|threshold>;value=<hex-pk-66 \| decimal>` | `challenge-arbiter` |
| 2 | `UPDATE_INSURANCE_POOL_PARAMS` | `max_coverage_bps=<u64>;cooldown_sec=<u64>` | `insurance-pool` |
| 3 | `UPDATE_TIMELOCK_DELAY` | `delay_sec=<u64>` (>= 3600) | `timelock-admin` |
| 4 | `UPDATE_RANGE_PROOF_PARAMS` | `min_bits=<u64>;max_bits=<u64>` (1..=32) | `range-proof-registry` |
| 5 | `PAUSE_PROTOCOL` | `mode=<pause \| unpause>` | Multiple |

### Rejected at creation

- `bps > 10 000` → invalid fee.
- Arbiter public key not exactly 66 hex characters → wrong length.
- Arbiter threshold `0` or `> 64` → not enforceable.
- Timelock `delay_sec < 3600` → below the 1-hour minimum.
- Range-proof `min_bits > max_bits` or either outside [1, 32].
- Unknown pause mode.

Every rejection has a Rust proptest counterpart and a Python parity test.

## Execution model — pull, not push

`execute_proposal` records a **decision**, not a **direct call**. It
writes the exec-log entry:

```
exec_log[proposal_id] = (SHA(EXECUTION_DOMAIN:pid:action:params), executed_at, executor)
```

where `EXECUTION_DOMAIN = "ae402:governance-dao:exec:v1"`. The target
AE402 contract (e.g. `insurance-pool`) then reads that entry in its own
`apply_governance_update` entry point and mutates its state — but only
after the timelock-admin delay has elapsed and only if the exec-log
hash matches the params it's asked to apply.

### Why pull, not push

1. **Composes with timelock-admin.** A DAO push that lands in the same
   block as the vote would bypass the timelock. A pull requires the
   target contract to enforce the delay itself — the timelock stays
   authoritative.
2. **Avoids one-block re-entrancy.** Casper's execution model doesn't
   have Ethereum-style re-entrancy vectors, but a direct cross-contract
   call chain is still harder to audit than a data-driven update read
   at deploy time.
3. **Composes with veto.** Because the target contract reads the log at
   apply-time (not at execute-time), a `veto_proposal` before the
   timelock elapses cancels the effect — no post-hoc undo needed.
4. **Composes with `two-key-account`.** The two-key admin path can
   require a second Ed25519 signature over the exec-log hash before
   applying — the DAO decides *what*, the two-key gate decides *who
   pushes the button*.

## Voting power & delegation

- `register_voter` is installer-only. Staking or holder-registry
  wiring is out of scope for this contract — deliberately, so the DAO
  can be composed with any future AE402 stake model.
- `delegate(to)` puts your voting power into another account. From
  that moment your own `voting_power` returns 0 and only `to` can
  spend it. Self-delegation is rejected on-chain.
- On `vote(support, weight)`, the effective weight is
  `min(requested_weight, voting_power)` — you can never vote for more
  than you have.
- The quorum check triggers **early finalization**: the moment
  `votes_for + votes_against >= 30% * total_staked`, the proposal is
  resolved (PASSED if for > against, else REJECTED). No need to wait
  out the 7-day window if quorum is decisively met.

The `resolve_status()` pure function is proptested in
`contracts/tests/src/governance_dao_property_tests.rs` — every
transition it can emit is one of `ACTIVE | PASSED | REJECTED |
EXPIRED`; `EXECUTED` and `VETOED` are only set by their respective
entry points.

## Threat model

### Whale voting (concentration risk)

A voter with `>= 30%` stake can single-handedly meet quorum and pass
any proposal by voting YES. This is not a bug — it's the definition of
weighted governance. AE402 mitigates it in three ways:

1. **Timelock delay.** Even a whale-passed proposal doesn't apply
   instantly; the target contract enforces `timelock-admin`'s delay.
2. **Veto power.** The `installer` (in AE402: the two-key smart
   account) can `veto_proposal` before execution. This is the
   escape hatch for a whale attack.
3. **Range-proof action ceiling.** The AE402 governance surface is
   deliberately narrow — the DAO **cannot** move funds directly; it
   can only tune parameters bounded by hard caps (fee ≤ 10 000 bps,
   insurance coverage ≤ 10 000 bps, timelock ≥ 1h, range bits ≤ 32).
   A whale who takes over the DAO cannot drain the treasury.

### Quorum-bypass via `total_staked` manipulation

Because quorum is `30% * total_staked`, a malicious installer could
inflate `total_staked` by `register_voter`-ing a straw account with a
huge stake — then a small friendly minority meets the "quorum". Two
mitigations:

1. `register_voter` is installer-guarded. If the installer is
   compromised, the whole protocol is compromised — there's no
   local governance-only surface to attack.
2. The two-key installer + timelock gates this: an installer trying to
   register a new voter still has to satisfy the two-key path.

### Execution race between vote-close and execute

Between "voting window closes" and "someone calls execute", a proposal
sits with `status = ACTIVE` even though it's really `PASSED`/`REJECTED`/`EXPIRED`.
`execute_proposal` **late-finalizes** — it calls `resolve_status()`
before checking `PASSED`, so a stale ACTIVE row does not stall or
mis-execute. The Rust proptest `status_only_emits_known_codes` covers
this exhaustively.

### Timelock ↔ DAO deadlock

Scenario: the DAO passes a proposal to `UPDATE_TIMELOCK_DELAY` to a
value so high that no future proposal can ever land within a reasonable
window. Mitigations:

- Hard minimum: `delay_sec >= 3600` is enforced in `parse_params()`.
- No hard **maximum** is enforced. This is deliberate — a hard-max
  would be another value the DAO could game. The `installer` veto is
  the escape hatch: a veto works during the current-timelock window,
  which is at most the *old* delay, not the new one.

### Vote replay across proposals

Vote records are keyed by `(proposal_id, voter_account_hash)` in the
`votes` dictionary. A YES-vote on proposal 5 cannot be replayed as a
YES-vote on proposal 6 — different key.

### Params-substitution attack at execute time

Attack: a malicious executor calls `execute_proposal(pid)` but
substitutes params. Mitigation: params are read from
`proposal_details[pid]`, not from the executor's arguments;
`execute_proposal` takes only `proposal_id`. The exec-log records the
canonical params hash, so the target contract can reject any apply
call whose params don't match.

## SDK usage

```python
from sdk.governance import (
    AdjustFeeBps, UpdateTimelockDelay, PauseProtocol,
    encode_params, build_execution_message,
)

# Compose a proposal payload
action, params_str = encode_params(AdjustFeeBps(bps=500))
# → action = 0, params_str = "bps=500"

# The message the on-chain execute pathway pins
msg = build_execution_message(proposal_id=1, action_code=action, params_str=params_str)
# → "ae402:governance-dao:exec:v1:1:0:bps=500"
```

All schemas validate client-side first — an invalid `AdjustFeeBps(bps=10_001)`
raises `GovernanceError` before any Casper deploy fee is spent.

## Test coverage

| Layer | File | Tests |
|---|---|---|
| Rust pure logic | `contracts/tests/src/governance_dao_property_tests.rs` | 49 |
| Python parity + errors | `tests/test_governance_dao_parity.py` | 51 |
| Python lifecycle | `tests/test_governance_dao_lifecycle.py` | 7 |
| **Total** | | **107** |

The pre-existing AE402 suite (185 tests before #11) stays green.

## Related

- [`docs/TIMELOCK_ADMIN.md`](TIMELOCK_ADMIN.md) — the delay layer the DAO
  composes with.
- [`docs/MACAROONS.md`](MACAROONS.md) — capability delegation model; DAO
  proposals can rotate macaroon-issuing keys via
  `ROTATE_ARBITER_SET`.
- [`docs/RANGE_PROOFS.md`](RANGE_PROOFS.md) — the range-proof registry;
  DAO tunes its bit-width bounds via `UPDATE_RANGE_PROOF_PARAMS`.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — where governance sits in
  the AE402 stack.
