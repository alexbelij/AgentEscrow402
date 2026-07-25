# Range Proofs on Amounts

**Status:** shipped in `contracts/range-proof-registry/` + `sdk/range_proof.py` on branch `feat/ae402-range-proofs`.

## Why this exists

For some AE402 flows the settled amount is commercially sensitive
(escrow between two agents whose competitors index the chain; enterprise
usage where the *fact* of a payment is public but the *quantum* is
under NDA; adaptive fee routing where publishing the exact amount lets
a downstream layer front-run future flows). We want a way to lock an
escrow to a specific amount, prove on-chain that this amount is
inside a declared business-legal range (e.g. `[MIN_INVOICE, MAX_ESCROW_MOTES]`),
settle against the correct value, but keep the amount itself opaque
on the ledger until the parties opt to reveal it.

This document defines the on-chain contract, the off-chain proof
format, the arbiter workflow, and the honest threat model — including
what this design does NOT protect against, so readers don't assume
guarantees that aren't there.

## Design summary

Casper's WASM host exposes Ed25519 verification but no big-integer
modular exponentiation and no elliptic-curve pairings. A
Bulletproofs-style range-proof verifier does not fit in a realistic
gas budget on Casper today. AE402 therefore uses an
**arbiter-attested** verification model:

1. **Hiding commitment on-chain.** The prover publishes a Pedersen
   commitment `C = g^amount * h^randomness mod p` under a 2048-bit
   safe-prime group. The commitment is hiding (uniform `randomness`
   makes it statistically indistinguishable from a random group
   element) and binding (opening to a different amount requires
   solving the discrete-log problem).
2. **Proof hash on-chain.** The prover also publishes
   `blake2b(canonical_proof)`, where the canonical proof is a
   deterministic byte encoding of `(commitment, min, max, amount, randomness)`
   — see `sdk/range_proof.RangeProof.to_bytes`. The **proof itself is
   sent privately** to the arbiter set; only its hash goes on-chain.
3. **Off-chain verification.** Each arbiter runs
   `sdk/range_proof.py::verify_range_proof` deterministically: it
   checks that `min <= amount <= max` AND that
   `g^amount * h^randomness == commitment`. If both pass, the arbiter
   signs the canonical attest preimage (see below) with its Ed25519
   key and submits the signature via `attest()`.
4. **Threshold flip.** The contract verifies each signature on-chain,
   deduplicates attesters, and counts. Once
   `attest_count >= threshold`, anyone can call `finalize()` to move
   the record from `Pending` to `Verified`. Downstream settlement
   contracts (escrow.rs, multi-asset-escrow.rs) treat
   `get_status_ep(escrow_id) == 2 (Verified)` as an on-chain
   assertion that the hidden amount is in `[min, max]`.
5. **Opening at settlement.** When the escrow settles the party may
   publish `(amount, randomness_hash)` via `open()`. The contract
   enforces `min <= amount <= max`. Off-chain, any observer with the
   randomness can recompute `g^amount * h^randomness == C` and
   dispute via `mark_fraud` if the two disagree.

## Contract API

### Named storage

Per-escrow record dictionaries (keyed by `escrow_id_hex`, 64-char
lowercase hex):

| Dictionary | Type | Purpose |
|---|---|---|
| `rec_commitment` | `String` (hex) | `g^amount * h^r mod p` |
| `rec_proof_hash` | `String` (64-hex) | `blake2b(proof)` |
| `rec_min`, `rec_max` | `u64` | Declared inclusive range |
| `rec_arbiter_set_hex` | `Vec<String>` | Attesters allowed for this record |
| `rec_threshold` | `u32` | Attestations required to Verify |
| `rec_attest_count` | `u32` | Current attestation count |
| `rec_attesters_hex` | `Vec<String>` | Deduped attester public keys |
| `rec_status` | `u8` | 0 Unset · 1 Pending · 2 Verified · 3 Opened · 4 Fraud |
| `rec_opened_amount` | `u64` | Publicly opened amount |
| `rec_opened_r_hash` | `String` | Publicly opened randomness hash |

### Entry points

