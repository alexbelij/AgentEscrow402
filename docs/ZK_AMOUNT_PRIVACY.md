# Zero-knowledge amount privacy (Tier Wow — W.2)

**Status:** implemented, opt-in demo/audit surface. Not yet on the primary escrow write path.

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

Total: 41 tests, all green.

## Future work

1. **Wire into escrow create/release path** as an opt-in
   `use_confidential_amount: true` flag on `EscrowRequest`. Server would
   verify the range proof at create-time, store the commitment, and only
   reveal the amount at release/refund time (with sender's opening).
2. **Bulletproof upgrade** — O(log n) proof size (~700B) for a public
   audit endpoint that verifies many proofs per second.
3. **On-chain verification** in the escrow contract (requires porting
   the point arithmetic to Rust and a WASM contract redeploy).
