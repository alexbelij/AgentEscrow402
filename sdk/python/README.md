# agentescrow402-sdk

Publishable Python SDK for **AgentEscrow402** — trustless AI-agent escrow payments on Casper Network.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](../../LICENSE)
[![PyPI ready](https://img.shields.io/badge/pypi-ready-orange.svg)]()

Full parity with the [TypeScript SDK](../../sdk-ts/README.md) — same read
API, same offline arbiter-vote verifier — plus the full write path
(`create_escrow` / `release` / `refund` / `dispute`) that the TS package
does not (yet) cover.

## Install

```bash
pip install agentescrow402-sdk
```

Optional extras:

```bash
pip install "agentescrow402-sdk[langchain]"   # LangChain adapter
pip install "agentescrow402-sdk[mcp]"         # MCP server
pip install "agentescrow402-sdk[dev]"         # tests, ruff, mypy
```

## Quick start — signed client (live API)

```python
import asyncio
from agentescrow402_sdk import EscrowClient

async def main():
    async with EscrowClient.generate("https://agentescrow402-api-ywm8.onrender.com") as client:
        print("agent identity:", client.sender)  # 64-hex Ed25519 pubkey

        escrow = await client.create_escrow(
            receiver="ab" * 32,   # 64-hex Casper account hash
            amount=5000,
            ttl=300,
        )
        print("escrow:", escrow["service_hash"])

        # After the work is delivered:
        await client.release(escrow["service_hash"])

asyncio.run(main())
```

## Quick start — offline vote verification

Verify an arbiter multisig vote **without any HTTP call** — the same
Ed25519 check the on-chain `resolve()` entry point performs, byte-for-byte
identical to `server/arbiter_crypto.py`.

```python
from agentescrow402_sdk import (
    build_resolve_message,
    verify_ed25519_vote,
)

message = build_resolve_message(service_hash="ab" * 32, in_favor_of="cd" * 32)
ok = verify_ed25519_vote(
    pubkey_hex="01" + "..." ,  # tag-prefixed hex
    sig_hex="01" + "...",
    message=message,
)
assert ok
```

Batch verification with dedup + registered-arbiter enforcement:

```python
from agentescrow402_sdk.verify import count_valid_votes

registered = ("01" + pub_a, "01" + pub_b, "01" + pub_c)
valid = count_valid_votes(
    pubkeys=[...],
    signatures=[...],
    registered=registered,
    service_hash="ab" * 32,
    in_favor_of="cd" * 32,
)
if valid >= 2:  # e.g. threshold 2-of-3
    print("resolve vote passes threshold")
```

## Read-only client — no signing needed

```python
async with EscrowClient("https://agentescrow402-api-ywm8.onrender.com") as client:
    status = await client.get_escrow("ab" * 32)
    rep = await client.get_reputation("cd" * 32)
    risk = await client.risk_score("cd" * 32)
    health = await client.health()
```

## Sandbox vs signed mode

| Mode | Constructor | Sends `X-Payment` header | Use when |
|------|-------------|-------------------------|----------|
| Sandbox | `EscrowClient("http://localhost:8000", sender="agent-1")` | No | Local dev against `SANDBOX_MODE=true` backend |
| Signed | `EscrowClient.generate(base_url)` or `EscrowClient(base_url, private_key=priv)` | Yes | Any real deployment |

The live backend rejects unsigned requests with `401 sender identity required`.

## Canonical messages — matches Rust contract exactly

| Purpose | Builder | Format |
|---------|---------|--------|
| `resolve()` verdict | `build_resolve_message(sh, in_favor_of)` | `resolve:{sh}:{in_favor_of}` |
| Above-cap `release()` / `reveal_swap()` | `build_cap_approval_message(action, sh)` | `{action}:{sh}:cap_approval` |
| Insurance-pool `claim()` | `build_insurance_claim_message(id, ah, amount)` | `claim:{id}:{ah}:{amount}` |

All messages must match `contracts/escrow/src/main.rs` and
`contracts/insurance-pool/src/main.rs` byte-for-byte. If the Rust
contract changes, this module must too.

## Development

```bash
cd sdk/python
pip install -e ".[dev]"
pytest tests/
ruff check .
```

## Parity with the TypeScript SDK

| Feature | Python | TS |
|---------|--------|-----|
| Read: `get_escrow` / `get_reputation` / `risk_score` / `health` | ✅ | ✅ |
| `verify_ed25519_vote` | ✅ | ✅ |
| `count_valid_votes` + variants | ✅ | ✅ |
| Signed write path (`create_escrow` / `release` / `refund` / `dispute`) | ✅ | ❌ (planned) |
| LangChain adapter | ✅ | ❌ |
| MCP server | ✅ | ❌ |

## License

MIT — see [`LICENSE`](../../LICENSE).
