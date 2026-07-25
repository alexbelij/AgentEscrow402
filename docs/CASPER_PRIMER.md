# CASPER_PRIMER.md — Casper for the Ethereum-native judge

*Two pages, aimed at judges from EVM/Solana/Cosmos backgrounds. Just enough Casper to read AE402 without a re-read of the Casper 2.0 docs.*

---

## 1. Consensus & network in three sentences

Casper is a **Proof-of-Stake** L1 (originally CBC-Casper research, in production as the **Highway** family protocol; upgraded to a Zug-style protocol in Casper 2.0). Validators bond CSPR, propose eras, and finalize deploys with BFT-style finality — no PoW, no re-orgs past finality. **Blocks are numbered by height and grouped into eras** (~2h on mainnet, shorter on testnet); a deploy is *executed* immediately upon inclusion but its finality lands within a bounded number of blocks.

**Judge shortcut:** treat it like an EVM L1 with ~30 s inclusion latency, sub-minute strong finality, and no MEV-searcher stack. Explorer: <https://testnet.cspr.live>.

## 2. Execution: WASM, not EVM

Casper smart contracts are **WASM binaries** produced from Rust (typically) via the `casper-contract` SDK. There is no Solidity, no EVM bytecode, no `SELFDESTRUCT`, and *no precompiles in the EVM sense*. The host exposes primitives via a `runtime::` module: `runtime::get_named_arg`, `runtime::put_key`, `runtime::call_contract`, `runtime::verify_signature`, etc. Storage is a URef-keyed KV store, not a 256-bit slot grid.

**What this means for AE402:**
- Contracts are typically 60–200 KB WASM each (governance-dao is 159 KB, range-proofs ~180 KB). Storage is variably-typed (`CLValue`s), not padded to 32-byte words.
- No `SELFDESTRUCT` → contract lifetimes are indefinite; upgrades happen via **package versioning** (see §5).
- No BLS12-381 or bn254 precompile — heavy crypto pays linear WASM gas. AE402's range proofs are designed around this constraint (mod-exp on 3072-bit safe prime, big-int library in-WASM).

## 3. Accounts vs. purses (this is the one that trips EVM devs)

An **Account** on Casper is *not* a balance-holding entity like it is on Ethereum. An Account holds:
- An `AssociatedKey` set (public keys with weight, for multi-sig / key management),
- A collection of **named keys** pointing to URefs / contract-hashes,
- And exactly **one main `Purse`** — the URef that holds CSPR balance for that account.

A **Purse** is a URef with a special "balance" semantic; you can create additional purses and transfer between them. A contract likewise has its own set of URefs / named-keys and can own purses. **CSPR is held in purses, not in accounts directly.** Transferring CSPR is a `transfer` between two purses.

**What this means for AE402:**
- The escrow-manager contract owns a purse per escrow instance; `create()` transfers from the payer's account main purse to the escrow purse; `release()` transfers from the escrow purse to the payee's main purse.
- Custody rules: contract-owned purses can only be transferred *from* by that contract's code. Third-party direct-withdrawal attacks are structurally impossible — the contract's `release()` logic is the sole gatekeeper.

## 4. Keys: `Key::Account`, `Key::Hash`, `Key::AddressableEntity`

Casper 2.0 introduced a new `Key::AddressableEntity` variant that unifies how contracts are addressed. Before 2.0, contracts sat under `Key::Hash`; the migration path (which AE402 shipped on 2026-07-19, commit `a9d7071`) is to use `Key::from_addressable_entity(EntityAddr::SmartContract(addr))` when passing target contract addresses in `runtime::call_contract`. Getting this wrong causes silent `ApiError::EarlyEndOfStream` or `Key mismatch` reverts.

**Practical judge takeaway:** if you're reading an older Casper contract that uses `hash_addr` and it's calling into a 2.0 contract, the call will silently fail. The 2026-07-19 redeploy of AE402's 4 core contracts (escrow-manager, agent-identity-registry, multi-asset-escrow, cep18/aemat) was exactly this fix. Package hashes were preserved (in-place upgrade); only `contract_hash` / `deploy_hash` / version bumped.

## 5. Package hash vs. contract hash (the versioning model)

