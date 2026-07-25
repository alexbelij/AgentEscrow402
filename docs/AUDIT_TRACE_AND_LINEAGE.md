# AE402 — Redacted Audit Trace & Merkle Lineage (AE-A2)

## What this is

A judge or auditor needs to see **what the system did** — arbitration
started, provider was picked, evidence was processed, a decision was
made, an escalation fired — without being handed raw prompts, provider
keys, wallet secrets, or user PII.

This document describes two cryptographic surfaces that together give
that guarantee:

1. **Redacted audit trace** (`server/audit_trace.py`) — a deterministic
   event log where the *shape* of each event is fixed and any
   secret-looking value is refused at the door.
2. **Merkle evidence root + inclusion verify** (`server/merkle_provenance.py`
   + `POST /arbitration/verify-evidence`) — proves that a specific piece
   of evidence was in the batch that produced a published root, without
   trusting the server that published it.
3. **Merkle lineage** (`server/audit_trace.py::LineageLink`) — links
   consecutive arbitrations / appeals into a tamper-evident chain by
   folding their evidence roots into a single lineage root.

## Redacted audit trace

### Event shape

```json
{
  "event_id":      "<sha256 of canonical pre-image>",
  "event_type":    "arbitration_start" | "evidence_processed" | ...,
  "timestamp":     "2026-07-20T12:00:00Z",
  "actor_hash":    "<sha256(actor_id)>" | null,
  "subject_hash":  "<sha256(subject_id)>" | null,
  "decision":      "favor_sender" | ... | null,
  "provider":      "groq" | "nvidia" | ... | null,
  "confidence":    0.87,
  "evidence_root": "<sha256 hex>" | null,
  "prompt_hash":   "<sha256 hex>" | null,
  "attributes":    { <flat map, allow-listed keys only> }
}
```

### What the module refuses to persist

- **Raw prompts** → hashed to `prompt_hash`, never persisted verbatim.
- **Actor / subject ids** (email, dispute id, escrow id) → hashed.
- **Secret-shaped strings** in attributes (OpenAI / Groq / NVIDIA /
  OpenRouter keys, GitHub PATs, PEM private keys, long hex strings) →
  collapsed to `[REDACTED:<shape>]`.
- **Blocked attribute keys** (`prompt`, `api_key`, `password`, `email`,
  `wallet_key`, …) → key kept, value replaced with `[REDACTED:hash]`.
- **Unknown attribute keys** → dropped silently. Key names themselves
  can leak intent, so only an enumerated allow-list survives.

### Determinism

Given the same `(event_type, timestamp, actor_id, subject_id, decision,
provider, confidence, evidence_root, prompt, attributes)`, the emitted
event is byte-identical:

- `timestamp` normalised to UTC ISO-8601 `...Z`.
- Attributes canonicalised via `json.dumps(sort_keys=True, separators=(',',':'))`.
- `event_id = sha256(canonical_preimage)`.

A judge can re-run the fixture and get the same `event_id` chain.

### Chain root

`compute_chain_root([event_id_0, event_id_1, …])` folds an ordered
sequence into a single anchor:

```
chain_0     = sha256("chain:genesis")
chain_{i+1} = sha256(chain_i || event_id_i)
```

Any tampered event → different chain root. The chain root is what a
receipt commits to on-chain (see `receipt_committed` event).

## Merkle evidence root

Every arbitration recommendation carries an `evidence_root` — a
Merkle root over the (sender-first, receiver-second) evidence set the
arbitrator saw at decision time. Semantics are byte-identical to the
RWA-Sentinel `merkleProvenance.ts` port.

### `POST /arbitration/verify-evidence`

The UI "verify" button. Given a `(leaf, siblings[], expected_root)`
triple, the server folds the proof and reports whether the running
hash equals the root. **The endpoint is a convenience** — the same
math runs client-side and the result must match. Trust nothing;
verify.

Request:

```json
{
  "leaf": "<sha256 hex>",
  "siblings": [
    { "hash": "<sha256 hex>", "position": "left" | "right" }
  ],
  "expected_root": "<sha256 hex>"
}
```

Response:

```json
{
  "valid": true,
  "computed_root": "<sha256 hex>",
  "expected_root": "<sha256 hex>",
  "steps": 3,
  "reason": null
}
```

`400` on malformed hex, unknown position, or wrong-length root/leaf.
`200` always for well-formed requests; `valid: false` when the fold
does not converge to `expected_root`, with `reason` set.

## Merkle lineage — multi-step arbitration

An arbitration is rarely one-shot. An **appeal** references the
evidence set of the original arbitration; a **multi-step batch**
threads intermediate arbitrations into a final one. To keep the
derivation chain tamper-evident:

```
link_hash_i     = sha256(parent_root_i || current_root_i || step_index_i)
lineage_0       = sha256("lineage:genesis")
lineage_{i+1}   = sha256(lineage_i || link_hash_i)
```

`LineageLink(parent_evidence_root, current_evidence_root, step_index)` is
the primitive; `compute_lineage_root(links)` folds them.

### Use cases

- **Appeal v2** cites the original arbitration's evidence root and
  produces a lineage root the judge can verify.
- **Multi-step**: e.g. an evidence-collection arbitration feeds a
  decision arbitration; each step publishes its lineage root.

## Tests

- `tests/test_merkle_provenance.py` — 30 tests (existing, unchanged):
  determinism, leaf sensitivity, odd/even/empty batches, inclusion,
  tampered-root rejection.
- `tests/test_audit_trace.py` — 24 tests: determinism, PII/secret
  redaction, blocked/unknown-key handling, timestamp normalisation,
  chain root order sensitivity, lineage link stability, full
  arbitration scenario reproducibility, JSON round-trip.
- `tests/test_arbitration_verify_endpoint.py` — 8 tests: valid proof,
  tampered root, wrong leaf, malformed leaf/root/position, single-leaf
  batch, all-positions coverage on 4-leaf batch.

62 dedicated tests, full suite `624 passed`.

## Deliberate non-goals

- **No storage** in this module. Persistence is the caller's job —
  audit_trace.py emits, the caller decides where events go
  (Postgres, on-chain, filesystem, ...). Keeps the primitive pure.
- **No signing** in this module. Signed receipts are a separate
  concern (`arbiter_crypto.py` handles arbiter signatures over
  `analysis_hash` already, which now folds in `evidence_root`).
- **No client-side crypto shim** here. The JS-side proof verifier is
  the RWA-Sentinel `merkleProvenance.ts` port — same tree math, same
  vectors.
