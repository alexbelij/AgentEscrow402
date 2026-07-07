# MultiAssetEscrow — real on-chain evidence

This documents the first real, contract-custody deployment and full
lifecycle exercise of `contracts/multi-asset-escrow` against the deployed
CEP-18-compatible test token, on Casper testnet. All transactions below
are real, submitted with the alexbelij deployer secp256k1 key and a
generated 5-key ed25519 arbiter set, and independently re-verified by
reading the token's own `balances` dictionary on-chain after each step
(not just deploy success/failure).

## Contracts involved

| Contract | Hash | Package hash |
|---|---|---|
| MultiAssetEscrow | `52db09a146158ba2a07b5da07587046985ce8ca3be094fca9ad63cb6b9ecd12a` | `a3207e9bb29f6cec6c5017e6c7538626f92f001d35cda22585dff9f76a488044` |
| Test token (AEMAT), upgraded | `8ba7df6fd9a12c71de903a915717537eeff4f04adf33f4ed8abf16c254e300a5` | `5caa324c3073a8b9fc05076a01e9d4d658cb08a1b4839fa0aa93dac39213e3fd` (unchanged) |

The test token's package hash is unchanged from the one given in the task
brief (`5caa324c...`) -- it was upgraded twice in place via
`add_contract_version` (see "Test token upgrade" below), so its balances
dictionary and the installer's original 1,000,000.000000 AEMAT balance
were preserved throughout.

Accounts:
- Installer / depositor: `74c96cd0073c4c973b70e7925adca8a4ba58ffcb9737304631381b82695007a8`
- Test receiver: `9707af970eff80a708a791be528b639c6642019e38cbed8bf84d915909cfac6d`

## Why the test token needed an upgrade first

`runtime::get_caller()` in Casper always returns an `AccountHash` -- by
construction it can never represent a contract, so across a
contract-to-contract call it still resolves to the transaction's
originating account, not the immediate calling contract. The originally
deployed test token derived the acting identity for
`transfer`/`transfer_from`/`approve` purely from `get_caller()`, which
made it structurally impossible for any contract (including
MultiAssetEscrow) to ever be recognized as a token holder or an approved
spender in its own right -- there is no way to make `get_caller()`
resolve to a contract's identity.

Fix: the token's `caller_key()` now uses
`runtime::get_immediate_caller()`, which *can* represent a calling smart
contract (`Caller::SmartContract{contract_package_hash, ..}`) distinct
from a directly-signing account (`Caller::Initiator`). This was deployed
as an `add_contract_version` upgrade to the same package (see contract
hash history below) -- a real code fix, not a workaround in the test
harness. A second upgrade also fixed the `allowances`/`balances`
dictionary key format: a plain `"{owner}:{spender}"` string overflowed
Casper's 64-byte dictionary-item-key cap once either identity was a
73-char `contract-<hex>` string, so the allowance key is now a blake2b256
hash of both parts, and the plain per-address key dropped the
`contract-` prefix entirely (`ApiError::DictionaryItemKeyTooLarge`,
first hit and fixed live during this exercise).

Test token contract-hash history on the same package
(`5caa324c...`): `761664c7...` (given in task brief) → `f5b6c6bf...`
(immediate-caller fix) → `8ba7df6f...` (dictionary-key-length fix, used
for all lifecycle calls below).

## 1. Arbiter registration

`set_arbiters` on MultiAssetEscrow, 5 freshly generated ed25519 keys,
threshold 3 (default).

- Deploy: `0a57f2a27a33d580baaf0b2f9c976a541ac731c2ba01ca1b7109975e62ee8659` — success

## 2. Approve (depositor grants MultiAssetEscrow spending allowance)

`token.approve(spender=Key::Hash(<MultiAssetEscrow package hash>), amount=9,000,000)`
(covers all three escrows below).

- Deploy: `ddccf532e8cc49c734711ef295b26b72d118d935e9edb5a2c1b8cb4f5f6e1692` — success

## 3. Create → release (happy path)

