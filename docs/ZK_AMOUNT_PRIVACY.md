# Zero-knowledge amount privacy (Tier Wow — W.2) — Confidential-Amount Escrows

**Status:** implemented. Both the standalone `/zk/*` demo/audit surface
(below) AND the primary escrow lifecycle (`POST /escrow`, `GET
/escrow/{service_hash}`, `POST /release|/refund|/dispute|/resolve`, plus a new
`POST /escrow/{service_hash}/reveal`) support confidential amounts — see
"Escrow lifecycle integration" below. This closes the "Future work #1" item
that originally shipped with this doc.

## How this differs from the Range-Proof Fraud Registry

AE402 also ships [docs/RANGE_PROOFS.md](RANGE_PROOFS.md), an **on-chain**,
arbiter-attested range-proof registry. Both use a Pedersen commitment +
range proof, so it's worth being explicit that these are two independent,
complementary layers, not a duplicate:

- **This doc (W.2)** hides the amount **by default, from everyone**,
  verified non-interactively by anyone off-chain (Fiat-Shamir, no
  arbiters needed), on secp256k1. It's a transactional-privacy primitive.
- **The registry** hides the amount **on-chain**, verified by a k-of-n
  **arbiter committee** on a 2048-bit group, producing an on-chain,
  disputable attestation a fraud/insurance flow can act on. It's a
  dispute-evidence primitive.

