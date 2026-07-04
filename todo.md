# Console UX overhaul — todo (from Alexey's 2026-07-04 message)

## Global (all console pages)
- [ ] explanation block must come AFTER the page title, not before, and must not duplicate the text under the title
- [ ] title row + text below it should span full width on one line (not ~50% as now)
- [ ] check font sizes, contrast ratio, keyboard navigation across console (accessibility pass) — item 12

## Navigation / layout
- [ ] Nav currently scrolls both vertically and horizontally — bug. Replace with classic dashboard left sidebar:
      collapsible to icon-only rail (icon + tooltip on hover), full mode = icon + label, no tooltip.
      Rethink page grouping — maybe merge some pages / add nesting (sub-menus).
- [ ] /console currently mixes real console sections, demo tools, and dev docs — separate/decompose into distinct
      groups/sections (we already discussed this decomposition).
- [ ] Content area is constrained/narrow while nav takes fixed width oddly — make everything use full width (item under nav point 1).
- [ ] Under sidebar, full-width "Hosted demo signer" block (point 1, 2nd list).

## Overview page (/console/overview)
- [ ] Total Volume — reduce font size
- [ ] Contract target — should link to explorer
- [ ] Other stats — link to explorer or relevant console section where applicable
- [ ] Missing useful metric widgets — overview should show full network/project state: nice animated
      charts/graphs, realtime logs/activity feed
- [ ] Unify block font sizes/styles (currently inconsistent & too large)

## Escrows (/console/escrows)
- [ ] confirm real data (not fake/demo passed as real)
- [ ] Rework modal — hash column wraps to 3 lines due to narrow width

## Agents (/console/agents)
- [ ] "Register agent" button should be to the right, after "Delegate..."
- [ ] Can we add real data alongside demo data?

## Contracts (/console/contracts)
- [ ] Reposition "Fresh escrow" (per Alexey — check exact placement issue)
- [ ] "Receiver" column — widen at the expense of "Amount (CSPR)" so full address fits

## Advanced Escrow (/console/advanced)
- [ ] Results currently render below the form — move to the right side; question excess empty space

## Arbitration (/console/arbitration)
- [ ] Results show both below and to the side — all results should render on the right only

## Agent Demo (/console/agent-demo)
- [ ] "Result" column — double width
- [ ] Steps: render in a single left column list (not 2-column like /sandbox)
- [ ] Completed step: green + animate move to end of list
- [ ] Next step: purple outline (design accent color), not red
- [ ] Reset: steps return to original style/position; "Current request & result" panel clears output

## Sandbox (/console/sandbox)
- [ ] Missing variable/type descriptions like proper API docs

## Demo signer / wallet connect UI
- [ ] "Demo signer" connect button doesn't switch to active/connected style — add style
- [ ] On connect: button text becomes demo wallet address (like real wallet-connect buttons do)
- [ ] Remove demo wallet address shown to the right of "Demo · not your key" badge; remove the badge
      entirely — button style itself communicates demo mode
- [ ] "Disconnect" + "Hosted demo signer" (with icon before label) shown only while demo wallet connected
- [ ] Add (i) info icon to the right of the label; move long explanatory text into a tooltip shown on
      click/tap; tooltip dismisses on click of (i) again or click-outside/tap-outside

## Process
- Work in blocks, report progress to Alexey per block (heavy scope — 1:1 DM, no other channels).
- Verify against CI-parity checks (frontend: tsc --noEmit + npm run build) before each report.

## CRITICAL FINDING (this session) — resolve() dispute path non-functional
- Deployed escrow contract's `resolve()` (3-of-5 arbiter multisig) can NEVER succeed: on-chain `arbiter_list` is empty (verified via query_global_state), and there is no post-install entry point to add arbiters.
- Backend/SDK never call `resolve()` at all — `ResolveRequest` model exists in server/models.py but is unused (no endpoint, no casper_client method, no node script wiring).
- Demo script (examples/escrow_agent.py) "bad" scenario calls /release after dispute -> fails (contract + local sandbox both require status==pending for release/refund).
- Fix requires: contract upgrade (add installer-only `set_arbiters`/`add_arbiter` entry point via package-hash upgrade deploy) + backend `/resolve` endpoint + casper_client.resolve() + node script + 5 real/test arbiter accounts.
- Rust toolchain now installed in sandbox (rustup, wasm32-unknown-unknown target) — `cargo build --release --target wasm32-unknown-unknown -p escrow` verified working.
- Awaiting Alexey's go-ahead on contract upgrade + arbiter account list before implementing.

