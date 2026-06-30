# AgentEscrow402 — BUIDL Submission

## Form Fields

| Field | Value |
|-------|-------|
| **BUIDL name** | AgentEscrow402 |
| **Logo** | Purple shield with "402" overlay |
| **Category** | crypto/web3 |
| **GitHub** | https://github.com/alexbelij/AgentEscrow402 |
| **Website** | https://ae402.xyz |
| **Demo video** | _(pending)_ |
| **Social** | GitHub: https://github.com/alexbelij |

---

## Vision (short)

Machine-to-machine payments on Casper. Agents lock funds in on-chain escrow, deliver services, release payments. No wallets, no humans, no trust assumptions.

## BUIDL Details

### What's broken

AI agents can call APIs. They can parse responses. They can chain tools. What they can't do is pay.

HTTP 402 — Payment Required — has existed since 1999. Twenty-seven years and no one built a proper implementation. Stripe doesn't help here. PayPal doesn't help here. Both require human identity, KYC, bank accounts. An autonomous agent has none of that.

The current workaround: pre-funded API keys with rate limits. That's not commerce. That's an allowance.

### What AgentEscrow402 does

AgentEscrow402 implements x402-compatible payment middleware on Casper Network. The flow:

1. Agent A calls Agent B's API endpoint
2. Agent B responds with HTTP 402 + payment terms (amount, TTL, contract address)
3. Agent A creates an on-chain escrow with the specified parameters
4. Agent B verifies the escrow on-chain, delivers the service
5. Agent A confirms delivery, escrow releases funds to B
6. If delivery fails, Agent A files a dispute resolved by 3-of-5 arbiter multisig

No custodians. No intermediaries. Fully on-chain settlement.

### Why Casper

Casper's account model and predictable gas costs make it practical for programmatic agents. Fixed-cost deploys mean an agent can budget accurately — no gas auctions, no surprise fees. The contract stores escrow state, reputation scores, and insurance pool balances in named keys with dictionary lookups, so state access is O(1).

### Technical depth

**Smart contract** (Rust, 168KB wasm):
- 6 entry points: create, release, refund, dispute, resolve, claim_insurance
- Reputation: `score = max(0, 50 + completed*5 - disputed*10)`, decays toward 50 when idle
- Insurance pool: configurable basis points (default 200 = 2%), deducted from release amount
- CEP-88 events for indexers and off-chain listeners

**Backend** (Python 3.11, FastAPI):
- `/escrows` — CRUD with pagination, status filtering
- `/agents` — reputation leaderboard
- `/stats` — aggregate metrics (total, pending, released, disputed, volume)
- `@require_payment` decorator wraps any endpoint with 402 flow
- PostgreSQL persistence (Neon), connection pooling (psycopg_pool)

**SDK**:
- `EscrowClient` — 9 methods covering full lifecycle
- `EscrowPaymentTool` — LangChain-compatible tool class
- MCP server — 7 tools exposed via stdio/SSE transport

**Frontend** (React, TypeScript, Vite, Tailwind):
- Dashboard with 3 tabs: Escrows, Agents, Operations
- Wallet connect (Casper Wallet / Signer)
- Real-time stats from API
- Direct contract interaction for create/release/dispute

**Testing**: 103 total (85 pytest + 18 cargo test). CI runs on every push.

### Deployed

- Contract: `5dd33e8e79789d386832a80c39006002383fa44dd76ba677cae3279f3a134451` on casper-test
- API: agentescrow402-api.onrender.com
- Frontend: ae402.xyz
- Database: PostgreSQL on Neon (50 escrows, 16 agents, insurance records)

### What's different

Other escrow projects on Casper handle human-to-human payments. This handles machine-to-machine. The x402 flow is the key differentiator — agents negotiate and settle payments autonomously using HTTP semantics they already understand. No new protocol to learn, no wallet extension to install. An HTTP header and a deploy hash.

Dispute resolution isn't single-authority. It's 3-of-5 multisig with on-chain arbiter staking. Bad arbiters lose their stake. Good ones earn fees.

The insurance pool isn't just marketing. Every released escrow pays into it. Claims are processed through the same multisig mechanism.

### What's next

Multi-token support, batch escrow creation, cross-chain bridges. But the core protocol — HTTP 402 → escrow → release — works today.
