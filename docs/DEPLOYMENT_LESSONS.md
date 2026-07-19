# AE402 Casper Testnet Deployment — Lessons Learned

**Compiled**: 2026-07-19 after the insurance-pool redeploy at `ead90738…95fff4`.

**Audience**: whoever runs the next contract deploy against `casper-test` — either from `alexbelij` or a fresh wallet.

**Source**: real-world diagnosis of failed and successful deploys on 2026-07-18, cross-checked against the `casper-contract` 5.1.1 crate source (not the public docs, which lag).

---

## TL;DR — before you deploy

1. **Toolchain must be `nightly-2025-01-01`** — see `contracts/rust-toolchain.toml`. Bumping this without a live-testnet verification will burn CSPR.
2. **Every `storage::new_contract(...)` deploy needs the `install_or_upgrade` flag on the transaction.** Without it, the chain returns `NotAllowedToAddContractVersion [48]`. This applies **even to fresh packages**, contrary to older internal notes.
3. **`storage::new_dictionary(name)` fails with `InvalidArgument [3]` if the deployer account already holds a named key with that same `name`.** Detect this by calling `state_get_account_info` before submission. If any planned dictionary name collides, deploy from a clean wallet.
4. **Never blind-retry a full deploy.** Every failed installer still costs CSPR. Isolate the failure in a minimal harness (10–20 CSPR) before spending 100+ CSPR on another full attempt.

---

## Lesson 1 — Rust nightly compatibility

### What broke

- `nightly-2025-03-01` produces WASM that Casper testnet preprocessing rejects outright with `Bulk memory operations are not supported`.
- The failure happens **before** the contract executes, so no useful chain-side error is emitted. Testnet payment is still consumed for the deploy attempt.

### Why

Recent rustc/LLVM nightlies emit bulk-memory instructions (`memory.copy`, `memory.fill`, etc.) that Casper's WASM preprocessor doesn't accept. This has nothing to do with the Casper SDK version — it's the codegen path.

### Fix

Pin to `nightly-2025-01-01`. This has been confirmed deploy-compatible by the successful insurance-pool redeploy at `ead90738…95fff4`.

### How to safely bump

1. Change `contracts/rust-toolchain.toml`.
2. Run the full contract build.
3. Deploy the smallest contract in the repo to `casper-test` from a **disposable** wallet with ~200 CSPR balance.
4. Query the deploy result until it succeeds or fails.
5. **Only then** update the pin for the rest of the team.

Do **not** bump based on rustc release notes alone.

---

## Lesson 2 — `install_or_upgrade` is required for every fresh contract

### What broke

The insurance-pool redeploy from `alexbelij` failed with `NotAllowedToAddContractVersion [48]` on the very first `storage::new_contract(...)` call — even though the package was fresh.

### The wrong hypothesis

An earlier internal note said "`install_or_upgrade` rejects WASM > 64KB". That was **verified false** during this redeploy — the SDK accepts 312KB with the flag set. The 64KB limit belongs to a different code path (session-code payload size), not to the install-or-upgrade flag.

### Why `install_or_upgrade` is actually required

Reading the `casper-contract` 5.1.1 crate source directly (not the docs):

- `storage::new_contract(...)` unconditionally attempts to associate the new contract with the caller's account permissions.
- Without `install_or_upgrade` set on the transaction envelope, the chain treats the call as a **version upgrade** of an existing (nonexistent) contract → `NotAllowedToAddContractVersion`.
- The flag tells the chain: "This may be a fresh install OR an upgrade — handle both."

### Fix

Set the flag when constructing the transaction:

```rust
// pseudo — actual SDK call depends on which Casper SDK you use
transaction_builder
    .with_install_or_upgrade(true)
    .with_session_wasm(wasm_bytes)
    .build()?;
```

### Verification

Build the WASM, check its size (should be well over 64KB for the insurance-pool at ~312KB), and deploy with the flag set. Preprocessing accepts it. `install_or_upgrade` = required, WASM size = not the problem.

