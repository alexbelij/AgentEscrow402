# Known Limitations

## Smart Contract

- **No reentrancy guard** — The contract relies on Casper's execution model (single-threaded per deploy) but does not implement an explicit reentrancy lock. Future upgrades should add one for defense in depth.
- **Fee underflow edge case** — When `amount * fee_bps / 10_000 > amount`, the subtraction underflows. Fixed in practice because fee_bps is admin-controlled and capped, but should use `checked_sub`.
- **Emergency freeze is one-way** — The `emergency_freeze` entry point sets a frozen flag but there is no `unfreeze` entry point. A contract upgrade is required to resume operations.
- **Arbiter set is fixed at deploy** — The 5 arbiter addresses are set during contract installation. Rotation requires redeployment.

## Backend

- **On-chain integration is partial** — `create_escrow`, `release`, and `refund` use sandbox mode by default. Testnet deployment wires these to real Casper transactions.
- **Signature verification is placeholder** — The x402 middleware parses the header but does not cryptographically verify the signature field. Production use requires ed25519 verification.
- **No rate limiting** — The FastAPI server does not implement request rate limiting.
- **Single-process only** — The global `casper_client` instance is not thread-safe for multi-worker deployments.

## General

- **No persistent storage** — Sandbox mode uses in-memory dicts. Server restart loses all state.
- **Demo video pending** — Video script is ready but recording is not yet completed.
