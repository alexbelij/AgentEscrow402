# AE402 — Operator Runbook

> Short by design. Anything longer than 2 pages doesn't get read at 3 AM.

## Fast checks

| Q | Where |
|---|-------|
| Is the LB probe green? | `GET /health` |
| Is the deep operator surface OK? | `GET /ops/health` |
| Which LLM providers are configured? | `/ops/health → dependencies[]` |
| What warnings are active? | `/ops/health → warnings[]` |
| How many retries pending? | `/ops/health → retries.pending` |
| Recent arbitrations? | `GET /arbitration/history?limit=20` |
| Contract hashes? | `GET /contracts` |

## Common alerts

### `no primary LLM provider configured`

Cause: none of `GROQ_API_KEY`, `NVIDIA_API_KEY`, `OPENROUTER_API_KEY` is
set.

Effect: arbitration falls back to the deterministic heuristic policy.
This is **safe** — the heuristic never abstains and produces a valid
verdict — but confidence is low and every dispute will auto-escalate to
a VRF panel.

Fix: set at least one LLM provider env var on the deploy target
(Render → Environment tab). Restart service. Confirm via `/ops/health`.

### `provider <name>: circuit breaker OPEN`

Cause: consecutive failures crossed the threshold for that provider.

Effect: this provider is skipped in the fallback chain until the
breaker half-opens and probes recover.

Fix:
- Check the provider's dashboard (rate limits, key expiry).
- If the key is fine, the provider itself is degraded — wait for
  half-open probes to succeed, or manually reset if the operator UI
  supports it.

### `db: disconnected` on `/health`

Cause: Postgres URL unreachable, credential rotation, or Neon idle.

Effect: writes fail with 5xx. Reads that hit `_arbitration_agent._history`
(in-memory) still work.

Fix:
- `DATABASE_URL` sanity: `psql "$DATABASE_URL" -c 'select 1'` from
  the operator shell.
- Rotate Neon endpoint if the branch was recreated.
- Restart service after fixing.

## Rotation checklist

When rotating **any** secret (GitHub PAT, LLM provider key, Casper
deploy key):

1. Provision the new secret first; do NOT revoke the old one yet.
2. Set the new secret in the deploy target env; trigger a redeploy.
3. Confirm `/ops/health` shows the provider still `configured=true`
   (env write took effect).
4. Confirm the next arbitration goes through the intended provider
   (`/arbitration/history[0].provider`).
5. Revoke the old secret.

Never leave an active service with a stale key + a rotated key in
parallel. The circuit breaker will flip states unpredictably.

## Deploy recovery

If a Render deploy comes up broken (usually a schema drift after a
migration):

1. Roll back to the previous known-good deploy (Render → Deploys → hover
   → "Roll back to this deploy").
2. `GET /health` and `GET /ops/health` should both be green.
3. Open a follow-up ticket with the broken deploy's build_sha (visible
   in `/ops/health → build_sha`).

## Circuit breaker semantics

Providers move through three states:

- `closed` — normal. Calls flow to this provider.
- `open` — consecutive failures crossed the threshold. Calls skip
  this provider entirely for a cooldown window.
- `half_open` — cooldown expired; a single probe call is attempted.
  Success → `closed`. Failure → back to `open` with a longer cooldown.

The state is per-provider, exposed on `/ops/health → dependencies[]`.

## Emergency freeze

The escrow contract has an `emergency_freeze` capability guarded by the
3-of-5 arbiter multisig. When to use it:

- A protocol-level bug is confirmed (funds at risk).
- Not to be used for individual disputes — those go through the normal
  dispute → arbitration → resolve flow.

Steps (requires 3 arbiter signatures):

1. Draft the freeze proposal — reference the incident ticket.
2. Circulate to arbiters via out-of-band channel (never post the
   proposal payload in a public channel; it's a signed message that
   commits on-chain).
3. Collect 3 signatures.
4. Submit the freeze deploy. Confirm on `cspr.live`.
5. Post-freeze, users see a banner + `emergency: true` on relevant
   endpoints.

## When something is genuinely stuck

- Contact: on-call rotation in `#ae402-ops` (Slack).
- Escalation: named operators in `docs/OWNERS.md` (if present) or the
  README acknowledgements section.
