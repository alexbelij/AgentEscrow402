# Known Limitations

Honest constraints of the current build. Each item is either an
intentional trade-off (documented here so no README claim is
overstated) or a live gap the roadmap will close.

## Multi-hop A2A choreography (AE-M1)

### IntentChainStore is an in-memory cache, not the source of truth

`server/intent_chain.py`'s `IntentChainStore` is a process-lifetime,
in-memory dict of intents and hops. It does **not** survive a restart
of the API process. This is deliberate:

- The source of truth for chain-linkage is **on-chain** — the
  `escrow-manager.link_escrows` entry point writes an append-only,
  immutable record of every `(parent_service_hash, child_service_hash,
  chain_root_hash, hop_index)` tuple to the manager contract's
  `links_dict` (`contracts/escrow-manager/src/main.rs`).
- The source of truth for attestation events is the audit trail
  (`server/audit_trace.py`) — `chain_root_hash` folds ordered
  `hop_attested` event_ids deterministically, so any observer can
  independently recompute the root off-chain and compare against the
  value written on-chain.
- `IntentChainStore` is a **query/orchestration cache** on top of
  those two ground-truth surfaces. If it's lost, the intent is
  reconstructable by reading the audit trail (for attestations) and
  the manager contract (for linkage).

**What this means in practice:** after a restart, a judge cannot
inspect an intent through `GET /intents/{id}` — that endpoint reads
the in-memory store. But the choreography itself, cryptographically,
is verifiable from on-chain state + audit events without any help
from the backend. If durable intent state matters for your use case,
persist intents to Postgres (feature not yet built — tracked in
ROADMAP as *AE-M2 IntentChain persistence*).

### On-chain anchoring is best-effort

`POST /intents/{id}/hops` will submit `escrow-manager.link_escrows`
when a Casper client is wired in and configured with a
`manager_contract_hash`. If anchoring fails (RPC unavailable,
insufficient gas, contract revert on duplicate), the in-memory hop
registration is **not rolled back** — the chain remains reconstructable
from the audit trail regardless. The failed anchoring is logged at
WARN level and the response's `on_chain_link_tx_hash` remains `null`;
retry the anchoring by calling `POST /intents/{id}/hops` again with
the same body (the manager contract's `ERROR_LINK_ALREADY_EXISTS`
guard makes double-anchoring safe).

### hop_index == 0 has no on-chain link

`link_escrows(parent, child, chain_root_hash, hop_index)` requires a
parent — hop 0 has none, so its on-chain "linkage" is implicit
(defined by the intent itself). `Hop.on_chain_link_tx_hash` is
therefore always `None` for hop 0.

### `link_escrows` entry point is not yet redeployed on testnet

As of this branch (`feat/ae402-onchain-link-escrows`), the new
`link_escrows` / `get_link` entry points on `escrow-manager` are
added, compile (WASM 174KB), and are tested at the Python + API
layer via `record_on_chain_link()` and `POST /escrow`'s
`parent_intent_id` field. The *actual on-chain redeploy* of the
updated `escrow-manager.wasm` to Casper testnet has been deferred
until further contract changes accumulate — so any live call today
against the deployed manager contract hash
(`bfa8c02cb3ab0f9d7bf03335f324973675200a597162e1e5fa4cb5a77dff675d`)
will revert on `link_escrows` (unknown entry point).

Odra property/FSM tests for `link_escrows` — tracked as **P0.1.5**
— are also pending. The `escrow-manager` module currently has no
`contracts/tests/src/*_test.rs` coverage (this was already the case
before this branch); adding them alongside the redeploy is the
right bundling.

### README stale counters (docs bug, not code bug)

`README.md` currently states `63 API endpoints` / `1591 Python
tests` / `40 Rust tests` in badges and prose. Static audit shows
the live values are `130 endpoints`, `1628 Python tests`, and `213
Rust tests` — and `40` is stale from a manifest that has zero
tests today. See
[`docs/defence/README_STATIC_AUDIT.md`](docs/defence/README_STATIC_AUDIT.md)
for the full breakdown. This is direction-safe (under-counting, not
overclaiming), but a docs PR is queued to regenerate the counters.