Every Casper contract lives inside a **package**. The package has a stable hash (`package_hash`). Each deployment of a new WASM binary against that package creates a new **contract version** with a new `contract_hash` — but the `package_hash` is unchanged. Callers can either bind to a fixed `contract_hash` (pins to a version) or bind to `package_hash + version` (auto-follows the latest version).

**What this means when reading `TX_MANIFEST.md`:**
- The **package hash** is the identity you track across upgrades.
- The **contract hash** column is the *currently live* version — updated when we redeploy.
- `deploy_hash` in the manifest is the *original install* deploy of that package (unchanged forever), not the most recent upgrade deploy. Every upgrade produces its own new deploy hash, which lives in the git history of `deploy-out/onchain.json` rather than the summary tables.

## 6. Deploys, gas, and the payment model

A **deploy** on Casper is what an EVM tx is on Ethereum: signed by the account, submitted to a node, executed, finalized. But it carries **two WASM payloads**, not one:
- **Session code** — the actual thing you want to do (call a contract entry-point, transfer, etc.),
- **Payment code** — the WASM that pays for the deploy. Standard deploys use a canonical `standard_payment.wasm` that just says "spend up to N motes from my main purse".

Gas is denominated in **motes** (1 CSPR = 10⁹ motes) and priced roughly linearly by WASM opcode count. There is no priority-fee auction like EIP-1559; deploys are ordered per-account by nonce and included when a validator picks them.

**For AE402:** every entry-point (`create`, `release`, `dispute`, `claim`, etc.) has an empirically-calibrated gas budget documented in `docs/GAS_BUDGETS.md`. The `verify.sh` end-to-end script fails a run if any entry-point exceeds the calibrated ceiling — a regression gate.

## 7. CEP-18 & CEP-78 (Casper's ERC-20 / ERC-721)

**CEP-18** is Casper's fungible-token standard — analogous to ERC-20 but with **purse-native custody**: `transfer` between purses instead of an internal ledger keyed by address. AE402's `multi-asset-escrow` contract handles CEP-18 tokens (`aetusd`, `aemat` on testnet) by allowing the escrow to *own* a token purse per instance and calling `cep18::transfer` under the hood.

**CEP-78** is the enhanced NFT standard (ordinal IDs, transferable / burnable modes, minting-mode config). AE402 uses `aetnft` on testnet for the NFT-collateral escrow flow (buyer stakes an NFT, released to seller on delivery).

**Judge shortcut:** if you know the ERC-20 → ERC-721 story, the CEP-18 / CEP-78 story is functionally the same, with `purses` doing the work that `mappings(address => uint256)` do on Ethereum.

## 8. The AE402-specific glossary

| Term | Meaning in AE402 |
|------|------------------|
| **Escrow** | A single instance of the `escrow-manager` contract state — one purse, one payer, one payee, one lifecycle FSM (`Created` → `Released` \| `Disputed` → `Resolved`) |
| **Arbiter** | An agent registered in `agent-identity-registry` with capability `"arbitration"`, elected by VRF from the eligible set on dispute |
| **Insurance pool** | A contract-owned purse funded by protocol fees; pays out on FSM-verified insurance-eligible failures (arbiter offline, quorum failure with cooldown) |
| **Macaroon** | An Ed25519-signed capability token with caveats verified at redemption in the target contract |
| **VRF election** | The commit-reveal + threshold-attest arbiter selection ceremony; see `docs/CHALLENGE_ARBITER.md` and `docs/evidence/VRF_ONCHAIN_ELECTION.md` |
| **x402** | The HTTP payment protocol AE402 speaks on the API surface — `docs/X402_SPEC.md` |

## 9. Where to look next

- **Verify our claims on-chain:** [`TX_MANIFEST.md`](../TX_MANIFEST.md)
- **Understand what's uniquely-Casper:** [`docs/MOAT.md`](./MOAT.md)
- **Try it locally in one command:** `make judge-demo` (see Tier 1 T1.1)
- **Official Casper 2.0 documentation:** <https://docs.casper.network/>
- **Casper 2.0 SDK for Rust:** <https://docs.rs/casper-contract/>

---

*Written for the judge who's audited an Ethereum protocol before and wants to audit AE402 in the next hour. If you find a section that leaves you guessing — that's a docs bug, file an issue.*
