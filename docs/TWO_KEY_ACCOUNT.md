# Two-Key Smart Account (cold / hot)

An account-abstraction (AA) style Casper contract that separates two
Ed25519 key roles for AI-agent operators. The **cold key** is the root
authority (rotates keys, freezes, sets spend cap, renounces). The **hot
key** is the day-to-day agent-signing key, capped to a per-call
`hot_spend_cap_motes` and revocable in one cold-key call.

- Contract:       `contracts/two-key-account/src/main.rs`
- Python SDK:     `sdk/two_key_account.py`
- Property tests: `contracts/tests/src/two_key_account_property_tests.rs`
- SDK tests:      `tests/test_two_key_account_sdk.py`

## Why

AE402 agents sign payments autonomously. A single-key agent has no
containment — if the signer key leaks, everything the agent controls is
drained. This contract gives operators two dials:

1. **Blast-radius bound.** The hot key can only authorise calls up to
   `hot_spend_cap`. Everything above needs the cold key.
2. **Fast revocation.** The cold key can `freeze()`, `rotate_hot()`, or
   `renounce()` in a single call. A stolen hot key becomes useless the
   moment the cold key signs a rotation.

The cold key is meant to live somewhere the agent never touches
(hardware wallet, cold laptop, HSM). Compromising it takes the whole
account; compromising only the hot key at worst spends up to the cap
before the cold key rotates.

## Entrypoints

| Entrypoint       | Role  | Purpose                                            |
|------------------|-------|----------------------------------------------------|
| `exec`           | Hot   | Authorise a payment ≤ `hot_spend_cap`              |
| `rotate_hot`     | Cold  | Replace the hot key; resets hot nonce to 0         |
| `rotate_cold`    | Cold  | Replace the cold key (keeps its nonce monotonic)   |
| `freeze`         | Cold  | Halt `exec()` — hot key temporarily disabled       |
| `unfreeze`       | Cold  | Resume `exec()`                                    |
| `set_spend_cap`  | Cold  | Change `hot_spend_cap_motes`                       |
| `renounce`       | Cold  | Terminal state — no further ops of any kind        |
| `get_state`      | View  | Read current `(cold, hot, nonces, flags, cap)`     |

## Anti-replay design

Every signed call binds four things into the message the contract
verifies:

```
ae402:two-key:v1:{action}:{contract_id}:{nonce}:{payload_hash}
```

- **Action**  — a signature for `freeze` cannot execute `renounce`.
- **Contract ID** — a signature valid on deployment A won't verify on B,
  even with the same keys and nonces. The `contract_id` is bound as a
  named arg at call time; the contract itself does not read its own
  address, but *any* substituted `contract_id` would break signature
  verification because it wasn't what the off-chain signer signed.
- **Nonce**  — monotonically consumed per role (cold and hot each have
  their own). Any mismatch reverts with `ERR_NONCE_MISMATCH`.
- **Payload hash** — a caller-chosen commitment (sha256 recommended) to
  the concrete action (e.g. the payment destination + amount for
  `exec`). Signing one payload doesn't authorise any other.

The signed-message builder is byte-identical in Rust and Python; the
property-test suite exercises injectivity across arbitrary
`(action, contract_id, nonce, payload_hash)` tuples via `proptest`.

## Threat model

| Threat                                              | Mitigation                                                      |
|-----------------------------------------------------|-----------------------------------------------------------------|
| Hot key stolen                                      | Bounded by `hot_spend_cap`; cold rotates + resets hot nonce.    |
| Cold key stolen                                     | Full compromise. Keep cold offline. Renounce if suspected.      |
| Replay of `exec` signature                          | Nonce (u64, monotonic) + `payload_hash` binding.                |
| Replay of cold sig against a different deployment   | `contract_id` bound into signed message.                        |
| Reusing an old hot signature after rotation         | `rotate_hot` resets hot nonce to 0, invalidating old bytes.     |
| Signature substitution across actions               | Action string is part of the signed message.                    |
| Malicious relayer swaps `contract_id`               | Signature verify fails; tx reverts (`ERR_INVALID_SIGNATURE`).   |
| Post-renounce ops                                   | `ensure_not_renounced()` on every entrypoint.                   |

## Operational notes

- **Cold-key ceremony.** Generate offline. Sign the initial deploy with
  the cold key on an air-gapped machine. Store the raw ed25519 seed in
  a hardware wallet or paper backup.
- **Nonce discovery.** Query `get_state` before each call and use the
  returned `(cold_nonce, hot_nonce)` when constructing the message.
- **Spend cap sizing.** Set `hot_spend_cap_motes` to the largest single
  action the agent is authorised for. Larger flows must be split into
  multiple sub-cap calls or promoted to a cold-signed batch.
- **Recovery.** Losing the cold key without a backup renders the
  account frozen-forever if the hot key is not stolen, or drained-to-
  cap-then-frozen if it is. Always maintain at least one cold-key
  backup outside the operator's hot infrastructure.

## Deployment

The contract installs via the standard Casper `new_contract` pattern.
Install args:

```
cold_pubkey            : String  (hex Ed25519)
hot_pubkey             : String  (hex Ed25519, distinct from cold)
hot_spend_cap_motes    : U64
```

Result NamedKey (in the installer's account): `two_key_account_contract_hash`.

## Python SDK example

```python
from sdk.two_key_account import AccountState, prepare_call

state = AccountState(
    contract_id="…hex…",
    cold_pubkey_hex="01…",
    hot_pubkey_hex="01…",
    cold_nonce=3,
    hot_nonce=12,
    frozen=False,
    renounced=False,
    hot_spend_cap_motes=1_000_000_000,
)

signed = prepare_call(
    state,
    action="exec",
    payload=b"pay 0xdead 500m",
    sign=my_ed25519_signer,        # bytes -> bytes
)

deploy_args = signed.named_args()  # feed straight into casper deploy builder
```

The SDK is signer-agnostic — plug in `casper-client`, `pycspr`, or a
hardware signer callback. It only guarantees the *message* the signer
sees matches what the contract will verify.

## Related work

Inspired by ERC-4337 session-key patterns, Aztec's account-abstraction
model, and Casper's own multi-key associated-key layout — collapsed into
a two-role primitive that is small enough to audit end-to-end.