---

## Lesson 3 — `storage::new_dictionary` and named-key collisions

### What broke

An earlier insurance-pool redeploy attempt from `alexbelij` failed with `ApiError::InvalidArgument [3]` at the `storage::new_dictionary("stakes")` call — but the same wallet had successfully deployed the *previous* insurance-pool version months earlier.

The error was silent about the cause; from the outside it looked like a corrupt argument.

### Why (from `casper-contract` crate source)

`storage::new_dictionary(name)` requires that the deployer's account **does not already own a named key with that exact name**. It doesn't merge, it doesn't reuse — it rejects.

The `alexbelij` account, from the earlier deploy, still held named keys `stakes`, `slashed_proofs`, `claimed_escrow_ids`, etc. So any re-`new_dictionary` call from that account was doomed. The named keys aren't automatically cleaned up between contract versions.

### How to detect this before wasting CSPR

Before submitting a deploy that calls `storage::new_dictionary(name)`:

```bash
# Query the account's current named keys
casper-client get-account-info \
  --node-address https://node.testnet.casper.network:7777 \
  --public-key <deployer-pk>

# Check the "named_keys" array for collisions with your planned dictionary names
```

If any collision exists, **switch to a clean wallet** for this deploy. That's what happened for the CP stake-slashing redeploy on 2026-07-18: `anna-stolbovskaja` had the collision → deploy shifted to `defi_mock_owner` (verified clean via `state_get_account_info` first) → success at `1ad1b3d9…983d52`.

### Applying this to AE402 next time

- `alexbelij` still owns AE402 named keys. Any future insurance-pool or escrow redeploy from this wallet will hit the same wall for any dictionary that already exists.
- Options:
  1. Deploy from a fresh wallet (preferred — cleanest, cheapest to verify).
  2. Rename the dictionaries in the new contract version (breaks existing state readers — not recommended).
  3. Add cleanup logic in the contract itself before `new_dictionary` — non-trivial and error-prone.

Option 1 is what the CP redeploy proved works.

---

## Lesson 4 — Economic discipline

### What broke

The first insurance-pool redeploy attempt cost ~40 CSPR before failing with error 48. Retrying blindly would have cost the same again for the same failure.

### The rule

**Every failed installer costs real CSPR. Diagnose in isolation before retrying.**

For AE402 in particular, an **installer-isolation harness** looks like:

1. Take the failing constructor call sequence.
2. Wrap it in a minimal contract that does *only* that sequence and stops.
3. Deploy the minimal harness (10–20 CSPR, not 100+ for the full contract).
4. Read the exact error on the harness alone.
5. Fix root cause.
6. Only then re-run the full deploy.

This is what caught Lessons 2 and 3 above at a total of ~30 CSPR instead of 200+.

### For the next agent

If you see a testnet failure and your instinct is "let me just try again with slightly different args" — **stop**. Isolate first. The chain will not tell you what's wrong beyond a numeric error code, and the numeric codes are ambiguous. The crate source is the ground truth.

---

## Open items (not yet closed, need production access)

These require credentials no automated agent currently holds. Track them here so they don't get lost:

- [ ] **Prod env vars on Render** — `INSURANCE_CONTRACT_HASH` and `INSURANCE_PACKAGE_HASH` still point to the old `e128780f…` addresses. Must be updated to `ead90738…95fff4` / `78258f66…67f97`.
- [ ] **Arbiter set** — the new insurance-pool contract starts with an empty arbiter_list (threshold = 3). A `set_arbiters` transaction with the real project arbiter public keys is required before any live claim can be resolved.
- [ ] **Live smoke test** — one on-chain `claim(escrow_id)` on the new insurance-pool + one deliberate replay attempt (must be rejected). This is the final acceptance check that the redeploy actually delivers the invariant it claimed.

---

## Change log

- **2026-07-19** — File created after insurance-pool redeploy at `ead90738…95fff4`. Root causes for previous failed attempts documented from `casper-contract` 5.1.1 crate source.
