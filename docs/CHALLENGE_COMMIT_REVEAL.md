# Challenge-window & commit-reveal arbiter selection

Additive dispute-resolution layer that sits alongside the existing
`escrow::dispute()` + `escrow::resolve()` 3-of-5 multisig path. Introduced in
`contracts/challenge-arbiter/`. The name is deliberate: it covers **both**
sub-features from the AE402 roadmap step 9:

- **9a — Challenge-window improvements**: any dispute now requires a
  `challenge_bond`, has explicit `commit_deadline` and `reveal_deadline`
  timelocks, and slashes arbiters who commit but never reveal.
- **9b — Commit-reveal arbiter selection**: an arbiter's verdict is not
  observable on-chain until the reveal phase. The commit is a BLAKE2b-256
  hash of a caller-controlled preimage bound to `(dispute_id, verdict,
  nonce, arbiter_pk)` and to this contract's package hash. An attacker
  cannot target a specific arbiter without breaking Ed25519 + a private
  32-byte nonce.

The new contract is **additive-only**: `escrow.rs` is untouched, the 597
existing contract tests still pass. Cross-contract wiring (calling
`challenge-arbiter::finalize()` from `escrow::resolve()`) is left as a
follow-up so this PR carries zero risk of breaking on-chain state.

## Contract entry points

Config (installer-only, one-shot):

| Fn | Purpose |
|----|---------|
| `set_config(challenge_bond, arbiter_bond, commit_window_ms, reveal_window_ms, threshold)` | Bond amounts, timelocks, quorum. |
| `set_arbiter_registry(pubkeys)` | Hex-encoded Ed25519 pubkeys eligible to commit. |
| `lock_config()` | Freeze the above; irreversible. |

Flow (public):

| Fn | Called by | Effect |
|----|-----------|--------|
| `open_challenge(dispute_id, service_hash, challenger, posted_bond, now_ms)` | challenger | Opens a `STATUS_COMMIT_PHASE` challenge with `challenge_bond`. Reverts if `dispute_id` already exists. |
| `commit_verdict(dispute_id, arbiter_pk, commit_hex, arbiter_bond, now_ms)` | arbiter | Posts a 32-byte BLAKE2b hash of the reveal preimage plus `arbiter_bond`. Reverts if the pubkey is not in the registry, if commit window is closed, or if the arbiter has already committed. |
| `begin_reveal_phase(dispute_id, now_ms)` | anyone | Transitions from commit → reveal after `commit_deadline`. |
| `reveal_verdict(dispute_id, arbiter_pk, verdict, nonce_hex, recomputed_commit_hex, signature_hex, now_ms)` | arbiter | Reveals the verdict. Enforces `stored_hex == recomputed_hex` AND an Ed25519 signature over the canonical preimage. |
| `slash_non_revealer(dispute_id, arbiter_pk, now_ms)` | anyone | After `reveal_deadline`, permanently marks a committed-but-not-revealed arbiter as slashed. Idempotent (double-slash reverts). |
| `finalize(dispute_id, sender_reveal_count, receiver_reveal_count, now_ms)` | anyone | After `reveal_deadline`. Applies threshold + majority rule. Returns a `STATUS_FINALIZED_*` value. |

Reads: `get_challenge`, `get_commit`, `get_reveal`.

## Status enum

- `1` `STATUS_PENDING` (reserved)
- `2` `STATUS_COMMIT_PHASE`
- `3` `STATUS_REVEAL_PHASE`
- `4` `STATUS_FINALIZED_CHALLENGER_WINS`
- `5` `STATUS_FINALIZED_STATUS_QUO`
- `6` `STATUS_FINALIZED_FAILED_QUORUM`

Terminal statuses reject any further transition. `finalize()` explicitly
reverts with `ERR_ALREADY_FINALIZED (16)` on re-call. Verified by property
test `prop_terminal_never_refinalize`.

## Verdict enum

Verdict is `1 = sender` or `2 = receiver`. Any other integer reverts on
reveal with `ERR_INVALID_VERDICT (18)`. Verified by unit test
`preimage_deterministic_for_same_inputs` + Python SDK
`test_preimage_rejects_invalid_verdict`.

## Commit-reveal cryptography

### Canonical preimage

```
ae402:challenge:v1:reveal:{self_package_hash}:{dispute_id}:{verdict}:{nonce_hex}:{arbiter_pk_hex}
```

- Domain separator `ae402:challenge:v1` — never overlaps with any other
  contract in this repo (`two-key-account` uses `ae402:two-key:v1`).
- `self_package_hash` is stored on install and is unique per deployment.
  This is what prevents a signature from staging being replayed on
  mainnet.
- `verdict` is written as unpadded ASCII decimal via the same
  `u64_to_decimal` helper used by `two-key-account`.
- Delimiter `:` is safe because every field is a fixed-alphabet string
  (hex, dispute-id identifiers, or decimal digits). No ambiguity.

### Commit hex

`commit_hex := BLAKE2b-256(preimage) as lowercase hex`

Off-chain (Python SDK):

```python
from sdk.challenge_arbiter import build_commit_bundle, VERDICT_SENDER

bundle = build_commit_bundle(
    self_package_hash=known_pkg_hash,
    dispute_id="d-2026-07-24-042",
    verdict=VERDICT_SENDER,
    arbiter_pk_hex="02" + my_ed25519_pubkey_bytes.hex(),
    private_key_pem=my_ed25519_private_pem,
)
# Send bundle.commit_hex on-chain now.
# Keep bundle.nonce_hex + bundle.signature_hex secret until reveal.
```

