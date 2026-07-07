# Agent Identity Registry (ID-1) — on-chain contract

Standalone Casper contract bringing the roadmap's "ID-1 Agent Identity Registry" item from
stub (`contracts/stubs/src/agent_registry.rs`) to a real, deployed, tested contract. Modeled on
the ERC-8004/ERC-8126 "trustless agents" pattern from Ethereum: agents self-register a DID,
stake CSPR as anti-Sybil collateral, declare capabilities, and accrue/decay a reputation score.

**Deliberately a separate contract from `escrow`/`escrow-manager`.** It does not touch or
upgrade those live, already-9-times-upgraded contracts — zero risk to the existing escrow
flows. `server/identity_registry_api.py` remains the off-chain/Postgres registry the API uses
today; this is the on-chain counterpart, addressing the previously-stub-only status.

## Deployed contract (testnet)

- Package hash: `0b760bb7bf9be5a74ee4ed5626bcc74a8154f221a059e29fc9d768d45fb4a2ba`
- Current contract hash (v2): `1f29271d986818254d42e5551dd8fbb2e2b7f7295bdfcd6558639584ad311cae`
- Source: [`contracts/agent-identity-registry/src/main.rs`](../contracts/agent-identity-registry/src/main.rs)

## Entry points

| Entry point | Who | What |
|---|---|---|
| `register_agent(capabilities, amount, source_purse)` | anyone | Registers caller with a DID, stakes `amount` (must be >= min stake, default 100 CSPR) |
| `add_stake(amount, source_purse)` | registered agent | Adds more stake to an existing record |
| `update_capabilities(capabilities)` | registered agent | Replaces declared capabilities; also applies pending reputation decay |
| `apply_decay(owner)` | anyone | Force-applies weekly reputation decay for any agent (pure function of elapsed time) |
| `request_deregister()` | registered agent | Starts a 7-day cooldown before stake can be withdrawn |
| `withdraw_stake(target_purse)` | agent in cooldown | Returns stake once cooldown has elapsed |
| `slash(agent, amount)` | installer only | Cuts stake and halves reputation (documented gap: production should gate this behind the same arbiter-quorum pattern `escrow.resolve()` uses, not installer-only — kept simple for v1) |
| `configure_min_stake(new_min_stake_motes)` | installer only | Retunes minimum stake |
| `get_agent(owner)` | anyone | Reads the full on-chain record |

## Real on-chain evidence

10 real testnet transactions (deploy + upgrade + full lifecycle across 3 distinct agent
accounts), zero failures — see
[docs/evidence/agent_identity_registry_tx_log.jsonl](evidence/agent_identity_registry_tx_log.jsonl).
Final verified state (queried live via `state_get_dictionary_item`, not just deploy-success):

| Agent | Stake (CSPR) | Reputation | Status | Notes |
|---|---|---|---|---|
| `agent_a` | 105 (100 + 10 staked, − 5 slashed) | 25 (halved by `slash`) | active | Demonstrates `register_agent` → `add_stake` → `slash` |
| `agent_b` | 100 | 50 | active | Demonstrates `update_capabilities` (3 capabilities after update) |
| `agent_c` | 100 | 50 | cooldown | Demonstrates `request_deregister` → `apply_decay` (no decay yet, correctly: <1 week elapsed) |

## Known gaps (v1, honestly scoped for the 5h/hackathon budget)

- **`slash` is installer-only**, not arbiter-quorum-gated like `escrow.resolve()`. A single key
  can slash any agent. Fine for a testnet demo of the mechanism; not production-ready as-is.
- **No reputation-increasing path yet** (only decay and slash reduce it) — a real deployment
  would need to wire this to completed-escrow counts, mirroring `escrow`'s own
  `reputation_score()`, once this registry and the escrow contract are meant to interoperate.
- **`withdraw_stake` end-to-end wasn't demoed** — the 7-day cooldown is real wall-clock time,
  not something worth faking by shortening the constant for a demo. The code path was reviewed
  and the guard logic (`now < deregistered_at + cooldown`) is covered by property tests.
- **Found and fixed during development** (both caught by cross-checking with two independent
  external AI code reviews, not by the author alone): (1) a silent `U512`→`u64` stake-amount
  truncation in `register_agent`/`add_stake` if a caller supplied a stake above `u64::MAX`
  motes — now explicitly rejected; (2) `get_blocktime()` returns **epoch-milliseconds**, not
  seconds (confirmed empirically via the real on-chain `registered_at` timestamp), so the
  initial 7-day-in-seconds cooldown/decay constants would have actually fired after ~10
  minutes — fixed by redenominating the constants in milliseconds before the first mainnet-style
  usage of the deployed contract (v2 upgrade, same package hash, state preserved).