See the full comparison table in
[docs/RANGE_PROOFS.md](RANGE_PROOFS.md#how-this-differs-from-confidential-amount-escrows-w2).

## What it is

Confidential-amount escrows: the on-chain / server-visible record carries a
**Pedersen commitment** `C = r·G + v·H` to the escrow amount `v`, plus a
**range proof** that `0 ≤ v < 2^64` (u64 motes). The actual amount `v` and
blinding factor `r` are held privately by sender and receiver.

Two crypto guarantees:

1. **Hiding** — commitment leaks nothing about `v` (blinding `r` is uniform
   over a prime-order group).
2. **Binding** — no sender can open the same `C` to a different `v'` without
   solving DLOG (`log_G H`).

## Design

- **Curve:** secp256k1 (already a hard dep via `cryptography` for ECDSA in
  `server/middleware.py`). No new native dep, no PyNaCl/coincurve.
- **Generators:** `G` = standard secp256k1 base point; `H` = hash-to-curve
  of the domain separator `AE402/ZK/H/v1` via SHA-256 try-and-increment.
  Nobody knows `log_G H` → binding holds.
- **Range proof:** bit-decomposition **Chaum-Pedersen OR proof**, one per
  bit. For each bit `b_i ∈ {0,1}` publish `C_i = r_i·G + b_i·H` plus a
  Fiat-Shamir NIZK OR-proof that `C_i` opens to 0 XOR 1. Verifier checks
  each OR-proof AND that `C = Σ 2^i · C_i`.
- **Bit width:** 64 (u64 motes matches the on-chain wire).
- **Homomorphism:** `C(v1) + C(v2) = C(v1 + v2)` with blinding `r1 + r2`.

## Why not Bulletproofs?

Bulletproofs give O(log n) proof size (~700B for 64-bit vs ~33KB here), but
require inner-product-argument machinery + MSM tooling that would pull in a
native dep. For a hackathon-scale confidentiality demo, the simpler
bit-decomposition proof is sufficient and dependency-free.

## Performance (measured on hackathon pod, single-threaded pure-Python)

| Bits | Prove   | Verify  | Proof size (JSON) |
|------|---------|---------|-------------------|
| 8    | ~15 ms  | ~15 ms  | ~4 KB             |
| 16   | ~30 ms  | ~30 ms  | ~8 KB             |
| 64   | ~1.4 s  | ~1.4 s  | ~33 KB            |

The verifier cost dominates for a public audit endpoint, so the API surface
is opt-in — plain amounts remain the fast path.

## Endpoints (`/zk/*`)

Stateless, no auth (they're crypto utilities; rate-limited by the global
60 req/min IP limiter).

### `GET /zk/generators`

Returns the two group generators `G`, `H` (SEC-1 compressed hex), the
curve name, and the range-proof parameters. Deterministic — a client can
independently derive `H` from the domain and confirm.

### `POST /zk/prove`

```json
{
  "amount": 1000000,
  "transcript": "escrow-42",
  "bits": 64
}
```

Returns `{ commitment, range_proof, blinding, bits, prove_ms }`. The
caller MUST persist `blinding` privately — losing it means the escrow
cannot be opened later.

### `POST /zk/verify`

```json
{
  "commitment": "…",
  "range_proof": { … },
  "transcript": "escrow-42"
}
```

Returns `{ valid, verify_ms, bits }`. `transcript` binding prevents proof
replay across escrows.

### `POST /zk/aggregate`

```json
{
  "commitments": [{"commitment": "…"}, {"commitment": "…"}, …]
}
```

Homomorphic sum. Useful for batch-cap conservation: sum all commitments
in a batch, then verify the aggregate against a public cap.

### `POST /zk/open`

```json
{
  "commitment": "…",
  "amount": 1000000,
  "blinding": "hex(32B)"
}
```

Verifies the commitment opens to `(amount, blinding)`. Used by an
authorized receiver/auditor to confirm a disclosed amount matches.

## Escrow lifecycle integration

`server/confidential_escrow.py` bridges this primitive into the escrow
create/read/reveal path — `docs/tier3/` conventions aside, this is filed
here (not a separate doc) because it is additive behavior on the same
primitive, not a new one.

### Opting in: `POST /escrow`

Add `"confidential": true` to the existing `EscrowRequest` body:

```json
{
  "receiver": "<64-hex account hash>",
  "amount": 50000000000,
  "service_hash": "<64-hex>",
  "confidential": true
}
```

The server still computes the net amount (after the insurance fee) exactly
as for a plaintext escrow — real fund movement in this demo requires it,
and there is no on-chain amount-hiding contract (see Non-goals). What
changes is presentation: the response (and every subsequent `GET
/escrow/{service_hash}`, and the `EscrowRecord` returned by
`/release`, `/refund`, `/dispute`, `/resolve`) carries:

```json
{
  "amount": -1,
  "confidential": true,
  "commitment": "<33-byte compressed secp256k1 point, hex>",
  "range_proof_bits": 48,
  "...": "..."
}
```

`amount: -1` is a sentinel (`EscrowRequest.amount` already enforces `gt=0`,
so `-1` cannot collide with any real amount) — `confidential_escrow.REDACTED_AMOUNT`.

The range proof is bound to the escrow's own `service_hash` as its
Fiat-Shamir transcript, so it cannot be replayed as a valid proof for a
different escrow.

### Bit width: 48, not 64

The standalone `/zk/*` surface defaults to the full `AMOUNT_BITS = 64`. The
escrow lifecycle uses a narrower default,
`confidential_escrow.ESCROW_RANGE_BITS = 48` (max ≈ 281,474 CSPR at
1e9 motes/CSPR), because proving/verifying cost is ~linear in bit count and
this path runs synchronously inside the create/reveal HTTP handlers —
measured ~0.7-1.1s at 48 bits vs ~1.4-2s at 64 bits on the hackathon pod (see
the perf table above; costs are higher there than in this doc's original
measurement, likely CPU-dependent — rerun `pytest -m slow` on your own
hardware if you need current numbers). A request whose *net* amount (after
the insurance fee) doesn't fit in 48 bits gets a `422` **before** anything is
created — there is no partial state where the client sees an error but a
plaintext escrow silently exists anyway.

### Disclosure: `POST /escrow/{service_hash}/reveal`

```json
{ "blinding": "<32-byte hex, returned once at creation>" }
```

```json
{ "service_hash": "...", "amount": 49000000000, "verified": true }
```

This is the one legitimate disclosure path. It is a **cryptographic** gate,
not an **authorization** system: the endpoint proves the caller holds the
blinding factor that opens the stored commitment to the server's private
ledger amount (Pedersen's binding property makes forging a different
opening computationally infeasible) and discloses the amount only on
success (`403` otherwise). It does not itself check that the caller is the
escrow's sender/receiver/an arbiter — in this demo, possession of the
blinding (handed out once, at creation, never logged, never persisted
anywhere `blinding` could leak back into an API response) *is* the access
control. A production build would pair this with the same identity checks
that already gate release/refund/dispute.

### Where the private seal lives

`confidential_escrow._confidential_ledger` — a small module-level dict,
keyed by `service_hash`, holding `{commitment, range_proof, range_proof_bits,
blinding}`. Deliberately **not** part of `EscrowRecord` or
`SandboxStore._escrows` (those flow into API responses and best-effort
Postgres) — `blinding` must never appear in either. Like `SandboxStore`
itself, this is process-local and sandbox/demo-mode only.

## Wire format

```json
{
  "commitment": "<33-byte compressed secp256k1 point, hex>",
  "range_proof": {
    "bit_commitments": ["<33-byte compressed point hex>", …],
    "or_proofs": [
      {"a0": "…", "a1": "…", "e0": "…", "e1": "…", "z0": "…", "z1": "…"},
      …
    ]
  }
}
```

64 bit-commitments + 64 OR-proofs per full 64-bit proof.

## Threat model

- **Sender or receiver leaks `v`** — out of scope. This is a
  confidentiality primitive, not anonymity. Anyone legitimately opening
  `C` sees `v`.
- **Server-side inspection** — the server operator does not need to know
  `v`; only the commitment is persisted for confidential auditing.
- **Cross-escrow proof replay** — mitigated by the `transcript` field
  (escrow id / service_hash / …) baked into the Fiat-Shamir hash.
- **Point-at-infinity accidents** — the code detects and errors on the
  degenerate `C = ∞` case (probability ≈ 1/N ≈ 2^-256).

## Non-goals

- No integration with the on-chain CEP-18 escrow contract (that requires
  a schema and contract migration — post-hackathon).
- No sender anonymity (identity remains public via `sender_public_key_hex`).
- No full Bulletproof (see above).

## Tests

- `tests/test_zk_amount.py` — 33 unit tests: generator determinism &
  independence, commitment binding & hiding, homomorphism, range-proof
  soundness & completeness, tamper resistance, Fiat-Shamir transcript
  binding, wire round-trip, full 64-bit end-to-end (2 slow tests).
- `tests/test_zk_amount_api.py` — 8 API tests: generators endpoint,
  prove/verify round-trip, transcript negative case, open commitment,
  aggregate, out-of-range rejection.
- `tests/test_confidential_escrow.py` — 29 unit tests: `seal_amount`
  shape/binding/out-of-range, `redact_amount_field` no-op vs. redact,
  `reveal` success/wrong-blinding/wrong-amount/malformed-input,
  `verify_seal` valid/wrong-transcript/wrong-bits/tampered, the private
  ledger store, and 3 slow tests at the real `ESCROW_RANGE_BITS=48` default.
- `tests/test_confidential_escrow_api.py` — 12 API tests: create with
  `confidential=true` redacts `amount`, plain escrows unaffected, seal
  persisted privately, over-cap amount rejected with no escrow created,
  `GET` re-redacts, `reveal` success/wrong-blinding (403)/non-confidential
  (400)/nonexistent (404)/malformed-blinding (422), and confidentiality
  surviving a `/release` FSM transition.

Total: 82 tests, all green.

## Future work

1. ~~Wire into escrow create/release path~~ — **done**, see "Escrow
   lifecycle integration" above.
2. **Bulletproof upgrade** — O(log n) proof size (~700B) for a public
   audit endpoint that verifies many proofs per second.
3. **On-chain verification** in the escrow contract (requires porting
   the point arithmetic to Rust and a WASM contract redeploy).
4. **Authorization on `/reveal`** — today it is a pure cryptographic gate
   (whoever holds the blinding can disclose); pairing it with the same
   sender/receiver/arbiter identity checks that already gate
   release/refund/dispute would close the gap noted above.
5. **Async proof generation** — `seal_amount`/`reveal` currently run
   synchronously inside the request handler (~0.7-1.1s at the default 48
   bits on this hardware). Fine for a demo; a production build would move
   this to a threadpool (`fastapi.concurrency.run_in_threadpool`) so a slow
   proof can't hold up the event loop for other requests.
