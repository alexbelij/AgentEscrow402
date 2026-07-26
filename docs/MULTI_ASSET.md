# Multi-asset escrow

AE402 supports three asset types via a single `/escrow/multi-asset`
endpoint:

- **CSPR** — native Casper motes. Custodial demo model (operator
  moves funds).
- **CEP-18** — fungible tokens against a deployed CEP-18 contract.
  Custodial demo model, plus a gasless permit path (CEP-2612-style)
  where funds move from the user's own wallet balance via
  `permit() + transfer_from()`.
- **CEP-78** — enhanced NFTs. Custodial demo model.

Full router: `server/multi_asset.py`. Backing contract:
`MultiAssetEscrow` — hash and explorer link in `TX_MANIFEST.md`.

## Demo

```
python -m demo.multi_asset_flow                  # CSPR happy path
python -m demo.multi_asset_flow --refund         # CSPR refund path
python -m demo.multi_asset_flow --amount 5000000000 --json
```

Both paths run entirely in-process against a sandbox FastAPI stack —
no network, no Casper deploy latency — and complete in <1 s each.

### What the demo exercises end-to-end

1. `POST /escrow/multi-asset` — create with x402 auth, `token_type=cspr`.
2. `SandboxStore.create_escrow` — pending record persisted.
3. `POST /release` (or `/refund`) — same x402 identity proves caller
   is the escrow's own sender.
4. `GET /escrow/{service_hash}` — final state, status flipped to
   `released` / `refunded`.

### CEP-18 note

The demo defaults to CSPR because the CEP-18 code path calls
`CasperClient.cep18_transfer`, which needs the live deployed CEP-18
contract at `cep18_aetusd_contract_hash` (see `TX_MANIFEST.md`) —
the sandbox Casper stub does not fulfil that call. To exercise CEP-18
end-to-end, point the demo at a live backend (that variant is one PR
away — build it against `sdk.EscrowClient` with a real signing key
and hit the deployed API URL instead of `TestClient`).

## Wire format

```
POST /escrow/multi-asset
Headers:
  X-Payment: x402-v1;<service_hash>;<amount>;<sender>;<ts>;<nonce>;<sig>
  X-AE402-Demo-Identity: hosted-console       # optional, only in sandbox
Body:
  {
    "receiver": "<64-hex account hash>",
    "amount_motes": 1000000000,               # or "amount" for token units
    "token": {
      "token_type": "cspr" | "cep18" | "cep78",
      "contract_hash": "..."                  # required for cep18/cep78
    },
    "service_hash": "<64-hex>",
    "ttl": 300,                               # 60..86400
    "permit": { ... }                         # optional, cep18 only
  }
```

See `docs/openapi.yaml` for the full schema (path `/escrow/multi-asset`).

## Related

- `server/multi_asset.py` — router + adapters (CSPR, CEP-18, CEP-78).
- `demo/multi_asset_flow.py` — this demo.
- `tests/test_multi_asset.py` — router integration tests.
- `tests/test_demo_multi_asset_flow.py` — demo smoke tests.
- `docs/DEMO.md` (from C1) — the other demo (`ae402 replay`).
- `TX_MANIFEST.md` — canonical MultiAssetEscrow contract hash.
