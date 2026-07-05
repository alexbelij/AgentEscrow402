# BUIDL Submission — AgentEscrow402

## Project Name
**AgentEscrow402**

## Tagline
HTTP 402 × Casper Network: autonomous escrow for AI-to-AI micropayments

---

## Problem It Solves

AI agents increasingly need to transact with each other — paying for compute, data, or API calls — but today there's no trustless, on-chain mechanism to do this without a human in the loop or a centralized facilitator holding funds. HTTP 402 (Payment Required) has existed in the web spec since 1996 for exactly this use case, but existing implementations assume Ethereum-based hot wallets managed by a third-party facilitator. If the paying agent doesn't trust the receiving agent, or the service is never delivered, there's no escrow, no timeout, and no dispute mechanism — funds are at risk.

---

## Solution

AgentEscrow402 deploys a Rust/WASM smart contract on Casper Network that implements a full escrow lifecycle: Agent A locks funds with a time-to-live, Agent B delivers the service, Agent A releases — all mediated by a FastAPI payment server that validates x402 headers on every HTTP request. Three capabilities distinguish it from every existing x402 implementation: time-locked on-chain escrow (if Agent B doesn't deliver, the sender auto-reclaims after TTL), per-agent reputation tracking with exponential decay stored directly in the contract, and 3-of-5 multi-sig arbiter dispute resolution with on-chain vote recording. The full stack — contract, server, console, Python SDK, LangChain tool, and MCP server — is deployed and live.

---

## Live Demo
🔗 **[ae402.xyz](https://ae402.xyz)** — live console with real escrow data on Casper Testnet

Backend API: `https://ae402-backend.onrender.com`

Contract: [`50ca3364...`](https://testnet.cspr.live/contract/50ca336428601e9920f3493112cad452c4b9359b1a88fd8893441b41c4498664)

---

## GitHub Repository
🔗 **[github.com/alexbelij/AgentEscrow402](https://github.com/alexbelij/AgentEscrow402)**

---

## Video
[Video](TBD)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Smart contract | Rust → WASM, Casper 2.x, CEP-88 events |
| Payment server | Python 3.11, FastAPI, Uvicorn |
| x402 middleware | Custom HTTP 402 header parser + validator |
| SDK | Python async SDK, LangChain tool, MCP server (7 tools) |
| Console | Next.js, Vercel |
| Backend hosting | Render |
| CI | GitHub Actions — lint, pytest, WASM build, cargo test |
| Tests | 85 Python + 18 Rust = 103 total, all passing |

---

## What Makes It Unique

**On-chain escrow, not hot wallets.** Existing x402 implementations store funds in a facilitator's hot wallet. AgentEscrow402 locks them in a time-locked Casper contract. If the service isn't delivered, the sender reclaims — no trust required.

**Reputation as infrastructure.** Every completed payment updates an on-chain trust score with exponential decay (`new = old × 0.95 + latest`). Agents can query counterparty reliability before committing funds. This is stored in the contract itself, not an off-chain database.

**3-of-5 arbiter dispute resolution.** Contested payments don't go to a single administrator — they go to a configurable arbiter pool with a multi-sig vote. The contract handles payout atomically on quorum. No human coordinator required.

**Casper-native.** Built for Casper 2.x with native WASM, CEP-88 event monitoring, and testnet deployment. Not a port or wrapper — a ground-up implementation designed for Casper's execution model.

**x402 for AI agents, not browsers.** The x402 middleware returns machine-readable 402 responses (structured JSON with price, receiver, and accepted format) that AI agent SDKs can parse and act on programmatically — no wallet pop-up, no human approval.

---

## Team

**alexbelij** — Solo builder bringing x402 to Casper Network. Designed the protocol, architected the escrow smart contract, built the payment server with 402 middleware, developed the Python SDK with LangChain and MCP integrations, and deployed the full stack end-to-end. Background in distributed systems and protocol design; focus on machine-to-machine payment infrastructure for the agentic economy.

GitHub: [github.com/alexbelij](https://github.com/alexbelij)
