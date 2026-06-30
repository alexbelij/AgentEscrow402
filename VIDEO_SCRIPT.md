# VIDEO_SCRIPT.md — AgentEscrow402
## "AI agents paying each other on-chain — HTTP 402 meets Casper Network"
**Format:** Faceless tutorial · 2 min · English
**Target:** DeFi developers, AI builders, Web3 hackathon watchers

---

## HOOK VARIANTS (First 15 seconds — pick one)

### Hook A — Problem Statement
> [B-ROLL: Fast montage — terminal, spinning blockchain icon, dollar sign flying between server icons]

[NARRATION: "What happens when an AI agent needs to pay another AI agent — in real-time, with zero human involvement? HTTP 402 was literally invented for this. But nobody built it right. Until now."]

---

### Hook B — Demo First
> [SHOW: Browser opening ae402.xyz — dashboard loads with live escrow rows, green "Active" badges]

[NARRATION: "This is a live escrow dashboard where AI agents lock and release real funds on Casper Network. Fully autonomous. No wallet pop-up. No human approval. Let me show you how it works in under two minutes."]

---

### Hook C — Provocation
> [B-ROLL: Old "402 Payment Required" error page flashing on screen]

[NARRATION: "HTTP 402 — Payment Required — has been sitting in the spec since 1996, marked 'reserved for future use.' We decided the future is now. This is AgentEscrow402."]

---

## MAIN BODY

---

### SEGMENT 1: The Problem (0:15 – 0:35)

> [B-ROLL: Diagram — Agent A → API → Agent B, with a question mark and broken chain]

[NARRATION: "When AI agents interact with paid APIs today, they rely on centralized facilitators holding funds in hot wallets. No escrow. No timeout protection. No dispute resolution. If Agent B ghosts you, your funds are gone."]

> [SHOW: Slide text: "Current x402 = Ethereum + centralized facilitator"]

[NARRATION: "Existing x402 implementations, including Coinbase's, only run on EVM chains and still require a facilitator to hold funds. That's not trustless. That's not agentic."]

---

### RE-HOOK at 0:35
> [SHOW: Terminal — curl command firing, then "201 Created" response with service_hash]

[NARRATION: "Here's what creating an escrow looks like from a single curl command — and here's the on-chain proof."]

---

### SEGMENT 2: The Solution — Live Demo (0:35 – 1:15)

> [SHOW: ae402.xyz homepage — hero section with tagline visible]

[NARRATION: "AgentEscrow402 is deployed on Casper Testnet. The contract is live. The dashboard is live. Let's walk through the full flow."]

> [SHOW: Terminal window]

[NARRATION: "Step one — create an escrow. Agent A locks 5 CSPR into a time-locked contract."]

```
[SHOW: typing and output]
curl -X POST https://ae402-backend.onrender.com/escrow \
  -H "Content-Type: application/json" \
  -d '{"sender":"agent-A","receiver":"agent-B","amount":5000000,"ttl":300}'
```

> [SHOW: JSON response appearing with service_hash field highlighted]

[NARRATION: "You get back a service hash — the unique key for this payment. Funds are locked. Agent B can verify this on-chain before doing any work."]

> [SHOW: ae402.xyz dashboard — new escrow row appears with "Locked" status badge]

[NARRATION: "Step two — the protected API endpoint. Agent B serves compute behind an x402 header. Agent A hits it, includes the payment header, and gets the result."]

> [SHOW: Terminal — GET request with X-Payment header]

[NARRATION: "Step three — Agent A releases the escrow after confirming delivery. One POST call. Funds go to Agent B. Reputation score updates on-chain instantly."]

> [SHOW: testnet.cspr.live deploy page — transaction confirmed]

[NARRATION: "And here it is on-chain. A verified Casper testnet transaction. No facilitator. No human. Just two agents settling a payment autonomously."]

---

### RE-HOOK at 1:15
> [B-ROLL: Code editor showing the three key features side-by-side]

[NARRATION: "Three things no other x402 implementation has."]

---

### SEGMENT 3: What Makes It Unique (1:15 – 1:45)

> [SHOW: Architecture Mermaid diagram animating — Agent A → x402 Middleware → Escrow Contract → Agent B]

[NARRATION: "First — on-chain escrow with TTL. If Agent B never delivers, Agent A calls refund after the timeout. Funds return automatically. No arbitration needed for the happy path."]

> [SHOW: Code snippet — reputation formula `new = old × 0.95 + latest`]

[NARRATION: "Second — reputation tracking. Every completed payment updates an exponential-decay trust score stored directly in the contract. Agents can look up counterparty reliability before committing funds."]

> [SHOW: Dashboard dispute panel — FOR/AGAINST vote buttons]

[NARRATION: "Third — 3-of-5 arbiter dispute resolution. No single point of failure. Contested payments go to a multi-sig vote. The contract handles payout automatically based on the result."]

---

### SEGMENT 4: Stack & CTA (1:45 – 2:00)

> [SHOW: GitHub repo page — alexbelij/AgentEscrow402 with stars visible]

[NARRATION: "Built with Python FastAPI, a Rust WASM smart contract on Casper, LangChain integration, and an MCP server exposing 7 tools. 103 tests passing. Contract audited."]

> [SHOW: ae402.xyz — full page scroll]

[NARRATION: "The live demo is at ae402.xyz. The code is open source on GitHub. If you're building AI agents that need to transact — drop a star, fork the repo, and build on top of it."]

> [B-ROLL: Logo animation + URL lower-third]

[NARRATION: "AgentEscrow402. HTTP 402 is alive."]

---

## END CARD
> [SHOW: Static frame — ae402.xyz · github.com/alexbelij/AgentEscrow402 · #CasperBuildathon]

**Duration target:** 1:55–2:05
**Voice tone:** Calm, technical, confident. Not hype. Evidence-first.
**Music bed:** Lo-fi electronic, neutral energy, ducked under narration by 18dB.
