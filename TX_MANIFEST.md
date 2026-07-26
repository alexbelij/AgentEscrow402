# TX_MANIFEST.md — AE402 Canonical Transaction & Contract Registry

*Source of truth for judges, auditors, and integrators verifying AE402 on Casper testnet.*

- **Network:** `casper-test` (`chain_name: casper-test`, RPC: `https://node.testnet.cspr.cloud/rpc`)
- **Explorer base:** `https://testnet.cspr.live/contract/<hash>` and `https://testnet.cspr.live/deploy/<deploy_hash>`
- **Machine-readable inventory:** [`deploy-out/onchain.json`](./deploy-out/onchain.json)
- **Bulk activity logs:** [`docs/evidence/`](./docs/evidence/)
- **Last regenerated:** 2026-07-25
- **Source ref (contract build):** `deploy-out/onchain.json.source_ref` (commit hash embedded per package)

---

## 1. Live production contracts (mainnet-testnet)

All contracts below are the **currently live** versions serving the hosted console (<https://ae402-console.vercel.app>). Historical redeploys and their rationale are noted in the machine-readable manifest.

| # | Contract | Package (stable) | Contract hash (current) | Ver | Explorer |
|---|----------|------------------|-------------------------|-----|----------|
| 1 | **Core Escrow (escrow-manager v10)** | `d3ca33d192dda5ece798db91811ec1259d2197ca0e8d3ea4de043b977d3c8eeb` | `07527a37742b4da87c9cc38baf752f53b1525b53d0825269d9952a3813739ef1` | 10 | [live](https://testnet.cspr.live/contract/07527a37742b4da87c9cc38baf752f53b1525b53d0825269d9952a3813739ef1) |
| 2 | **Batch Escrow Manager** | `cdc9924e260bd3a62789a610aae0c351760393b335ebb15a85d89e1df6a3f323` | `bfa8c02cb3ab0f9d7bf03335f324973675200a597162e1e5fa4cb5a77dff675d` | 1 | [live](https://testnet.cspr.live/contract/bfa8c02cb3ab0f9d7bf03335f324973675200a597162e1e5fa4cb5a77dff675d) |
| 3 | **Insurance Pool** (hardened) | `78258f66b1ae08120f9c10186ce88772d92d2f84561ca8aa68cb8ffcc6d67f97` | `ead90738d19ad7fcc88c9e079e12d8cf6d4fd09ddd3daafe565bf4fe4b95fff4` | 1 | [live](https://testnet.cspr.live/contract/ead90738d19ad7fcc88c9e079e12d8cf6d4fd09ddd3daafe565bf4fe4b95fff4) |
| 4 | **VRF Arbiter** | `53805f7866cd158ff091ab93efe2f19bd2e803414a5ef1badc7a46d759f36611` | `78ae28702deeb2eadec573d95b870f68b928a82a3566e292ff33a9ae2c779c93` | 1 | [live](https://testnet.cspr.live/contract/78ae28702deeb2eadec573d95b870f68b928a82a3566e292ff33a9ae2c779c93) |
| 5 | **Agent Identity Registry (ID-1)** | `0b760bb7bf9be5a74ee4ed5626bcc74a8154f221a059e29fc9d768d45fb4a2ba` | `345c179cd28eae46bfcda5cd4d8b9192d631593f936af85ccfe3a2cece5c7b1f` | 3 | [live](https://testnet.cspr.live/contract/345c179cd28eae46bfcda5cd4d8b9192d631593f936af85ccfe3a2cece5c7b1f) |
| 6 | **Multi-Asset Escrow (CEP-18)** | `a3207e9bb29f6cec6c5017e6c7538626f92f001d35cda22585dff9f76a488044` | `8080845bad4f12c4a720dd96551dc64d116208aa71e0ce1410b75afca8e8eb61` | 2 | [live](https://testnet.cspr.live/contract/8080845bad4f12c4a720dd96551dc64d116208aa71e0ce1410b75afca8e8eb61) |
| 7 | **CEP-18 Test Token (AETUSD)** | `ea6465021cf2c72b672f7a4fbb4039bb84764a800d279e957847bdff8e38f805` | `177ca5d88f72e1ca72fbe94a24ba34b03830dd1fe63d90d3d719cd6e6d4de754` | 3 | [live](https://testnet.cspr.live/contract/177ca5d88f72e1ca72fbe94a24ba34b03830dd1fe63d90d3d719cd6e6d4de754) |
| 8 | **CEP-18 Test Token (AEMAT)** | `5caa324c3073a8b9fc05076a01e9d4d658cb08a1b4839fa0aa93dac39213e3fd` | `2e319caa09768162144fed4c53f0259ef733ffd97e56a107064026022ac0377b` | 4 | [live](https://testnet.cspr.live/contract/2e319caa09768162144fed4c53f0259ef733ffd97e56a107064026022ac0377b) |
| 9 | **CEP-78 Test NFT (AETNFT)** | `ac38003d1ffe4550aa2ec82cbcd14fc938a078fafc43e111176e7ed6c9a8e85c` | `c2dee0f1f40c3dae3f3106f70d69b8768d7426758b43040673f68e271f2bf70a` | 1 | [live](https://testnet.cspr.live/contract/c2dee0f1f40c3dae3f3106f70d69b8768d7426758b43040673f68e271f2bf70a) |

**Key notes:**
- **Package hash is stable across upgrades** — use it to track a contract across versions (all in-place upgrades preserve the package hash; only contract_hash / deploy_hash / version bump).
- **Deploy hashes** correspond to the *original* installation for hardened redeploys (e.g. insurance-pool `4ea886be…`). For every subsequent version bump the current contract_hash is what governs live behavior.
- **2026-07-19 hardening event** (commit `a9d7071`): `into_hash_addr()` → `into_entity_hash_addr()` for Casper 2.0 `Key::AddressableEntity` compatibility. Redeployed: escrow-manager, agent-identity-registry, multi-asset-escrow, cep18/aemat. Package hashes unchanged.
- **2026-07-19 insurance-pool tombstone patch** — `claimed_escrow_ids` anti-replay guard added; superseded the earlier `e36b958d…` version which had a fully public claim/withdraw.

---

## 2. Post-hackathon contracts (developed under Tier 1 roadmap)

New contracts landed on-branch, awaiting merge into `main` and (re)deploy to testnet at submission time. Contract package hashes will be minted at deploy — package IDs below marked `TBA` will be filled by `scripts/deploy_all_contracts.py --network casper-test` and reflected in `deploy-out/onchain.json`.

| # | Contract | Branch | PR | WASM size | Status |
|---|----------|--------|----|-----------|--------|
| 10 | **Challenge Arbiter (commit-reveal + bond/slash)** | `feat/ae402-challenge-arbiter` | [#55](https://github.com/alexbelij/AgentEscrow402/pull/55) | ~160 KB | code merged locally, testnet deploy `TBA` |
| 11 | **Range Proof Registry (mod-exp on 3072-bit prime, threshold-attested)** | `feat/ae402-range-proofs` | [#62](https://github.com/alexbelij/AgentEscrow402/pull/62) | ~180 KB | code + tests green, testnet deploy `TBA` |
| 12 | **Governance DAO (ported RWA-S primitives + AE402 action layer)** | `feat/ae402-governance-dao` | [#63](https://github.com/alexbelij/AgentEscrow402/pull/63) | 159 KB | code + tests green, testnet deploy `TBA` |
| 13 | **Two-Key Account (cold/hot key AA-style account)** | merged to `main` 2026-07-24 | — | — | code + tests green, testnet deploy `TBA` — see [docs/TWO_KEY_ACCOUNT.md](docs/TWO_KEY_ACCOUNT.md) |

**Test coverage for post-hackathon block:**
- Challenge Arbiter: 26 Rust property tests + 31 Python parity tests
- Range Proof Registry: 32 Rust property tests + 42 Python parity tests
- Governance DAO: 49 Rust property tests + 58 Python (51 parity + 7 lifecycle)
- Two-Key Account: 14 Rust property tests

*(Rust counts verified 2026-07-26 by running the exact package-scoped `cargo test` commands CI
uses; workspace-wide `cargo test --release` is not runnable due to an unrelated
`casper-contract`/`std` feature-unification conflict across the whole workspace — CI and this
manifest both test per-package instead.)*

---

## 3. Testnet activity evidence (bulk-tx logs)

Real testnet deploys / invocations, verifiable by deploy-hash on the block explorer. All logs are structured JSON Lines — one deploy per line, deterministic replay.

| Log file | Contract touched | Deploys | Purpose |
|----------|------------------|---------|---------|
| [`docs/evidence/bulk_escrow_tx_log.jsonl`](./docs/evidence/bulk_escrow_tx_log.jsonl) | escrow-manager | **359** | Bulk escrow lifecycle stress test (create / release across 10 agents, real 5-motes-per-escrow spend) |
| [`docs/evidence/agent_identity_registry_tx_log.jsonl`](./docs/evidence/agent_identity_registry_tx_log.jsonl) | agent-identity-registry | **10** | End-to-end identity registration + v1 → v2 → v3 upgrades with fix commentary |

**Cumulative testnet activity:** **369+ verifiable deploy hashes** across live contracts. Every line in these logs is an on-chain deploy; open any `hash` field on `https://testnet.cspr.live/deploy/<hash>` to inspect state changes, gas, and finality.

### Selected head-of-log entries (for spot-verify)

**bulk_escrow_tx_log.jsonl** (first / last):
```
{"i": 1, "step": "create", "hash": "f1671b725b757e5cacc5e19c04bf56a7ff91ef778f7f080491553c3d1c1fcff7", "success": true}
{"i": 359, "step": "release", "hash": "2185ebd968d31efff83a52c93a0d4091c878d0703b99038f499a1ee3a48e9113", "success": true}
```

**agent_identity_registry_tx_log.jsonl** (highlights):
```
{"i": 1, "step": "deploy_v1", "hash": "97a8a444f5c010dede0083d1c15039f49254ef1339047be6b0c9c00738927641"}
{"i": 3, "step": "deploy_v2_upgrade", "note": "fixed U512->u64 stake-truncation guard and get_blocktime ms-vs-seconds unit bug", "hash": "4c8a6e3c0bfa3f6ea9430e3a92b7c44c2b449c1dca5dd5e8f25f74f4506fe586"}
```

---

## 4. Provenance evidence documents

Human-readable narrative for the two hardest-to-verify capabilities:

- **[`docs/evidence/VRF_ONCHAIN_ELECTION.md`](./docs/evidence/VRF_ONCHAIN_ELECTION.md)** — on-chain VRF arbiter selection walkthrough (proof of on-chain randomness, not off-chain oracle).
- **[`docs/evidence/MULTI_ASSET_ESCROW_ONCHAIN.md`](./docs/evidence/MULTI_ASSET_ESCROW_ONCHAIN.md)** — CEP-18 & CEP-78 escrow flow (transfer-in, hold, release with token custody switch across engine versions).
- **[`docs/evidence/escrow_state_snapshot_pre_multiasset_2026_07_07.json`](./docs/evidence/escrow_state_snapshot_pre_multiasset_2026_07_07.json)** — full state snapshot immediately before the multi-asset upgrade (proof of state-migration safety).

---

## 5. How to verify

**Quick check any contract:**
```bash
# Read live named-keys for a contract package
curl -sS https://node.testnet.cspr.cloud/rpc \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"state_get_dictionary_item",
       "params":{"state_root_hash":"<latest>",
                 "dictionary_identifier":{"ContractNamedKey":{
                   "key":"hash-<contract_hash>",
                   "dictionary_name":"<key>",
                   "dictionary_item_key":"<item>"}}}}'
```

**Or use the console:** open <https://ae402-console.vercel.app> → *"Contracts"* tab → each entry links to its explorer page.

**Or run the audit script:**
```bash
python3 scripts/audit_contract_artifact.py --network casper-test
# Verifies live named-keys against expected shape for every contract in onchain.json
```

**Reproducibility:**
```bash
git clone https://github.com/alexbelij/AgentEscrow402
cd AgentEscrow402
make judge-demo    # boots local NCTL + deploys + runs e2e flow (see Tier 1 T1.1)
```

---

## 6. Regeneration

This manifest is human-curated; the machine-readable inventory drives it. To regenerate `deploy-out/onchain.json`:

```bash
python3 scripts/deploy_all_contracts.py --network casper-test --dry-run  # verify plan
python3 scripts/deploy_all_contracts.py --network casper-test            # actual deploy
python3 scripts/emit_onchain_manifest.py > deploy-out/onchain.json       # regenerate
```

Then update the tables above and bump the "Last regenerated" date.

---

*See also:* [`README.md`](./README.md) · [`CHANGELOG.md`](./CHANGELOG.md) · [`docs/GOVERNANCE.md`](./docs/GOVERNANCE.md) · [`ROADMAP.md`](./ROADMAP.md)
