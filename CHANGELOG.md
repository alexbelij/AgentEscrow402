# Changelog

All notable changes to AgentEscrow402 will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.0] - 2026-06-29

### Added
- Full test suite: 85 Python tests + 18 Rust logic tests
- Security audit pass: emergency freeze, access control on `dispute()`, stored `fee_bps`
- CI pipeline with lint, Python tests, contract build & test
- `conftest.py` shared fixtures for pytest

### Fixed
- `dispute()` now enforces caller is sender or receiver
- `emergency_freeze()` flag checked on all state-changing functions
- `fee_bps` stored at creation; release/refund/resolve use stored fee
- Reputation counters use `saturating_add` to prevent overflow

### Security
- Risk score reduced from 6/10 to 2/10

## [0.2.0] - 2026-06-28

### Added
- Escrow smart contract deployed to Casper testnet
- FastAPI server with x402 payment middleware
- Sandbox escrow store with CRUD, release, refund, dispute
- Reputation scoring system
- Landing page
- Documentation: ARCHITECTURE.md, API.md, SECURITY.md

## [0.1.0] - 2026-06-28

### Added
- Initial project scaffold
