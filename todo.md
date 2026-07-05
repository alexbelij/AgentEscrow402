# AE402 — active task list (2026-07-05)

## STATUS NOTE
Console UX overhaul (sidebar rework, wallet toggle, overview links/graph, escrow modal,
contracts/agents layout, arbitration+demo result placement, sandbox API docs, a11y labels,
WalletStatus demo-mode banner) is **already merged into main** (commits e792c16, e10d7c8,
a95406f, 6f00ad1 — verified via `git branch --contains`/`git log`). The old 32-item checklist
below is STALE and should not be treated as still-open backlog. Keeping it only for reference;
do a fresh targeted audit later if Alexey flags a specific remaining UX complaint.

## CURRENT PRIORITY — from master_task_list.md (real competitor research, other thread)
Approved by Alexey 2026-07-05 to close these AE402-specific items instead of unvalidated
internal ROADMAP.md Phase 3/4 items:

- [ ] S4 — Legitimize planned features with official Casper reference patterns:
      - `two-party-multi-sig` pattern → escrow release/resolve flow
      - `casper-private-auction` pattern → commit-reveal (feeds into B1)
      Goal: reduce bug risk by reusing audited/official patterns instead of inventing from scratch.
- [ ] S5 — CEP-2612 Permit Extension: gasless approve+deposit in one transaction (real UX win,
      official standard, ~half day estimated).
- [ ] B1 — MultiAssetEscrow CEP-18/78 + commit-reveal (uses S4 reference). Real feature, bigger.
      - [x] On-chain HTLC hash-lock (commit_swap/reveal_swap entry points) — DONE, see below.
      - [ ] Real CEP-18/CEP-78 token integration (replace fully-simulated Cep18Adapter/
            Cep78Adapter/CsprAdapter in server/multi_asset.py with real on-chain calls against
            a deployed casper-ecosystem/cep18 test token). Backend /atomic-swap/commit and
            /atomic-swap/reveal still call the simulated in-memory flow, not the new on-chain
            entry points yet — wire them up next.
            - BLOCKER found 2026-07-05: prebuilt official `cep18.wasm` from GitHub release
              v1.2.0 (nightly-2025-02-04v1.2.0, built ~Apr 2024) install/upgrade args parse
              fine (verified correct bytesrepr encoding via RPC echo of the deploy: name/symbol/
              decimals/total_supply/enable_mint_burn all round-trip correctly), payment fine
              (500 CSPR, ruled out "out of gas"), but wasm execution fails with
              `ApiError::EarlyEndOfStream [17]` — a low-level VM bytesrepr error, not a
              Cep18Error application error. Root cause suspected: this prebuilt wasm predates
              some testnet protocol/host-function change (same class of issue we already hit
              upgrading our own escrow contract this session — Casper 2.0 vs older SDK
              assumptions). NEXT STEP: build cep18 from source using its pinned
              `nightly-2025-02-04` toolchain + `build-std` + `wasm-strip` (Makefile at
              /work/temp/cep18_ref, wasm cloned there) instead of the prebuilt release, then
              retry install. Deployer has plenty of CSPR for repeated attempts.
            - Scripts added: server/casper_tx/deploy_cep18_token.mjs (install/upgrade CEP-18
              token contract, correct args verified — safe to reuse once wasm rebuilt).
            - **RESOLVED 2026-07-05**: blocker confirmed to be the stale prebuilt wasm, not our
              args. Installed rustup + `nightly-2025-02-04` (cep18's pinned toolchain) +
              wasm32 target + rust-src, downloaded a static `wasm-strip` binary (no root/apt in
              sandbox, used prebuilt WebAssembly/wabt 1.0.41 release instead of `apt install
              wabt`), built `cep18.wasm` from source with `-Z build-std=std,panic_abort` per the
              project's own Makefile, then `wasm-strip`'d it. **Installed cleanly on testnet on
              the first try** (error_message: null) — contract hash
              `c93d7d59e73b213e4351f4e11f2a5217a6aa872bb18d378b3f5f230f29883e7d`, token "AE402
              Test USD" (AETUSD), 6 decimals, 1,000,000 total supply, enable_mint_burn=1 (all
              held by deployer initially).
            - **Real token transfer verified on-chain**: called `transfer` (deployer → provider
              test account, 50 AETUSD = 50000000 base units) — confirmed success
              (error_message: null), then independently queried the CEP-18 `balances`
              dictionary via `state_get_dictionary_item` and confirmed the provider's on-chain
              balance is exactly 50000000. Full real ERC20-equivalent flow now proven working,
              not just install.
            - New script: server/casper_tx/cep18_transfer.mjs (calls `transfer` entry point via
              ContractCallBuilder).
            - REMAINING for B1: wire `server/multi_asset.py`'s `Cep18Adapter`
              (transfer_to_escrow/simulated methods) to call this real deployed token contract
              instead of logging "Simulating...", and update `AdvancedEscrow.tsx` to drop the
              "simulated" caveat once done. CEP-78 (NFT) adapter is a separate, still-untouched
              piece of B1.
      - [ ] Update frontend AdvancedEscrow.tsx to remove "simulated" caveat once backend wired.

