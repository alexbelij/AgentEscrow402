# Submission

## Project

**AgentEscrow402** — x402-compatible payment middleware for AI agents on Casper Network

## Links

| Item | URL |
|------|-----|
| GitHub | https://github.com/alexbelij/AgentEscrow402 |
| Landing Page | https://ae402.xyz |
| Dashboard | https://ae402.xyz/dashboard |
| Backend API | https://agentescrow402-api.onrender.com |
| Testnet Contract | [5dd33e8e...134451](https://testnet.cspr.live/contract/5dd33e8e79789d386832a80c39006002383fa44dd76ba677cae3279f3a134451) |
| Demo Video | _TBD_ |

## Track

Agentic Infrastructure

## Team

Solo developer: alexbelij

## Summary

AgentEscrow402 enables machine-to-machine payments using the x402 HTTP payment protocol on Casper Network. AI agents can lock funds in trustless escrow smart contracts, deliver services, and release payments — no human in the loop. Features multi-sig dispute resolution (3-of-5 arbiters), on-chain reputation scoring with exponential decay, and an insurance pool funded by configurable fees.

## On-Chain Components

- `escrow.wasm` — Escrow create, release, refund, dispute, resolve + insurance pool + reputation tracking
- Contract hash: `5dd33e8e79789d386832a80c39006002383fa44dd76ba677cae3279f3a134451`

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, uvicorn |
| Smart Contract | Rust, casper-contract, CEP-88 events |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS |
| Database | PostgreSQL (Neon) |
| Hosting | Vercel (frontend), Render (API) |
| Tests | pytest (85 Python) + cargo test (18 Rust) |
| CI/CD | GitHub Actions |

## Hackathon Requirements Checklist

- [x] Original work built for this hackathon
- [x] Open-source code on GitHub
- [x] Working prototype on Casper testnet
- [x] On-chain transaction(s) — escrow create/release/dispute
- [x] Public GitHub repository with README
- [x] Demo video — _TBD_
