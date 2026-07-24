# AE402 — Deployment Guide

Reproducible deploy path for the whole stack: the Casper testnet
contracts under `contracts/` (see `deploy-out/onchain.json` for the
current authoritative list and hashes), FastAPI backend, React console,
and the `verify.sh` proof.

## 0. Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Rust nightly | `nightly-2025-01-01` (pinned in `contracts/rust-toolchain.toml` -- confirmed deploy-compatible; newer nightlies have emitted bulk-memory WASM ops that Casper testnet preprocessing rejects, see `docs/DEPLOYMENT_LESSONS.md`) | Contract compilation to `wasm32-unknown-unknown`. |
| `casper-client` | ≥ 2.0 | On-chain deploys, contract queries. |
| Node.js | 22.x | Casper JS SDK for `server/casper_tx/` scripts, frontend build. |
| Python | 3.11 | Backend (`server/`) and SDK (`sdk/`). |
| Postgres | 15+ (Neon or self-hosted) | Persistent escrow / reputation state (skip if only sandbox mode). |
| `jq`, `curl` | latest | Used by `verify.sh`. |

Casper testnet faucet: <https://testnet.cspr.live/tools/faucet> — you need
~5 000 CSPR to run all deploys with room to spare.

## 1. Contract compilation

```bash
git clone https://github.com/alexbelij/AgentEscrow402.git
cd AgentEscrow402/contracts
cargo build --release --target wasm32-unknown-unknown
```

The workspace at `contracts/Cargo.toml` compiles all stored contracts
(`escrow`, `escrow-manager`, `insurance-pool`, `vrf-arbiter`,
`agent-identity-registry`, `test-token`, `multi-asset-escrow`) plus their
session-WASM installers (`pool-funder`, `arbiter-registrar`,
`batch-funder`, `id-registry-funder`) and the `tests` crate. Artifacts
land in `contracts/target/wasm32-unknown-unknown/release/*.wasm`.

The Makefile shortcut compiles only the two most-changed contracts
(`make contracts`); use the raw `cargo build` above for the full set.

## 2. Contract deployment (one-by-one)

Each contract goes on-chain via `casper-client put-deploy` referencing its
compiled `.wasm`. Below is the template; substitute `<KEY>` with your
funded testnet private key path and adjust `--payment-amount` per contract
(insurance-pool needs ~50 CSPR, VRF ~35 CSPR, etc — see gas breakdown in
`docs/GAS_BENCHMARK.md`).

```bash
export NODE=http://node.testnet.cspr.cloud:7777
export CHAIN=casper-test

# 1. Core Escrow
casper-client put-deploy \
  --node-address $NODE \
  --chain-name $CHAIN \
  --secret-key <KEY> \
  --payment-amount 200000000000 \
  --session-path contracts/target/wasm32-unknown-unknown/release/escrow.wasm

# 2. Escrow Manager (batch orchestration)
casper-client put-deploy \
  --node-address $NODE \
  --chain-name $CHAIN \
  --secret-key <KEY> \
  --payment-amount 100000000000 \
  --session-path contracts/target/wasm32-unknown-unknown/release/escrow_manager.wasm

# 3. Insurance Pool  (hardened redeploy — the old public-claim variant is superseded)
casper-client put-deploy \
  --node-address $NODE \
  --chain-name $CHAIN \
  --secret-key <KEY> \
  --payment-amount 200000000000 \
  --session-path contracts/target/wasm32-unknown-unknown/release/insurance_pool.wasm

# 4. VRF Arbiter
casper-client put-deploy \
  --node-address $NODE \
  --chain-name $CHAIN \
  --secret-key <KEY> \
  --payment-amount 100000000000 \
  --session-path contracts/target/wasm32-unknown-unknown/release/vrf_arbiter.wasm

# 5. Agent Identity Registry
casper-client put-deploy \
  --node-address $NODE \
  --chain-name $CHAIN \
  --secret-key <KEY> \
  --payment-amount 150000000000 \
  --session-path contracts/target/wasm32-unknown-unknown/release/agent_identity_registry.wasm

# 6. MultiAssetEscrow
casper-client put-deploy \
  --node-address $NODE \
  --chain-name $CHAIN \
  --secret-key <KEY> \
  --payment-amount 200000000000 \
  --session-path contracts/target/wasm32-unknown-unknown/release/multi_asset_escrow.wasm

# 7 & 8. CEP-18 test tokens AETUSD and AEMAT
casper-client put-deploy --node-address $NODE --chain-name $CHAIN \
  --secret-key <KEY> --payment-amount 100000000000 \
  --session-path contracts/target/wasm32-unknown-unknown/release/test_token.wasm \
  --session-arg "name:string='AETUSD'" \
  --session-arg "symbol:string='AETUSD'" \
  --session-arg "decimals:u8='6'" \
  --session-arg "total_supply:u256='1000000000000'"

# same again with name='AEMAT'
```