`create_escrow(receiver=<test receiver>, amount=3,000,000, service_hash=56c56484ecd48a26bba39f77ff6169f1cf417dbf707a2192699969576967d594, ttl=600, fee_bps=200)`

- Deploy: `b2ce1e8848eda2ecb6d80f00a111e5c9a13033cfb52e6fcc4e4d52aa700b2e1c` — success
- On-chain custody check right after create: MultiAssetEscrow's own
  balance slot in the token's `balances` dict (keyed by its package hash,
  `a3207e9b...`) = **3,000,000** (real contract custody, not bookkeeping
  -- confirmed by directly reading the dictionary via
  `state_get_dictionary_item`, not just deploy success).
- Installer balance dropped from 1,000,000.000000 to 999,997.000000 AEMAT
  in the same read.

`release(service_hash=..., arbiter_pubkeys=[], arbiter_signatures=[])`
(amount well under the default release cap, no arbiter quorum needed)

- Deploy: `2683966f1f2c2e62d0f6edfe71192664cb7de1c38ef2272238f13623e9db9ea3` — success
- Post-release balances: contract custody → **0**, receiver → **2,940,000**
  (3,000,000 − 2% fee), installer (fee recipient) → **999,997,060,000**
  raw units (+60,000 fee). Numbers reconcile exactly: 2,940,000 + 60,000
  = 3,000,000.

## 4. Create → refund (TTL expiry path)

`create_escrow(receiver=<test receiver>, amount=2,000,000, service_hash=f496e53c2b5fb8711c186f44b1267171aa59f73faf1021622717230a34a14868, ttl=60, fee_bps=0)`

- Deploy: `78fbabb66ba8b5f71d6ac42502e9b8a6059dbc2a47b1e2dbe53481fa05e8fa55` — success

Waited > 60s for the TTL to expire, then:

`refund(service_hash=...)`

- Deploy: `0f03365e949ad5c404d0cc43dee3a589f271b4355d700f170a763df8d5881b76` — success
- Post-refund balances: contract custody → **0**, installer back to
  **999,997,060,000** raw units (same balance as before this escrow,
  fee_bps was 0).

## 5. Create → dispute → resolve (arbiter quorum path)

`create_escrow(receiver=<test receiver>, amount=1,000,000, service_hash=7b976f5fce176ebd6974023d2cb374f81cb222957035ff545ee6da1c9ad62770, ttl=600, fee_bps=0)`

- Deploy: `da0b3a7c984b2bb2e3c127674bf97767470d1051ebf6af1f129335b94dfe36b5` — success

`dispute(service_hash=...)`

- Deploy: `03633cdeef8d2f9a8e68736a5086d072d561f7b3c0a4c0d21722cd36f698db99` — success (status flips to `disputed` = 4)

`resolve(service_hash=..., in_favor_of="receiver", arbiter_pubkeys=[3 of the 5 registered arbiters], arbiter_signatures=[real ed25519 signatures over "resolve:{service_hash}:receiver", verified on-chain via `casper_types::crypto::verify`])`

- Deploy: `3c45b9732bc1c59b825e62f0fbc5ea8ba410a8efd47d406982c633eb51251a9e` — success
- Post-resolve balances: contract custody → **0**, receiver →
  **3,940,000** (2,940,000 from the release path above + 1,000,000 from
  this resolve). Escrow record status = `5` (`resolved`).

## Summary

| Path | Create deploy | Terminal-action deploy | Verified balance movement |
|---|---|---|---|
| Happy path (release) | `b2ce1e88...` | `2683966f...` (release) | custody 0→3,000,000→0; receiver +2,940,000; fee +60,000 |
| TTL expiry (refund) | `78fbabb6...` | `0f03365e...` (refund) | custody 0→2,000,000→0; sender fully refunded |
| Dispute + resolve | `da0b3a7c...` | `03633cde...` (dispute) → `3c45b973...` (resolve) | custody 0→1,000,000→0; receiver +1,000,000 |

All balance figures were read directly from the token contract's
`balances` dictionary via `state_get_dictionary_item` RPC calls (see
`scripts/query_multi_asset_state.py`), not inferred from deploy success
alone.
