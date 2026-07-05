# Security Policy

## Reporting a vulnerability

If you find a security issue, please report it privately via [GitHub Security Advisories](https://github.com/alexbelij/AgentEscrow402/security/advisories/new) or email aliaksandr.khrol@gmail.com.

Do **not** open a public issue for security vulnerabilities.

## Scope

This project is a hackathon prototype deployed on Casper **testnet only**. The smart contract has undergone internal security review (18 findings fixed, risk score 2/10), but has not been externally audited.

## Known limitations

- The contract *is* upgradeable (deployed as a versioned Casper contract package — v3 through v8
  in this hackathon so far), but only the deployer account that owns the package URef can push a
  new version; there's no timelock or multi-party governance over upgrades.
- Arbiter rotation goes through a real on-chain `set_arbiters` entry point (no redeploy needed),
  but is triggered manually by an admin API call, not by any on-chain vote.
- Insurance pool governance is centralized

See [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) for the full list.

## Secrets

- Never commit real deployer keys
- `.env.example` contains placeholder values only
- Testnet keys are disposable; do not reuse for mainnet