After each `put-deploy`:

```bash
casper-client get-deploy --node-address $NODE <deploy_hash>
```

Wait for `"execution_results": [ {"success": …} ]` and copy the resulting
`contract_hash` + `contract_package_hash` from the transforms.

## 3. Record on-chain evidence

Update `deploy-out/onchain.json` with each new deploy hash / contract hash
/ package hash. Frontend loads this file at `/onchain.json` (build copies
it into `frontend/public/`). Structure is:

```json
{
  "network": "casper-test",
  "generated_at": "<ISO-8601>",
  "contracts": {
    "escrow_manager_v9": {
      "name": "Core Escrow",
      "contract_hash": "hash-<hex>",
      "contract_package_hash": "hash-<hex>",
      "deploy_hash": "<hex>",
      "version": 9,
      "explorer": "https://testnet.cspr.live/contract/<hex>"
    },
    …
  },
  "source_ref": "CSPR.cloud API verified <YYYY-MM-DD>"
}
```

Verify each entry against CSPR.cloud before committing:

```bash
curl -s "https://api.testnet.cspr.cloud/contracts/<hex>?apikey=$CSPR_CLOUD_KEY" | jq '.contract_hash'
```

## 4. Backend setup (`server/`)

```bash
cd AgentEscrow402
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt      # tests + lint
cp .env.example .env                      # then edit
```

Minimum `.env`:

```env
# Chain
CASPER_NODE_URL=http://node.testnet.cspr.cloud:7777
CASPER_CHAIN_NAME=casper-test
CASPER_PRIVATE_KEY_PATH=/etc/ae402/keys/backend-signer.pem

# Contract hashes (paste from deploy-out/onchain.json)
CONTRACT_HASH=<hex from Core Escrow>
MANAGER_CONTRACT_HASH=<hex from Escrow Manager>
INSURANCE_CONTRACT_HASH=<hex>
INSURANCE_PACKAGE_HASH=<hex>
VRF_CONTRACT_HASH=<hex>
VRF_PACKAGE_HASH=<hex>
MULTI_ASSET_ESCROW_CONTRACT_HASH=<hex>
MULTI_ASSET_ESCROW_PACKAGE_HASH=<hex>
TEST_TOKEN_CONTRACT_HASH=<hex AETUSD>

# Mode
SANDBOX=0        # 1 for demo without RPC calls
AE402_STRICT=0   # 1 forces all-real-or-503; see docs/REAL_VS_SIM.md

# DB (Neon)
DATABASE_URL=postgres://…

# LLM chain (optional — falls back to next tier if unset)
GROQ_API_KEY=…
NVIDIA_NIM_API_KEY=…
OPENROUTER_API_KEY=…

# Admin
ADMIN_API_KEY=<shared secret for /admin/* routes>
```

Migrate + run:

```bash
alembic upgrade head        # if migrations directory is present
make run                    # uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload
```

Docker path:

```bash
docker build -t ae402-api .
docker compose up            # honors docker-compose.yml
```

Health check:

```bash
curl -s http://localhost:8000/health | jq
# expect {"status":"ok", "mode": "sandbox"|"live", "version": "…"}
```

## 5. Frontend build (`frontend/`)

```bash
cd frontend
npm install
cp .env.example .env         # then edit VITE_API_URL
npm run build                # tsc && vite build → dist/
```

Preview locally:

```bash
npm run preview              # serves dist/
```

Deploy target (production is <https://ae402.xyz>):

- Static host (any) serving `frontend/dist/`. Rewrite `/*` → `/index.html`
  for React Router.
- Ensure `/onchain.json` is served — the file lives at
  `frontend/public/onchain.json` and Vite copies it to `dist/` verbatim.

## 6. Verification

Run against the deployed API:

```bash
./verify.sh --api https://<your-api-host>
```

`verify.sh` performs five real checks:

1. Every contract listed in `deploy-out/onchain.json` exists on Casper testnet (via CSPR.cloud API).
2. API `/health` returns `status=ok`.
3. Escrow round-trip (create → list → detail) works.
4. Frontend serves HTML at `<frontend URL>/`.
5. `onchain.json` matches live contract state.

Exit code is 0 iff every check passes. `verify.sh` is the source of truth
for "did we ship it correctly" — CI runs it against every push to `main`.

## 7. Rollback

Contracts on Casper are versioned via `contract_package_hash`; a bad
deploy can be superseded by a new versioned `new_contract()` call under
the same package. The **old contract stays reachable** by hash. Update
`deploy-out/onchain.json` with the new version and re-run `verify.sh`.
The insurance-pool contract already demonstrates this: the old
`e36b958d…` variant is documented as superseded in the JSON `notes`.

Backend rollback: revert to the previous container image tag; the API is
stateless (Postgres is the only durable state, and migrations are
forward-only, so schema rollbacks require a manual `alembic downgrade`).