## resolve()/arbiter-list fix — STATUS UPDATE (this session)
- [x] Added `set_arbiters(arbiters: Vec<String>)` installer-only entry point to `contracts/escrow/src/main.rs`.
- [x] Modified `call()` to detect existing `escrow_package_hash` and use `storage::add_contract_version` (upgrade path) instead of `storage::new_contract` (preserves existing escrows/reputation).
- [x] Compiled wasm, verified `set_arbiters` string present in binary.
- [x] Deployed contract upgrade on-chain via `deploy_contract_legacy.mjs` (400 CSPR payment; 150 CSPR was insufficient — "Out of gas"). Deploy hash `89fb3c3d86ac3ae67f2ff2b60cae83a46d05b68edd69faba60400af17eee83ce`, block 8396150, error_message: null.
  - **IMPORTANT**: upgrade created a NEW contract entity hash `3a477e01eca177173a30e13b7b029cfc575488cd73b471b65505c576e1abb60e`, distinct from OLD `5d5c7551f9289b4679f798f3a90d7cfce7bfb10d0dd729186b16b48b5a7a1467` used everywhere (frontend Contracts.tsx, backend .env CONTRACT_HASH). The package hash (`hash-d3ca33d192dda5ece798db91811ec1259d2197ca0e8d3ea4de043b977d3c8eeb`) is stable across versions — should be the long-term reference, not the entity hash.
  - **TODO**: update backend `.env`/`server/config.py` `ESCROW_CONTRACT_HASH` and frontend `Contracts.tsx` Core Escrow hash to the NEW entity hash `3a477e01eca177173a30e13b7b029cfc575488cd73b471b65505c576e1abb60e` (or migrate config to reference the package hash + latest-version lookup instead of a fixed entity hash, to avoid this break on every future upgrade).
- [x] Generated 5 test arbiter Ed25519 keypairs (`server/casper_tx/gen_arbiters.mjs`); pems at `/work/temp/keys/arbiters/arbiter_{1-5}_secret_key.pem` (became permission-denied mid-session due to sandbox user-context switch; hashes/pubkeys recorded in Slack report and in this repo's chat history).
- [x] Registered the 5 arbiters on-chain via new `server/casper_tx/set_arbiters.mjs` script, called against the NEW contract hash. Deploy hash `a73cc0d0a35f43295674355a5bdb9f509b076ff3abf8c5d4bf5a6cdfcfef4a0d`, block 8396191, error_message: null.
- [x] **Verified via `query_global_state`** on `hash-3a477e01eca177173a30e13b7b029cfc575488cd73b471b65505c576e1abb60e` path `["arbiter_list"]` — returns all 5 registered arbiter account-hashes. Multisig arbiter list is now real and populated.
- [ ] **STILL TODO (next)**: 
  1. Wire `/resolve` FastAPI endpoint in `server/app.py` using existing (currently unused) `ResolveRequest` model.
  2. Add `resolve()` method to `server/casper_client.py` (build+sign+submit a `resolve` deploy against the NEW contract hash with `service_hash`, `in_favor_of`, `arbiter_accounts` args).
  3. Add resolve support to sandbox path (`server/sandbox.py`) so `--scenario bad` in `examples/escrow_agent.py` can complete end-to-end (currently fails after dispute because `release`/`refund` still require `status pending`, and `resolve` isn't called anywhere).
  4. Update `.env`/`config.py`/`Contracts.tsx` to the new contract hash (see note above); consider making all 4 contract hashes backend-configurable per other agent's suggestion.
  5. Re-run `examples/escrow_agent.py --scenario bad` end-to-end against production backend to prove full dispute→resolve→release lifecycle works on real testnet.
  6. Fix stale hash in `SUBMISSION.md`.
