# Contributing to AgentEscrow402

Thanks for your interest. Here's how to get started.

## Development setup

```bash
git clone https://github.com/alexbelij/AgentEscrow402.git
cd AgentEscrow402
pip install -r requirements.txt -r requirements-dev.txt
```

## Running tests

```bash
PYTHONPATH=. pytest tests/ -v
cd contracts/tests && cargo test
```

## Code style

- Python: formatted with `black`, linted with `ruff`
- Rust: `cargo fmt` + `cargo clippy`
- Run `ruff check server/ sdk/ tests/` and `black --check server/ sdk/ tests/` before committing

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `test:`, `docs:`, `chore:`

## Pull requests

1. Fork the repo and create a branch from `main`
2. Add tests for new functionality
3. Make sure all tests pass
4. Open a PR with a clear description

## Issues

Use GitHub Issues for bugs and feature requests. Include steps to reproduce for bugs.
