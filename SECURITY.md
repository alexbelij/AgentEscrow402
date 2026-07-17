# Security

## Reporting Vulnerabilities

If you find a security issue, email **security@ae402.xyz** or open a
[GitHub Security Advisory](https://github.com/alexbelij/AgentEscrow402/security/advisories/new).
Do **not** open a public issue. We aim to acknowledge reports within 48 hours.

## Self-Audit Summary

Last reviewed: 2026-07-17 (pre-submission audit)

### Smart Contracts (Rust → Wasm, Casper Testnet)

| Contract | Checked Arithmetic | Access Control | Reentrancy | Status |
|---|:---:|:---:|:---:|---|
| escrow v9 | ✅ | ✅ caller_key guard | N/A (no callbacks) | Deployed |
| escrow-manager | ✅ | ✅ admin-only batch ops | N/A | Deployed |
| insurance-pool | ✅ | ✅ arbiter quorum 3-of-5 | N/A | Deployed |
| vrf-arbiter | ✅ | ✅ admin seeding | N/A | Deployed |
| agent-identity-registry | ✅ | ✅ self-register only | N/A | Deployed |
| multi-asset-escrow | ✅ checked_deduct_fee | ✅ multi-sig verify | N/A | Deployed |
| test-token (AETUSD) | ✅ checked_add/sub | ✅ CEP-18 standard | N/A | Deployed |
| test-token (AEMAT) | ✅ checked_add/sub | ✅ custody get_immediate_caller | N/A | Deployed |

### Backend (Python / FastAPI)

| Category | Control | Status |
|---|---|---|
| Rate limiting | 60 req/min/IP via in-memory sliding window | ✅ |
| Authentication | x402 Ed25519 + secp256k1 signature verification | ✅ |
| Replay protection | Nonce + timestamp window (5 min) | ✅ |
| Input validation | Pydantic models on all endpoints | ✅ |
| SQL injection | Parameterized queries via SQLAlchemy/psycopg | ✅ |
| Secret management | Env vars only, never logged or returned in API | ✅ |
| CORS | Restricted to known origins | ✅ |
| Dependency scanning | Dependabot + TruffleHog secret scanner | ✅ |

### Known Limitations

| # | Issue | Severity | Mitigation |
|---|---|---|---|
| L-1 | Nonce cache is in-memory, not Redis | Low | Acceptable for testnet; production should use Redis |
| L-2 | Rate limiter is per-process, not distributed | Low | Single Render instance; production needs shared store |
| L-3 | AI arbitration uses external LLM API | Info | Deterministic rubric scoring supplements LLM verdict |
| L-4 | HTLC atomic swap contract not deployed | Info | Code complete, deployment planned for mainnet |

### Threat Model

**Agent cannot unilaterally withdraw funds.** The escrow contract enforces:
1. Creator deposit locks funds in contract purse
2. Release requires buyer confirmation OR arbiter quorum (3-of-5)
3. Refund requires seller confirmation OR timeout expiry
4. Insurance pool withdrawals require arbiter quorum consensus
5. No admin backdoor — deployer has no special withdrawal rights

This is a structural guarantee: even a compromised backend cannot extract
locked funds without the corresponding on-chain signatures.

### CI Security Pipeline

- **TruffleHog**: scans every push + PR for leaked secrets (weekly cron)
- **Dependabot**: automated dependency updates for Python and npm
- **pytest**: 490 tests including Hypothesis property-based fuzzing
- **cargo test**: 40 contract unit tests with proptest
