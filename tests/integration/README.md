# Integration tests — Casper NCTL

End-to-end escrow lifecycle against a **local Casper 2.0 network** running
via [makesoftware/casper-nctl][image]. These are excluded from the default
`pytest` run — start the network first, then run this suite explicitly.

[image]: https://hub.docker.com/r/makesoftware/casper-nctl

## Why a separate suite

The unit tests in `tests/` mock every RPC call. That's fast and hermetic,
but it never catches:

- casper-js-sdk deploy format regressions,
- `escrow_funder.wasm` bytecode issues,
- contract entry-point argument mismatches,
- account-state (main purse / balance) parsing drift between Casper 1.x
  and 2.x block formats.

This suite catches all four by spinning up a real 5-node network locally,
deploying the real WASM, and driving the same `CasperClient` production
uses.

## Prerequisites

- Docker + Docker Compose
- `node` + `npm install` at repo root (so `casper-js-sdk` is available
  to the bundled tx scripts in `server/casper_tx/`)
- Python deps: `pip install -e .[dev]` (or whatever installs
  `httpx`, `pytest`, `pytest-asyncio`)

## Running locally

```bash
# 1. Start the local network. Takes ~30-60s for the first block.
docker-compose -f docker-compose.casper-nctl.yml up -d
docker-compose -f docker-compose.casper-nctl.yml ps    # confirm health

# 2. Pull the predefined faucet + user keys out of the container.
./scripts/nctl_keys.sh /tmp/nctl-keys

# 3. Run the suite.
NCTL_KEYS_DIR=/tmp/nctl-keys \
NCTL_RPC_URL=http://127.0.0.1:11101/rpc \
  pytest tests/integration/ -m casper_net -v

# 4. Teardown (also wipes the tmpfs assets tree).
docker-compose -f docker-compose.casper-nctl.yml down -v
```

## Skip behaviour

If any of these are missing:

- `${NCTL_KEYS_DIR}/faucet-secret_key.pem`
- RPC at `${NCTL_RPC_URL}`
- `node` on PATH + `casper-js-sdk` in `node_modules/`

…every `casper_net`-marked test is auto-skipped with an explanatory
reason. The suite never fails on infra-not-present — you always get a
clear message.

## What's covered

| # | Test                                    | Verifies                                                  |
|---|-----------------------------------------|-----------------------------------------------------------|
| 1 | `test_nctl_rpc_reachable`               | `info_get_status` responds with a chain identifier        |
| 2 | `test_nctl_produces_blocks`             | validators advance the chain within 60s                   |
| 3 | `test_faucet_is_funded`                 | main-purse balance parsing works on Casper 2.0            |
| 4 | `test_predefined_users_exist`           | `PREDEFINED_ACCOUNTS=true` ships users 1..3               |
| 5 | `test_contract_is_installed`            | `escrow_funder.wasm` deploys and returns a contract hash  |
| 6 | `test_escrow_create_and_release`        | full happy-path: create → get → release                   |
| 7 | `test_escrow_create_and_refund`         | refund path: create → refund                              |

Tests 5-7 chain: 5 installs the contract once per session and 6/7 reuse
its hash. If 5 fails (Node.js env missing, deploy_contract_legacy.mjs
regression, etc.) 6/7 skip cleanly.

## CI

See `.github/workflows/casper-nctl-integration.yml` — the workflow reuses
this suite with a service-container NCTL and posts a job-summary if any
lifecycle test fails.
