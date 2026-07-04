# AgentEscrow402 SDK

## Python Client

### Signed mode — required for the real/live deployment
The live production API (and any deployment run with `SANDBOX=false`)
verifies a real Ed25519-signed `X-Payment` header on every request. There is
no unsigned path in that mode — `EscrowClient.generate(...)` handles signing
for you by deriving your agent's identity from a fresh keypair:

```python
from sdk.client import EscrowClient

async with EscrowClient.generate("https://agentescrow402-api.onrender.com") as client:
    print(client.sender)  # your agent's 64-hex Ed25519 public key / on-chain identity

    # receiver must be a real 64-hex Casper account hash (optionally
    # "account-hash-" prefixed) -- the API rejects anything else with 422.
    receiver = "ab" * 32
    escrow = await client.create_escrow(receiver=receiver, amount=5000, ttl=300)
    print(escrow["service_hash"])

    status = await client.get_escrow(escrow["service_hash"])
    await client.release(escrow["service_hash"], amount=5000)
    rep = await client.get_reputation(client.sender)
```

To reuse the same on-chain identity across runs, generate a keypair once and
pass it back in:
```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

key = Ed25519PrivateKey.generate()  # persist this, e.g. to a file, for reuse
client = EscrowClient("https://agentescrow402-api.onrender.com", private_key=key)
```

### Sandbox mode — quick local testing only
Your own local instance run with `SANDBOX=true` (the default) accepts a
plain string identity with no signature — convenient for local dev, but the
live deployment will reject it with `401 sender identity required`:
```python
async with EscrowClient("http://localhost:8000", sender="agent-001", sandbox=True) as client:
    escrow = await client.create_escrow(receiver="ab" * 32, amount=5000, ttl=300)
    await client.release(escrow["service_hash"])
```

### Full runnable examples
- `examples/quickstart.py` — minimal signed create → release
- `examples/escrow_agent.py` — full autonomous buyer/seller lifecycle,
  including a real dispute and a real AI arbitration call

## LangChain Tool

```python
from sdk.langchain_tool import EscrowPaymentTool

tool = EscrowPaymentTool("http://localhost:8000", sender="agent-001")  # sandbox mode
result = await tool.run("create", receiver="ab" * 32, amount=5000)
result = await tool.run("release", service_hash=result["service_hash"])
```

## MCP Server

The MCP server lets any MCP-compatible LLM manage escrow payments.

**Start (stdio):**
```bash
python -m sdk.mcp_server
```

**Start (SSE):**
```bash
pip install mcp[sse] uvicorn starlette
python -m sdk.mcp_server --transport sse --port 8402
```

**Available tools:**

| Tool | Description |
|------|-------------|
| `create_escrow` | Lock funds between sender and receiver |
| `release_escrow` | Release funds to receiver |
| `refund_escrow` | Return funds to sender |
| `dispute_escrow` | Open a dispute |
| `get_escrow` | Check escrow status |
| `get_reputation` | Query agent reputation |
| `build_x402_header` | Build x402 payment header |

## x402 Header Format

Real, verified header (what the live server requires, and what
`EscrowClient.generate(...)` builds automatically):
```
x402-v1;<escrow_hash>;<amount>;<sender>;<timestamp>;<nonce>;<signature>
```
`signature` is an Ed25519 signature (128 hex chars) over
`x402-v1;<escrow_hash>;<amount>;<sender>;<timestamp>;<nonce>;<method>;<path>`,
binding it to the exact HTTP method and path being called.

`EscrowClient.build_x402_header(...)` also exists for legacy/manual use, but
it builds an **unsigned** header (`x402;1;<amount>;<service_hash>;<timestamp>;<nonce>`)
that a real (non-sandbox) deployment will reject — prefer signed mode above.
