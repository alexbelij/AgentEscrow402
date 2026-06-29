# Security Policy

## Reporting a vulnerability

If you find a security issue, please report it privately via [GitHub Security Advisories](https://github.com/alexbelij/AgentEscrow402/security/advisories/new) or email aliaksandr.khrol@gmail.com.

Do **not** open a public issue for security vulnerabilities.

## Scope

This project is a hackathon prototype deployed on Casper **testnet only**. The smart contract has undergone internal security review (18 findings fixed, risk score 2/10), but has not been externally audited.

## Known limitations

- No upgrade mechanism on the deployed contract (by design for hackathon scope)
- Arbiter selection is currently manual
- Insurance pool governance is centralized

See [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) for the full list.

## Secrets

- Never commit real deployer keys
- `.env.example` contains placeholder values only
- Testnet keys are disposable; do not reuse for mainnet
