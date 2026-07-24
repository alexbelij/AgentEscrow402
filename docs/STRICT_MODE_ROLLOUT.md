# AE402_STRICT rollout plan

Status (updated after an audit against the current tree — the original plan
below was written against an earlier refactor and named files/methods that
no longer exist; see "Audit note" at the bottom):

- Config + startup gate + `/health` breakdown + FastAPI exception handler:
  **shipped**.
- Startup preconditions now also check `casper_private_key_path` (previously
  missing): a strict-mode app with `casper_node_url`/`contract_hash` set and
  `sandbox=false` but no private key used to pass
  `require_strict_preconditions()` at startup, yet `server/app.py` only
  constructs a live `CasperClient` when all three of `sandbox=false`,
  `casper_node_url`, and `casper_private_key_path` are set — so it would
  still silently fall through to the in-memory `SandboxStore` on every
  request. **Fixed.**
- `server/vrf_election.py::elect_arbiter`'s on-chain-VRF-fails →
  local-CSPRNG-fallback path now raises `StrictModeError` under
  `AE402_STRICT=1` when the on-chain election genuinely could not complete
  (RPC exception, timeout, on-chain revert) — see `_OnchainVrfUnavailable`.
  It intentionally does **not** raise when every on-chain candidate happens
  to be an excluded dispute party (INVARIANT 5): that is a legitimate
  business outcome of a successful on-chain call, not a failure, and this
  fallback is by design since the contract itself has no notion of dispute
  parties. **Fixed and tested**
  (`tests/test_strict_mode.py::TestVrfElectionGuard`).
- Remaining silent-fallback branches in the write/read path (CasperClient
  RPC retries, DB-disconnected writes): **not yet wired** — see "Remaining
  work" below with corrected file/line references.

## Audit note (why this doc changed)

The original version of this doc (written against branch
`feat/ae402-strict-mode`) listed 8 call sites in files that do not exist in
the current tree: `CasperClient.put_deploy` / `.query_state` / `.get_deploy`
(no methods with these names exist — the current `_rpc()` helper already
raises `RuntimeError` on exhausting the RPC fallback chain rather than
returning a synthesised value), `server/repository.py`,
`server/services/receipt_verifier.py`, and `server/services/arbiter_pool.py`
(none of these files exist). Re-auditing against the actual current code
before wiring guards against a stale plan avoids introducing dead
`strict.guard()` calls that never fire, or claiming coverage the code
doesn't have.

- **`server/db.py::save_escrow`** returns `False` (does not raise) when
  Postgres is unreachable — a real silent-fallback branch matching the
  original doc's `repository.py` item, just relocated. All 4
  `pgdb.save_escrow(...)` call sites in `server/app.py`
  (`create_escrow`'s sandbox and live-write branches, `create_escrow_batch`'s
  same two branches) now guard on a `False` return under
  `AE402_STRICT=1`. **Fixed.**

## Remaining work (re-audited against current tree)

1. **`server/casper_client.py::CasperClient._run_node_script`** — currently
   raises `RuntimeError` on a failed Node.js tx script (no silent
   fallback), so no guard is needed here today. If a future change adds a
   "return a placeholder hash on script failure" branch, it must get a
   `strict.guard()` call and a test at that time.
2. **`server/casper_client.py::CasperClient._rpc`** — currently raises after
   exhausting the fallback chain (no silent fallback). Same note as above.
3. **`server/db.py::update_escrow_status`** — same silent-`False`-return
   shape as `save_escrow`, called from `server/app.py` at the release,
   dispute, cancel, and resolve endpoints (grep `pgdb.update_escrow_status`
   for the current line numbers). Not yet guarded — needs the same
   `if not pgdb.update_escrow_status(...): strict.guard(...)` treatment at
   each site plus a `tests/test_strict_mode.py` case per site, following
   the pattern used for `save_escrow`.

## Testing

Every follow-up PR that adds a `guard()` call must ship an accompanying
integration test in `tests/test_strict_mode.py` (extend the existing
file). The pattern: build a `Config(strict_mode=True, ...)` with the
precondition met, exercise the offending code path with an injected
failure (mock RPC exception, DB down, etc.), assert the response is a 503
with the structured body and the right `path`. See
`TestExceptionHandler` and `TestVrfElectionGuard` for templates.
