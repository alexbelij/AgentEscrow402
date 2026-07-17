# ⚠️ Test-only arbiter keys — DO NOT use this pattern for production

This directory contains the **5 Ed25519 private keys** for the throwaway
"arbiter" accounts registered as the multisig dispute-resolution committee
on our **Casper Testnet** deployment of the Core Escrow contract
(`50ca336428601e9920f3493112cad452c4b9359b1a88fd8893441b41c4498664`).

## What these keys are

- Generated purely as demo/test fixtures via `server/casper_tx/gen_arbiters.mjs`.
- **Never funded.** All 5 accounts hold `0 CSPR` (verified via CSPR.cloud) —
  they are not real, funded testnet accounts, just keypairs.
- Registered on-chain via `set_arbiters` as the 5 addresses whose Ed25519
  signatures the contract accepts as valid arbiter votes (3-of-5 threshold)
  for `resolve()` on **this specific escrow contract only**. Confirmed still
  valid after the v8→v9 in-place upgrade (current contract hash
  `612cead2...ddd9ec`, same package `d3ca33d1...c8eeb`) — a real
  `dispute`→`resolve` cycle signed with these same 5 keys against the current
  live contract is recorded in
  [docs/evidence/bulk_escrow_tx_log.jsonl](../../docs/evidence/bulk_escrow_tx_log.jsonl).
- They are used by `sdk/arbiter_signing.py` / `examples/escrow_agent.py`
  to produce real signatures over the canonical vote message
  `resolve:{service_hash}:{in_favor_of}`, so graders/reviewers can run the
  full dispute → resolve flow themselves end-to-end without needing to be
  handed any of the project's real deployer credentials.

## What these keys can NOT do

- They cannot move funds, they are not the contract's deployer/upgrader key,
  and they have no relationship whatsoever to the real Casper accounts used
  to deploy/own this project's contracts (those private keys are never
  committed anywhere).
- Their only power is to sign one specific message format for one specific
  contract's arbiter vote — nothing else.

## How to test with these keys

These keys are picked up automatically by `examples/escrow_agent.py` (default
`ARBITER_KEYS_DIR=demo/test-arbiter-keys`), which runs the full buyer/seller
lifecycle including a real dispute + real arbiter multisig resolve. This is
the fastest way to independently verify the 3-of-5 arbiter flow described in
[docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md):

```bash
# Against the live production API (real testnet transactions):
python examples/escrow_agent.py --api-url https://agentescrow402-api-ywm8.onrender.com --scenario bad

# Or against your own local server (sandbox mode, no real chain calls):
uvicorn server.app:app --reload &
python examples/escrow_agent.py --scenario bad
```

The `bad` scenario runs a buyer who disputes a delivery; the script signs the
dispute vote with 3 of these 5 keys (`sign_arbiter_vote` in
`sdk/arbiter_signing.py`) and calls `/resolve`, which the backend submits
on-chain as a real `resolve()` transaction — the contract itself verifies
each Ed25519 signature against the registered `arbiter_list` before paying
out. Watch for a `deploy_hash` in the output and confirm it on
[testnet.cspr.live](https://testnet.cspr.live) to see the real multisig
quorum check execute.

To sign an arbiter vote manually (e.g. to test `/resolve` directly via curl
or the SDK) without running the full scenario script:

```python
from sdk.arbiter_signing import sign_arbiter_vote

pubkey_hex, signature_hex = sign_arbiter_vote(
    "demo/test-arbiter-keys/arbiter_1_secret_key.pem",
    service_hash="<64-char hex service_hash of the disputed escrow>",
    in_favor_of="receiver",  # or "sender"
)
```

Repeat with `arbiter_2_secret_key.pem` and `arbiter_3_secret_key.pem` (or any
3 of the 5) to assemble the `arbiter_pubkeys`/`arbiter_signatures` lists that
`POST /resolve` expects — 3 valid signatures is quorum for this contract.

## Why they're committed here

Committing real, unfunded, single-purpose demo keys makes the submission
independently reproducible: a judge or reviewer can clone the repo, run
`examples/escrow_agent.py` (or drive `/resolve` via the SDK directly) and
watch a full create → dispute → resolve cycle happen on Casper Testnet with
genuine on-chain signature verification, instead of having to trust a
screenshot or take our word for it.

**If you fork this project for anything beyond this demo:** generate your
own arbiter keypairs (`gen_arbiters.mjs`), re-register them via
`set_arbiters`, and never commit private keys that hold real value or that
control upgradeable/privileged contract entry points.

Pubkeys / account-hashes (for reference, all public info):

| # | Pubkey (tag-prefixed hex) | Account hash |
|---|---|---|
| 1 | `0112e33a39f03fba483baf7a62f299a559986112349da0a7630d3e55af854718ae` | `653a5c993d32abf9aed9603a68ba0fe4c448384b39cefd25a644dc916004db87` |
| 2 | `01a28e3979a681c8c1a1c1a065673c647713363c68b12201066aaa4dfd148ed7cf` | `83ffef7888ad9daefbeefbda5cb39c45cea9980fae61d31c01795c6cac8d2b08` |
| 3 | `0159823821c9faac713f25765d6f58cee5726e8bd3d83ead4a9e83cab009e3230c` | `05e10552ee70c4fbbf5349803723604909cfa60fa228177c0ca7d5bc37259eef` |
| 4 | `01628e3697932e64168e65f8784fbe547ec2dadabee2d76951cd9271dd86a2f95d` | `e3f1428201809881ffdf96d4d60edbd43df8a91c2487564437903db783bb2c91` |
| 5 | `012d703284694bdc6a47be7237f70c075b8d0ca7b9ee1ea560e2eb8b38754932ad` | `edeef6ad9758ba9ed06c89effbbfd4a5772a38907c219090f60d310585b0de54` |
