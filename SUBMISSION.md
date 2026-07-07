# Submission

## Project

**AgentEscrow402** — x402-compatible payment middleware for AI agents on Casper Network

## Links

| Item | URL |
|------|-----|
| GitHub | https://github.com/alexbelij/AgentEscrow402 |
| Landing Page | https://ae402.xyz |
| Console | https://ae402.xyz/console |
| Backend API | https://agentescrow402-api.onrender.com |
| Testnet Contract | [612cead2...ddd9ec](https://testnet.cspr.live/contract/612cead2226329fafec492042fd96a999df06d1e88c476913a167f44d3ddd9ec) |
| Demo Video | _TBD_ |

## Track

Agentic Infrastructure

## Team

Solo developer: alexbelij

## Summary

AgentEscrow402 enables machine-to-machine payments using the x402 HTTP payment protocol on Casper Network. AI agents can lock funds in trustless escrow smart contracts, deliver services, and release payments — no human in the loop. The platform features 8 deployed smart contracts, multi-sig dispute resolution (3-of-5 arbiters), VRF-based arbiter election, on-chain reputation scoring with exponential decay, multi-asset escrow (CSPR/CEP-18/CEP-78), HTLC atomic swaps, streaming payments, ML risk scoring, post-quantum metadata encryption, and an insurance pool funded by configurable fees.

## On-Chain Components

8 smart contracts deployed on Casper Testnet:

- **Core Escrow** (v9) — create, release, refund, dispute, resolve + insurance pool + reputation
- **Escrow Manager** — batch create/release/cancel
- **Insurance Pool** — premium collection, claims
- **VRF Arbiter** — on-chain random arbiter election (4 registered arbiters)
- **Agent Identity Registry** (v2) — DID registration, staking, reputation
- **MultiAssetEscrow** — CEP-18 token contract-custody escrow
- **AETUSD / AEMAT** — CEP-18 test tokens for multi-asset demo

349 real testnet transactions as on-chain evidence (173 create, 166 release, 4 refund, 3 full dispute→resolve cycles).

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, uvicorn — 62 API endpoints |
| Smart Contracts | 8× Rust → WASM, Casper 2.x, CEP-88 events |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS — 12 console tabs |
| Database | PostgreSQL (Neon serverless) |
| Hosting | Vercel (frontend), Render (API) |
| SDK | Python async SDK, LangChain tool, MCP server (26 tools) |
| Tests | pytest (450 Python) + cargo test (40 Rust) = 490 total |
| CI/CD | GitHub Actions |

## Hackathon Requirements Checklist

- [x] Original work built for this hackathon
- [x] Open-source code on GitHub
- [x] Working prototype on Casper testnet
- [x] On-chain transaction(s) — 349 verified (escrow create/release/refund/dispute/resolve)
- [x] Public GitHub repository with README
- [x] Demo video — _TBD_
