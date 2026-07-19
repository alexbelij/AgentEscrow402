# Build audit — is the fix actually live?

**Status:** shipped in `feat/ae-build-audit-artifact`. Closes the P0 Gate 1
gap "Build audit — confirm that fixed insurance WASM is actually in the
built artifact, not only in .rs source" from `AE402_FINAL_TASKS_V2.md`.

## The question this answers

A common failure mode in fast-moving contract work: the fix lands in the
`.rs` source, gets committed, gets tested locally against pure-Rust
mirrors of the logic — and never makes it to the live contract because a
redeploy was skipped, or a redeploy went to a fresh contract_hash but
the API config was never repointed. From the outside (source review,
green tests) everything looks fine. From an attacker's perspective the
old, unfixed contract is still on chain and the pool can still be
drained.

`scripts/audit_contract_artifact.py` closes that gap by asking Casper
global state directly: *what does the network actually serve today under
this contract_hash, and does it carry the named-keys the fix requires?*

## What the script does

Per registered target (currently: `insurance_pool`, `escrow_manager_v9`,
`vrf_arbiter`, `agent_identity_registry`, `multi_asset_escrow`):

1. **Fetches the live contract via RPC** using the `contract_hash` from
   `deploy-out/onchain.json`:
   `query_global_state({ key: "hash-<contract_hash>" })`. Reads the
   contract's named-keys, entry-points, and `contract_wasm_hash`.
2. **Checks required named-keys.** Each crate has a whitelist of
   named-keys that a properly-hardened contract MUST expose. For
   `insurance-pool` this includes `claimed_escrow_ids` — the escrow
   tombstone dict added by the 2026-07-19 claim-replay fix. If any
   required key is missing on chain, the fix isn't live under that
   contract_hash and the audit fails loudly.
3. **Best-effort deploy-bytes cross-check.** If `deploy_hash` is set and
   points to a ModuleBytes install deploy, the script also fetches
   `session.ModuleBytes.module_bytes` via `info_get_deploy`, builds the
   crate locally, compares WASM size and the domain strings baked into
   the DATA section. This is only corroborating: an old `deploy_hash`
   for a superseded install can lie (the contract_hash may have been
   redeployed since), and the script says so explicitly. Contract state
   is authoritative.

## Verified findings against the current chain

Run on 2026-07-20 against `casper-test`:

```
══ Auditing insurance_pool
  contract_hash = ead90738d19ad7fcc88c9e079e12d8cf6d4fd09ddd3daafe565bf4fe4b95fff4
  deploy_hash   = 4ea886beee6c1d302a4282c11390856da8ae89e6a05775e57bb6c5e7dae0b16f
✅ on-chain contract has 7 entry points, 8 named-keys
    contract_wasm_hash = contract-wasm-e8d23a22…
✅ all 7 required named-keys present on chain     ← FIX IS LIVE
✅ deploy-bytes vs local: 315,387 vs 315,676 (+289 bytes, +0.09%)
⚠️  deploy_hash bytes are missing markers ['claimed_escrow_ids'] — consistent with a superseded install.
```

Two things this run made explicit:

1. **The claim-replay fix IS live** on the current contract_hash
   `ead90738…`. Its named-keys include `claimed_escrow_ids`. An attacker
   with a valid arbiter quorum can no longer replay a claim against a
   previously-claimed escrow — the on-chain tombstone rejects it.
2. **The `deploy_hash` in `deploy-out/onchain.json` was stale.** It
   pointed to the ORIGINAL 2026-07-06 install of this package
   (`4ea886be…`) whose WASM did NOT yet have `claimed_escrow_ids`. The
   2026-07-19 hardened redeploy created a new contract_hash under the
   same package but its deploy_hash was never written back to
   onchain.json. Fixed in this same PR: added `deploy_hash_note` and an
   explicit warning that `contract_hash` is the source of truth.

The `⚠️` about deploy-bytes markers being missing is EXACTLY the signal
we wanted the audit to be able to surface — the script now
distinguishes "current contract missing the fix" (hard fail) from
"listed deploy_hash predates the fix but current contract has it" (warn
+ suggest fixing onchain.json). Both are actionable, neither is a false
alarm.

## Running

```bash
export PATH="$HOME/.cargo/bin:$PATH"
python3 scripts/audit_contract_artifact.py insurance_pool     # default: one target
python3 scripts/audit_contract_artifact.py --all              # all registered targets
python3 scripts/audit_contract_artifact.py insurance_pool --strict   # exit 1 on drift
```

Requirements: python3 (stdlib only), cargo with the
`wasm32-unknown-unknown` target and the toolchain pinned in
`contracts/rust-toolchain.toml`.

## Wiring into the redeploy playbook

Every redeploy should end with `python3 scripts/audit_contract_artifact.py
<key> --strict`. The three things it forces you to notice:

- Did the redeploy actually go to a new contract_hash?
- Does that new contract_hash carry the named-keys your fix requires?
- Is the deploy_hash in `deploy-out/onchain.json` the one that installed
  the current live contract_hash? (If not, update it.)

## Extending

Add a new target: register `(crate_dir, wasm_filename)` in `TARGETS`,
then whitelist the required named-keys in `REQUIRED_NAMED_KEYS`. Both
are dicts in the script header, no other code changes required.
