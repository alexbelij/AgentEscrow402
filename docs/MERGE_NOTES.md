# Merge notes — feat/ae402-arbiter-signing-e2e (T24)

**For the merge agent.** Read this before merging or deploying.

## What this branch does

Adds a single end-to-end test file (`tests/test_arbiter_signing_e2e.py`, +383 LOC, 5 tests)
that locks the SDK-driven arbiter-signing contract:

1. Happy path: PEM → `sdk.arbiter_signing.sign_arbiter_vote` → `sdk.EscrowClient.resolve` →
   `/resolve` → `count_valid_votes` → FSM `disputed → resolved`.
2. A5 broadcast alias: `/resolve` fans out both `escrow_resolved` **and**
   `arbitration_complete` (regression guard for the AE402_AGENT_SPEC batch-2 A5 alias).
3. Forgery reject via SDK: outsider PEMs → HTTP 422.
4. Verdict-flip reject via SDK: signed-for-`receiver`, submitted-`sender` → HTTP 422.
5. Broadcast payload shape lock: `service_hash: str[64]`, `ts: int` (downstream dashboards /
   MCP / cross-repo agents can rely on this).

No production code changed. No dependency changes. No config changes.

## Render — no changes required

**Do not touch Render for this merge.** This branch is test-only:

- Zero new environment variables.
- Zero new secrets.
- Zero deploy-shape changes (routes, workers, health checks, build command).
- No migrations.
- No new external service dependencies.

If Render is set to auto-deploy on `main`, the deploy after merge is a no-op —
the running image just picks up the new test file, which is inert at runtime.

The separate SigNoz/OTel deploy runbook lives in the **T23** branch
(`feat/ae402-signoz-otel` → `docs/DEPLOY_SIGNOZ.md`). If both branches are being
merged, apply the T23 runbook once, from T23; nothing extra here.

## Pre-merge check

Run the full suite from repo root:

```
python -m pytest tests/ -q
```

Expected: `597 passed` (592 main baseline + 5 new). Any red = do not merge.

## Post-merge

Nothing to do. Merge, close PR, move on.
