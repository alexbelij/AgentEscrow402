# Demo Video Script

Target duration: 2:00-2:30

## Timeline

| Time | Scene | Action |
|------|-------|--------|
| 0:00-0:10 | Title card | "AgentEscrow402 — x402 Payments for AI Agents on Casper" |
| 0:10-0:25 | Problem | AI agents cannot pay for API services programmatically. Show failed HTTP request. |
| 0:25-0:40 | Solution | x402-compatible middleware + on-chain escrow. Show architecture diagram. |
| 0:40-1:10 | Live demo | Agent calls API → gets 402 → pays via escrow → gets data. Show terminal + Casper Explorer. |
| 1:10-1:25 | Dispute | Agent disputes → 3-of-5 arbiters resolve. Show on-chain transaction. |
| 1:25-1:40 | On-chain proof | Show transactions in Casper Explorer (escrow create, release, dispute). |
| 1:40-1:55 | LangChain | EscrowPaymentTool integration. Show 3-line code snippet. |
| 1:55-2:10 | Reputation | Reputation board with decay formula. Insurance pool stats. |
| 2:10-2:25 | Architecture | Full system diagram. Mention sandbox mode for quick testing. |
| 2:25-2:30 | Close | "Machine-to-machine commerce, trustlessly on Casper." |

## Commands to Run

```bash
# Terminal 1: Start server
python -m uvicorn server.app:app --port 8000

# Terminal 2: Run quickstart
python examples/quickstart.py

# Terminal 3: Show Casper Explorer
open https://integration.cspr.live/
```

## Key Points to Emphasize

- x402 is an open standard, not proprietary
- Escrow is fully on-chain, not custodial
- Dispute resolution uses multi-sig, not single authority
- Insurance pool protects against bad actors
- SDK integrates with LangChain in 3 lines