```
init(admin: String, self_package_hash: String) -> ()   // called once by call()

register_commitment(
    escrow_id_hex: String,          // 64 lowercase hex chars
    commitment_hex: String,         // Pedersen commitment, hex; 1..=512 bytes decoded
    proof_hash_hex: String,         // 64 lowercase hex chars, non-zero
    min_amount: u64,
    max_amount: u64,                // >= min_amount, > 0
    arbiter_set_hex: Vec<String>,   // 1..=32 unique hex-encoded Ed25519 pubkeys
    threshold: u32,                 // 1..=len(arbiter_set_hex)
) -> ()
// Effect: creates a Pending record. Idempotent: re-registering the same
// escrow_id reverts with ERR_ALREADY_REGISTERED.

attest(
    escrow_id_hex: String,
    attester_hex: String,           // must be in rec_arbiter_set_hex
    signature_hex: String,          // Ed25519 sig over attest_preimage
) -> ()
// Verifies signature over the canonical attest preimage (see below),
// requires status = Pending, deduplicates attester, increments count.

finalize(escrow_id_hex: String) -> ()
// Requires status = Pending AND attest_count >= threshold; flips to Verified.

open(
    escrow_id_hex: String,
    amount: u64,
    randomness_hash_hex: String,    // 64 hex chars, non-zero
) -> ()
// Requires status = Verified; enforces min <= amount <= max; flips to Opened.

mark_fraud(
    escrow_id_hex: String,
    attester_hex: String,           // must be in rec_arbiter_set_hex
    signature_hex: String,          // Ed25519 sig over fraud_preimage
    reason_hash_hex: String,        // 64 hex chars — attester's dispute reason hash
) -> ()
// Requires status ∈ {Pending, Verified, Opened}; flips to Fraud (terminal).

// Read entry points return CLValue-wrapped scalars.
get_status_ep(escrow_id_hex: String) -> u8
get_commitment_ep(escrow_id_hex: String) -> String   // hex or ""
get_attestation_count_ep(escrow_id_hex: String) -> u32
get_opened_amount_ep(escrow_id_hex: String) -> u64
get_range_ep(escrow_id_hex: String) -> (u64, u64)
```

### State machine

```
Unset
  └─ register_commitment ──▶ Pending
                              │
                              ├─ threshold attests + finalize ──▶ Verified
                              │                                     │
                              │                                     ├─ open ──▶ Opened ──┐
                              │                                     │                    │
                              │                                     └─ mark_fraud ──▶ Fraud (terminal)
                              │                                                          ▲
                              └─ mark_fraud ──────────────────────────────────────────────┤
                                                                                          │
                                              mark_fraud from Opened (post-mortem) ───────┘
```

All illegal transitions revert with `ERR_STATUS_TRANSITION`.

## Canonical preimages

Every arbiter signature is Ed25519 over a **domain-separated,
ASCII, single-line, colon-delimited** preimage that embeds this
deployment's `self_package_hash`. Byte-for-byte parity is enforced in
`contracts/tests/src/range_proof_registry_property_tests.rs` and
`tests/test_range_proof_sdk.py`.

**Attest** (signed by arbiters attesting the proof verifies):

```
ae402:range-proof:v1:attest:<self_package_hash_hex>:<escrow_id_hex>:<commitment_hex>:<proof_hash_hex>:<min>:<max>
```

**Fraud** (signed by arbiters disputing the record):

```
ae402:range-proof:v1:fraud:<self_package_hash_hex>:<escrow_id_hex>:<commitment_hex>:<proof_hash_hex>:<reason_hash_hex>
```

Fields:

* `<self_package_hash_hex>` — 64 lowercase hex chars, the deployment's
  Casper `ContractPackageHash`. Different deployment ⇒ different
  signature domain. A signature made against deployment A cannot be
  replayed on deployment B.
* `<escrow_id_hex>` — 64 lowercase hex, business-supplied identifier.
* `<commitment_hex>` — the Pedersen commitment, hex, variable length
  up to 512 bytes decoded.
* `<proof_hash_hex>` — 64 lowercase hex, `blake2b_32(canonical_proof)`.
* `<min>`, `<max>` — u64 in ASCII decimal, no leading zeros (except 0
  itself). Matches Python `str(int)` and the no_std `u64_to_dec`
  helper.
* `<reason_hash_hex>` — 64 lowercase hex, attester's private choice.

## Off-chain proof format

Canonical byte encoding (see `sdk/range_proof.RangeProof.to_bytes`):

```
ae402:range-proof:v1:proof:<commitment_hex>:<min>:<max>:<amount>:<randomness>
```

Hashed with `blake2b(digest_size=32)`. The prover sends the raw
`(amount, randomness)` privately to arbiters; only the hash goes
on-chain.

## Threat model

### What this design protects against

1. **Cross-deployment signature replay.** Each preimage embeds
   `self_package_hash`. A signed attest for deployment A never
   verifies against deployment B — so leaking a signature after
   escrow settlement cannot compromise a different deployment.
2. **Cross-role signature replay.** The `:attest:` vs `:fraud:` domain
   tag means an attester who signs attest cannot have their signature
   silently repurposed as a fraud dispute (or vice versa).
3. **Cross-escrow signature replay.** `escrow_id_hex` is in the
   preimage; an attest for escrow A never verifies for escrow B.
4. **Range fabrication.** The `(min, max)` pair is in the preimage;
   a proof attested for `[100, 500]` cannot be reused as evidence for
   `[100, 999]`.
