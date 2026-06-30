# HTTP 402 is Alive: How AgentEscrow402 Enables AI Agent Micropayments on Casper

*By alexbelij · Casper Agentic Buildathon 2026*

---

The year is 2026 and AI agents are everywhere — writing code, querying APIs, generating reports, running inference pipelines. The inevitable next step: agents paying other agents for compute, in real time, with no human in the loop.

HTTP 402 was designed for exactly this. It's been sitting in the web spec since 1996, marked "reserved for future use." That future is now.

---

## The Problem: x402 Needs Trustless Escrow

The x402 protocol, popularized recently by Coinbase, defines how machines can pay for API calls using HTTP payment headers. An AI agent hits a paid endpoint, includes a signed payment header, and gets the result. Clean, machine-native, no wallet pop-up.

But there's a catch: current x402 implementations require a **centralized facilitator** holding funds in a hot wallet. If you're Agent A paying Agent B:

- Who holds the funds between request and delivery?
- What if Agent B takes the money and never delivers?
- What if Agent A disputes the result?

With a facilitator, you've replaced one centralized dependency (a bank) with another (a startup's infrastructure). That's not trustless. That's not agentic.

---

## The Solution: On-Chain Escrow on Casper Network

**AgentEscrow402** solves this with a Rust/WASM smart contract deployed on Casper Testnet that implements a full escrow lifecycle — no facilitator required.

Here's the flow:

1. **Agent A creates an escrow** — locks 5 CSPR in a time-locked contract with a 5-minute TTL
2. **Agent B checks on-chain** — verifies funds are locked before doing any work
3. **Agent A hits the protected endpoint** — includes the x402 payment header; the server validates it against the contract
4. **After delivery, Agent A releases** — one API call; funds transfer atomically to Agent B; reputation score updates on-chain

If Agent B never delivers? Agent A calls `/refund` after TTL. Funds return. No dispute needed. No administrator to call.

```bash
# Create an escrow in one curl
curl -X POST https://ae402-backend.onrender.com/escrow \
  -H "Content-Type: application/json" \
  -d '{"sender":"agent-A","receiver":"agent-B","amount":5000000,"ttl":300}'

# Response:
{"service_hash":"abc123...","status":"locked","expires_at":1751320000}
```

---

## Demo Walkthrough

Land on **[ae402.xyz](https://ae402.xyz)** and you'll see the live dashboard: a table of escrows with status badges (Locked, Released, Disputed), a real-time event feed, and links to verified Casper Testnet transactions.

The contract is not a demo — it's deployed:
[`5dd33e8e...` on testnet.cspr.live](https://testnet.cspr.live/contract/5dd33e8e79789d386832a80c39006002383fa44dd76ba677cae3279f3a134451)

Every escrow you create from the dashboard triggers a real on-chain transaction you can verify independently.

---

## Technical Deep Dive

### Three Capabilities That Don't Exist Elsewhere

**1. Time-locked on-chain escrow**

Funds live in a Casper WASM contract, not a hot wallet. The `create_escrow` entry point accepts a TTL parameter. After expiry, `refund` becomes callable by the sender — no permission needed, no admin. The contract enforces it.

**2. Reputation with exponential decay**

Every completed payment updates an on-chain trust score:

```
new_score = old_score × 0.95 + latest_delivery_score
```

This score is stored in the contract's named keys — readable by any agent before committing funds. A bad actor's score decays slowly toward zero as their history accumulates. A good actor's score converges toward 1.0.

**3. 3-of-5 arbiter dispute resolution**

Contested payments don't escalate to a single administrator. They go to a configurable arbiter pool. The `dispute` entry point opens a vote; `resolve` records each arbiter's decision. On quorum, the contract executes the payout atomically — release to receiver or refund to sender. No human coordinator, no off-chain coordination.

### The x402 Middleware

The FastAPI payment server wraps every protected endpoint with middleware that:
- Parses `X-Payment: x402-v1;<escrow_hash>;<amount>;<sender>;<signature>` headers
- Validates the signature and checks on-chain escrow status
- Returns a structured 402 response when the header is missing — machine-readable, not an HTML error page

```json
{
  "error": "payment_required",
  "accepts": "x402-v1",
  "price": 1000000,
  "receiver": "account-hash-74c9..."
}
```

An AI agent SDK can parse this, create an escrow, retry the request, and handle the result — all programmatically.

### Stack

- **Smart contract:** Rust → WASM, Casper 2.x, CEP-88 event standard
- **Server:** Python 3.11, FastAPI, 85 passing tests
- **Contract tests:** 18 Rust integration tests
- **SDK:** Python async client, LangChain tool, MCP server (7 tools)
- **Dashboard:** Next.js on Vercel

---

## What's Next

The escrow primitive is live and tested. The next layer is agent discovery — a registry where agents publish their capabilities, pricing, and reputation scores, and other agents can query and transact autonomously. That turns AgentEscrow402 from a payment tool into a coordination layer for the agentic economy.

---

## Build On It

The code is open source: **[github.com/alexbelij/AgentEscrow402](https://github.com/alexbelij/AgentEscrow402)**

The backend is live: `https://ae402-backend.onrender.com`

If you're building AI agents that need to transact — fork it, extend it, or just use the API. HTTP 402 is alive. Let's build the agentic economy on top of it.

---

*Built for the Casper Agentic Buildathon 2026. Live at [ae402.xyz](https://ae402.xyz).*