On reveal, the contract:

1. Reads `stored_hex` from the commits dictionary.
2. Compares against `recomputed_commit_hex` supplied by the caller. Any
   mismatch reverts with `ERR_COMMIT_MISMATCH (13)`.
3. Reconstructs the canonical preimage and verifies the caller-supplied
   Ed25519 signature against the registered pubkey. A wrong signature
   reverts with `ERR_INVALID_SIGNATURE (2)`.

Defence-in-depth logic: the recomputed-hash comparison alone would be
brute-forceable in principle if an attacker knew every field except the
nonce. The added signature check makes forgery equivalent to forging an
Ed25519 signature — a hard problem. In practice, an attacker who observes
`commit_hex` learns nothing about the verdict until the arbiter chooses to
reveal.

## Threat model

### Adversary A — front-running / grief

- **Goal:** learn an arbiter's verdict during commit phase to bribe them or
  publish a counter-transaction.
- **Defense:** the on-chain commit is a hash over a 32-byte private nonce.
  The nonce is generated with `secrets.token_hex(32)` — the same primitive
  Python uses for CSRF tokens. Brute-forcing a 256-bit nonce is infeasible.

### Adversary B — targeted arbiter

- **Goal:** predict which arbiter will handle a given dispute (as with the
  old `dispute() → resolve()` path where 3-of-5 signers were fixed and
  visible), pre-bribe or DDoS them.
- **Defense:** the reveal binds the verdict to `(arbiter_pk, nonce)` — an
  attacker who compromises a specific arbiter still cannot see the verdict
  until that arbiter reveals it. Combined with the VRF-arbiter selection
  from step 8 (also on `main`), the identity of "which arbiter will be
  used for THIS dispute" is unpredictable until after commit; the verdict
  is unpredictable until after reveal.

### Adversary C — non-revealing arbiter

- **Goal:** stall a dispute by committing but never revealing, holding
  the escrow in `STATUS_REVEAL_PHASE`.
- **Defense:** anyone can call `slash_non_revealer` after
  `reveal_deadline` to slash the missing arbiter's `arbiter_bond` into the
  challenge pool, THEN call `finalize`. If the total revealers fall below
  `threshold`, the challenge finalizes as `FAILED_QUORUM`, which the
  escrow contract interprets as "challenge did not succeed" (status-quo
  wins). The stalling arbiter loses their bond either way; the escrow
  cannot be indefinitely frozen.

### Adversary D — cross-dispute signature replay

- **Goal:** re-use one legitimate signature for a different dispute or a
  different deployment.
- **Defense:** the preimage embeds both `dispute_id` and
  `self_package_hash`. Injectivity is proven by proptest
  `prop_preimage_injective_in_dispute_id` and
  `prop_preimage_injective_in_package_hash`.

### Adversary E — inconsistent finalize

- **Goal:** the caller of `finalize` supplies bogus sender/receiver reveal
  counts to steer the outcome.
- **Defense:** `finalize` enforces `sender + receiver == stored reveal_count`
  and reverts with `ERR_INVALID_STATE (3)` otherwise. Verified by proptest
  `prop_finalize_rejects_inconsistent`.

## Operational notes

- **Bond amounts** are set in `set_config()` and must be strictly positive.
  Once `lock_config()` is called, they cannot be changed — an upgrade
  requires deploying a new contract.
- **Commit window** vs **reveal window**: recommended defaults are
  `commit_window_ms = 24h`, `reveal_window_ms = 24h`, `threshold = 3`.
  A shorter commit window increases finality speed but can under-recruit
  arbiters on weekends; a longer reveal window increases resistance to
  transient network partitions.
- **Registered pubkeys**: use `set_arbiter_registry` to bootstrap the
  eligible set. This is the same convention the existing `escrow`
  contract uses for its 3-of-5 multisig — the challenge-arbiter registry
  can share the same pubkey set for continuity.
- **Cross-contract wiring**: not enabled in this PR. To integrate with
  `escrow::resolve()`, the resolver would `call_contract` into
  `challenge_arbiter_package::finalize` and interpret the returned
  status. That work is scoped separately to keep this PR reviewable.

## Test coverage

- `contracts/tests/src/challenge_arbiter_property_tests.rs` — 26 tests
  (14 proptest + 12 unit). Covers preimage injectivity in all 5 fields,
  state-machine safety, threshold semantics, slash eligibility, verdict
  enum, and timing monotonicity.
- `tests/test_challenge_arbiter_sdk.py` — 14 tests. Byte-for-byte parity
  with the on-chain preimage layout, commit-hex determinism, Ed25519
  signature roundtrip.

## Related

- `contracts/escrow/src/main.rs::dispute()`, `::resolve()` — the existing
  3-of-5 multisig path this layer will eventually replace or supplement.
- `contracts/vrf-arbiter/` — VRF-based arbiter selection introduced in
  step 8; complementary to commit-reveal (VRF hides *who*, commit-reveal
  hides *what*).
- `contracts/two-key-account/` — same `u64_to_decimal` helper + same
  domain-separated signature pattern (`ae402:{scheme}:v1:...`).
