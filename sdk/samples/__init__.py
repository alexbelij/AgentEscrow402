"""AE402 SDK usage samples.

Each module in this package is a self-contained script that demonstrates
one specific SDK pattern. They live under `sdk/samples/` rather than
`examples/` because they are designed to be *importable* — the top-level
`examples/` scripts are user-facing recipes; these are the smallest
possible reference implementations for people writing their own agents.

Run them directly:

    python -m sdk.samples.autonomous_agent
    python -m sdk.samples.cep18_permit_flow

All samples default to the in-process sandbox (no external services)
so they always work offline. Point at a live backend via `--api-url`.
"""
