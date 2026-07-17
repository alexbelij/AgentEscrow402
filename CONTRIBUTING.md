# Contributing to AgentEscrow402

Thanks for your interest. AE402 is under active hackathon development,
but contributions and issues are welcome.

## Ground rules

- **Don't push to `main`.** Open a pull request from a topic branch.
  `main` is protected and only merged after review.
- **One commit per logical change**, [Conventional Commits](https://www.conventionalcommits.org/):
  `fix:` / `feat:` / `docs:` / `chore:` / `ci:` / `refactor:`.
- **No secrets in commits.** Gitleaks runs on every push and PR.
  API keys, PATs, RPC private keys and mnemonics never enter the repo.
- **No breaking changes to the on-chain surface** without an explicit
  migration note in the PR.

## Repo layout

| Path | What it is | Owner |
|---|---|---|
| `contracts/` | Casper smart contracts (Rust) | Core |
| `server/` | FastAPI backend, arbitration, insurance, VRF | Core |
| `sdk/` | Python + TypeScript SDKs | Core |
| `frontend/` | React + Vite console + landing | UX |
| `tests/` | Pytest suite (`pytest -q`) | Core |
| `docs/` | Architecture, API, SDK reference | All |
| `deploy-out/` | Machine-readable deploy metadata | Core |

## Development setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- Rust stable (only if you touch `contracts/`)
- A Casper testnet secret key at `~/.casper/keys/wallet-test-key/secret_key.pem`
  (or set `CASPER_SECRET_KEY_PATH`)

### Backend

```bash
pip install -r requirements.txt
cp .env.example .env    # edit CASPER_RPC_URL, CONTRACT_HASH, keys
uvicorn server.main:app --reload
```

### Frontend

```bash
cd frontend
npm ci
npm run dev
```

### Tests

```bash
pytest -q                        # full 450-test suite
pytest tests/e2e_live_smoke.py   # live testnet smoke (requires funded key)
```

## Pull request checklist

Before opening a PR, run:

```bash
# Backend
pytest -q

# Frontend
cd frontend
npx tsc --noEmit
npm run build
```

Then:

- [ ] Branch names follow `feat/*`, `fix/*`, `docs/*`, `chore/*`, `ci/*`.
- [ ] Commit messages follow Conventional Commits.
- [ ] No changes to `contracts/` without new tests.
- [ ] No console.log / console.error in production paths — guard with
      `import.meta.env.DEV` (frontend) or Python logging (server).
- [ ] Public API changes are documented in `docs/API_SDK_MCP.md`.
- [ ] UI text is in English.
- [ ] `deploy-out/onchain.json` is updated if a new contract is deployed.

## Reporting security issues

Please do **not** open a public issue for security vulnerabilities.
Email the maintainer directly (see repo owner on GitHub) with a
description and reproduction steps.

## License

AE402 is MIT-licensed. By contributing you agree that your changes
will be released under the same license.
