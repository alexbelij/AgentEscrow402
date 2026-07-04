# ⚠️ Test-only arbiter keys — DO NOT use this pattern for production

This directory contains the **5 Ed25519 private keys** for the throwaway
"arbiter" accounts registered as the multisig dispute-resolution committee
on our **Casper Testnet** deployment of the Core Escrow contract
(`dca7e926af8aac73fc1104e1bb9a52b0035a9196bef5de8336557ea34cec69d6`).

## What these keys are

- Generated purely as demo/test fixtures via `server/casper_tx/gen_arbiters.mjs`.
- **Never funded.** All 5 accounts hold `0 CSPR` (verified via CSPR.cloud) —
  they are not real, funded testnet accounts, just keypairs.
- Registered on-chain via `set_arbiters` as the 5 addresses whose Ed25519
  signatures the contract accepts as valid arbiter votes (3-of-5 threshold)
  for `resolve()` on **this specific escrow contract only**.
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