5. **Duplicate attestation stuffing.** `attest()` deduplicates
   attester public keys, so one arbiter cannot inflate `attest_count`
   toward the threshold on their own.
6. **Range violation at open.** `open()` enforces
   `min <= amount <= max` at the contract level, so a Verified record
   cannot be opened to an amount outside its declared range even if
   the arbiter set later goes rogue.
7. **Post-settlement dispute.** `mark_fraud` remains callable from
   `Opened`, so a dispute discovered after settlement can still be
   recorded on-chain for downstream slashing paths (in
   `challenge-arbiter` and the insurance pool).

### What this design does NOT protect against — read carefully

1. **Arbiter collusion.** If `threshold` arbiters collude, they can
   attest a Pedersen commitment that opens to an amount OUTSIDE
   `[min, max]`. Mitigation: pick the arbiter set from independent
   parties (see `vrf-arbiter` for randomised selection), and set
   `threshold` high enough that collusion is expensive. **This is
   the same trust model as any k-of-n oracle system.** Full ZK
   range-proofs would remove this, but Casper's WASM host cannot
   verify them today.
2. **Discrete-log break of the 2048-bit group.** The commitment's
   binding property rests on the discrete-log problem in a
   2048-bit safe prime. If someone can compute `log_g(h)`, they can
   open the commitment to any amount. `h` is derived via a NUMS
   procedure (`sha512("ae402:range-proof:v1:h_generator")` squared
   mod p) so **no party can be pre-baked** into the setup.
3. **Randomness reuse.** If the prover uses the same `randomness`
   for two different commitments, an observer can subtract them and
   the commitments become homomorphically linked. Provers MUST use
   fresh cryptographic randomness for each commitment — the SDK's
   `pedersen_commit()` default does this correctly.
4. **On-chain amount at `open()`.** Once `open()` runs, the amount is
   public on-chain. This is by design (settlement time) but note
   there is no post-open "unwind" back to Verified.
5. **Metadata leakage.** The commitment length and byte pattern
   depend on the commitment integer's bit-length; two very-different
   commitment values may still be distinguishable by cursory
   observers. If leakage of "commitment ≈ big" vs "commitment ≈
   small" matters, pad the commitment to a fixed 256-byte length
   client-side (the contract accepts any length up to 512 bytes).
6. **Verifier gas.** The contract stores hex-encoded commitments up
   to 512 bytes decoded. Very large commitments cost proportionally
   more gas at `register_commitment` time; benchmarks show ~200-byte
   commitments (1600-bit) are the sweet spot for the current 2048-bit
   group config.

## Integration with escrow.rs

`escrow.rs` is intentionally NOT modified in this branch (single-PR
rule + risk containment). To wire the two contracts together in a
follow-up PR:

1. Add a `range_proof_registry_pkg` named-key to escrow.rs at deploy.
2. In `settle()` / `resolve()`, before releasing purse funds, do a
   `runtime::call_contract(registry, "get_status_ep", ...)` to check
   status. Refuse to release if the record is not `Verified` or
   `Opened`.
3. When the escrow uses range-proofs (opt-in via a new
   `range_locked: bool` field), require the settling amount to match
   `rec_opened_amount` — falling back to `escrow.amount` when the
   escrow does not use range-proofs.

That wiring PR is small (~50 LOC) and does not require rebuilding
the on-chain testing infra.

## Test evidence

* `contracts/tests/src/range_proof_registry_property_tests.rs` —
  32 tests (14 proptest + 18 unit/scenario): preimage injectivity in
  every field, domain separation, state-machine safety, threshold
  gate, open-range invariant, hex codec round-trip, terminal fraud.
* `tests/test_range_proof_sdk.py` — 42 tests: Pedersen commit +
  hiding invariants, range-proof happy/tamper paths, canonical
  preimage byte-parity with Rust, Ed25519 sign/verify with tamper
  rejection on every field, cross-deployment replay resistance,
  full-workflow `build_register_bundle` happy path.
* `cargo build -p range-proof-registry --target
  wasm32-unknown-unknown --release` — WASM binary
  (`range-proof-registry.wasm`) builds cleanly at 302 KB.
* Full existing test suite (`cargo test -p tests`) — no regressions.

## Follow-ups (not in this PR)

* **True ZK range proofs.** When Casper adds a big-int modexp or
  BN254/BLS12-381 pairing host function, replace
  `verify_range_proof` with a Bulletproofs-style verifier and add a
  parallel `finalize_zk()` path that bypasses arbiter attestations
  when a ZK proof is present. The arbiter path stays as a fallback.
* **Cross-contract wiring** with `escrow.rs` and
  `multi-asset-escrow.rs` (see "Integration" above).
* **Insurance-pool slash** for arbiters who signed
  `attest` and are later proven wrong by a `mark_fraud` majority.
  Wire on top of the `challenge-arbiter` contract's slash primitives.
