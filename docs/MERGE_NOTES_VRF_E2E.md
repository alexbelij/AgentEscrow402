# Merge Notes — feat/ae402-vrf-selection-e2e (T26)

**Scope: TEST-ONLY. No production code touched. No Render changes.**

## What this branch does

Adds one file — `tests/test_vrf_selection_e2e.py` — with 5 tests locking the
full VRF arbiter-selection contract through the public SDK surface:

- **Identity binding**: VRF elects by Casper `account_hash`, `/resolve`
  verifies by Ed25519 `pubkey`. This branch is the *only* test that
  exercises both identity domains in a single flow.
- **INVARIANT 5 through SDK**: dispute parties never elected, even if
  they are the only registered candidates (503 fallback locked).
- **Idempotent re-election**: second `/vrf/elect` for a dispute_id
  returns the prior result or 409, never allocates a fresh one.
- **abstain → panel escalation**: `/arbitration/analyze` with
  `sender_account+receiver_account` auto-populates `panel_election`
  when the LLM (mocked) abstains, and picks a non-party arbiter.
- **Missing party accounts → escalation_reason**: guards a silent
  regression where empty party fields would try to elect.

Test uses `httpx.ASGITransport` — no network, no external services.

## Render / deploy impact

**Zero.** This branch:

- Does not add/remove/change any environment variables
- Does not add/remove/change any secrets
- Does not modify any deploy configuration
- Does not touch `render.yaml`, `Dockerfile`, `requirements.txt`, or
  `pyproject.toml`
- Does not touch `server/` code — only adds one file under `tests/`

**Do not touch Render.** If Render is configured to auto-deploy on merge
to `main`, the resulting deploy is a no-op — same image, same env, same
routes.

The SigNoz OTEL runbook and Render env-var changes are unrelated and
live in a separate branch (`feat/ae402-signoz-otel`).

## Independence from other open PRs

This branch is fully independent of:

- `feat/ae402-signoz-otel` (T22+T23) — touches different files
  (`docs/DEPLOY_SIGNOZ.md`, `server/telemetry.py`)
- `feat/ae402-arbiter-signing-e2e` (T24) — different test file
  (`tests/test_arbiter_signing_e2e.py`)
- `feat/ae402-formal-verification` (T25) — Rust contract tests
  (`contracts/tests/src/fsm_property_tests.rs`)

No merge-order dependency. Any order works.

## Pre-merge verification

Only Python tests were touched:

```
cd /data/AgentEscrow402
python -m pytest tests/ -q
# expected: 597 passed
```

If a downstream branch also adds Python tests, add them together —
the total should be `592 baseline + 5 (this branch) + N (other) = 597 + N`.
