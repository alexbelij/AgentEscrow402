# Submission

## Project

**AgentEscrow402** — x402-compatible payment middleware for AI agents on Casper Network

## Links

| Item | URL |
|------|-----|
| GitHub | https://github.com/alexbelij/AgentEscrow402 |
| Demo Video | _pending_ |
| Landing Page | _pending_ |
| Testnet Contract | _pending_ |
| Casper Explorer TX | _pending_ |

## Track

Agentic Infrastructure

## Team

Solo developer: alexbelij

## Summary

AgentEscrow402 enables machine-to-machine payments using the x402 HTTP payment protocol on Casper Network. AI agents can lock funds in trustless escrow smart contracts, deliver services, and release payments without human intervention. The system includes multi-sig dispute resolution (3-of-5 arbiters), on-chain reputation scoring with exponential decay, and an insurance pool funded by configurable fees.

## On-Chain Components

- `escrow.wasm` — Escrow create, release, refund, dispute, resolve, insurance pool, reputation

## Tech Stack

- Python 3.11 (FastAPI backend, SDK, tests)
- Rust (Casper smart contract)
- LangChain integration