## S5 note (folded into B1)
CEP-2612 permit is a CEP-18-token feature (gasless approve+deposit); native CSPR escrow already
requires sender-signed session-wasm so permit doesn't apply there. Deliver S5 together with B1's
CEP-18 integration as a "CEP-2612-inspired" (not byte-exact standard) permit flow, not standalone.

## ALREADY DONE (do not duplicate)
- [x] On-chain HTLC atomic-swap hash-lock (SHA-256 commit/reveal), contracts/escrow/src/main.rs:
      - New entry points `commit_swap(service_hash, commit_hash)` (sender-only, once, PENDING-only)
        and `reveal_swap(service_hash, preimage)` (callable by anyone — HTLC pattern, secret =
        authorization; verifies sha256(preimage)==commit_hash on-chain, then releases funds via
        shared `do_release_funds()` also used by release()).
      - Used audited `sha2` no_std crate (Casper contracts expose no generic on-chain hash host
        function).
      - 22/22 Rust tests pass (18 original + 4 new HTLC unit tests), 322/322 Python tests pass.
      - Deployed as in-place contract upgrade on testnet (state preserved — same
        contract_package_hash d3ca33d1..., new entity hash f3bfbd7c...). Deploy hash
        2211685a43a04a7ccff760ab345bec4c3315f8cb5b3f93a6778c67da29c7aaa2 (700 CSPR payment
        needed for this large wasm upgrade; smaller payments hit "Out of gas").
      - **Live e2e verified on-chain 2026-07-05**: created real escrow (requester→provider,
        3 CSPR) → commit_swap by sender → reveal_swap by a *different* account (provider,
        proving the "anyone can reveal" HTLC semantic) with correct preimage → transfer of
        2.94 CSPR confirmed in the reveal transaction's on-chain effects. Full lifecycle works,
        not just unit tests.
      - Gotcha: these are Casper 2.0 Transactions, not legacy Deploys — poll via
        `info_get_transaction` with `{"transaction_hash":{"Version1":"<hash>"}}`, not
        `info_get_deploy` (returns "No such deploy" for these).
      - New script: server/casper_tx/swap_lifecycle.mjs (submits commit_swap/reveal_swap via
        ContractCallBuilder, mirrors existing lifecycle.mjs).
- [x] A1 no-withdraw-path — verified: release()/refund() only ever pay the fixed sender/receiver
      recorded at escrow creation; resolve() requires 3-of-5 Ed25519 arbiter multisig. No entrypoint
      allows unilateral/arbitrary withdrawal.
- [x] B8 Agent Identity Registry — wired, not stub (identity_registry.py / identity_registry_api.py).
- [x] resolve() crypto-hardening (real Ed25519 arbiter multisig, replay-proof) — commit 1fedc77.
- [x] Console UX overhaul — merged into main (see STATUS NOTE above).

## EXPLICITLY OUT OF SCOPE FOR THIS THREAD
- A2 (volume of real testnet transactions / Agent Factory + Runner) — handled by the separate
  analytics/research thread. Do not duplicate per Alexey's "не мешай разные ветки" instruction.
- Phase 4 (mainnet, external audit, bridge, formal verification, compliance) — not required by
  hackathon rules (testnet prototype only) and not supported by competitor research as valuable
  pre-hackathon. Reasonable to defer post-hackathon.
- Internal ROADMAP.md Phase 3 items not present in master_task_list.md (Threshold MPC/Shamir,
  flash-loan protection, gaming-reward escrow) — not validated by real competitor research;
  do not implement blindly ("features for feature's sake").
