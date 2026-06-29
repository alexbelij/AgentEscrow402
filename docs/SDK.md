# AgentEscrow402 SDK

## Python Client

```python
from sdk.client import EscrowClient

async with EscrowClient("http://localhost:8000", sender="agent-001") as client:
    # Create escrow
    escrow = await client.create_escrow(receiver="svc-007", amount=5000, ttl=300)
    print(escrow["service_hash"])

    # Check status
    status = await client.get_escrow(escrow["service_hash"])

    # Release funds
    await client.release(escrow["service_hash"])

    # Check reputation
    rep = await client.get_reputation("agent-001")
```

## LangChain Tool

```python
from sdk.langchain_tool import EscrowPaymentTool

tool = EscrowPaymentTool("http://localhost:8000", sender="agent-001")
result = await tool.run("create", receiver="svc-007", amount=5000)
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

```
x402;1;<amount>;<service_hash>;<timestamp>;<nonce>
```

Build programmatically:
```python
header = client.build_x402_header(receiver="svc-007", amount=5000)
```
