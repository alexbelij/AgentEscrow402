# AE402_STRICT rollout plan

Status as of the branch `feat/ae402-strict-mode`:

- Config + startup gate + `/health` breakdown + FastAPI exception handler:
  **shipped in this branch.**
- Guard call sites inside actual silent-fallback code paths: **staged for
  follow-up branches** — this doc lists each one so a reviewer can grep
  them and a follow-up PR can go site by site.

Why the split
-------------

Adding `strict.guard(cfg, path, reason)` inside `casper_client.put_deploy`,
`repository.py`, and the RPC fallback chain touches production request
paths. Landing them behind the same PR as the config + `/health`
plumbing would make review harder and increase blast-radius if the
guard fires in an unexpected place.

The plumbing (this branch) is safe by construction: every guard() call
site added later is inert unless `AE402_STRICT=1` is set, so shipping
the plumbing on its own is a no-op for the hosted demo and lets us wire
guards site by site with independent tests.

## Call sites to wire (in priority order)

Each entry lists the file + function, the exact silent-fallback branch,
and the `path` identifier the guard() call should use. All are grepped
from the current tree; line numbers are the point where the branch
starts.

### 1. `server/casper_client.py::CasperClient.put_deploy`

- **Fallback branch**: if `self.private_key_path` is empty or the key
  cannot be parsed, the method returns a synthesised deploy hash.
- **Guard identifier**: `casper_client.put_deploy.no_key`
- **Reason string**: `"casper_private_key_path is empty or unreadable"`

### 2. `server/casper_client.py::CasperClient.query_state`

- **Fallback branch**: if all three RPC providers (CSPR.cloud, NowNodes,
  official node) return 5xx or time out, the method returns a cached /
  synthesised value rather than raising.
- **Guard identifier**: `casper_client.query_state.all_providers_failed`
- **Reason string**: `"all three RPC providers failed after retries"`

### 3. `server/casper_client.py::CasperClient.get_deploy`

- **Fallback branch**: if the deploy hash cannot be looked up on any
  provider, the method returns an in-memory placeholder (`pending`).
- **Guard identifier**: `casper_client.get_deploy.not_found_on_chain`
- **Reason string**: `"deploy hash not found on any provider"`

### 4. `server/repository.py::PGRepository.save_escrow`

- **Fallback branch**: if the DB is disconnected, the method logs a
  warning and returns without persisting. Under strict mode this would
  mean the response says "created" but no row exists.
- **Guard identifier**: `repository.save_escrow.db_disconnected`
- **Reason string**: `"pgdb.is_connected()=False, refusing to swallow write"`

### 5. `server/repository.py::PGRepository.save_receipt`

- Same shape as save_escrow.
- **Guard identifier**: `repository.save_receipt.db_disconnected`
- **Reason string**: same.

### 6. `server/vrf_election.py::VrfElection.select_arbiters`

- **Fallback branch**: if arbiter set is empty at selection time, the
  function returns a deterministic dummy panel so demos do not crash.
- **Guard identifier**: `vrf_election.no_arbiters_available`
- **Reason string**: `"arbiter pool empty at selection time"`

### 7. Hash-mismatch branch in receipt verification

- **File**: `server/services/receipt_verifier.py`
- **Fallback branch**: if the on-chain hash of the receipt does not
  match the computed one, the current code logs and returns
  `status="unverified"`. Under strict, this must be a hard error so a
  UI never renders an unverified receipt as green.
- **Guard identifier**: `receipt_verifier.on_chain_hash_mismatch`
- **Reason string**: interpolate the two hashes so the operator can
  grep production logs.

### 8. Arbiter offline handling

- **File**: `server/services/arbiter_pool.py`
- **Fallback branch**: if `arbiter.ping()` fails but the arbiter is
  still weighted in the current epoch, the code proceeds with the
  remaining N-1. Under strict, this is a hard error until the epoch
  rolls over -- otherwise a judge can see a "unanimous" verdict that
  actually only had N-1 votes.
- **Guard identifier**: `arbiter_pool.offline_but_weighted`
- **Reason string**: `"arbiter <id> unreachable but still weighted in current epoch"`

## Testing

Every follow-up PR that adds a guard() call must ship an accompanying
integration test in `tests/test_strict_mode.py` (extend the existing
file). The pattern is: build a `Config(strict_mode=True, ...)` with the
precondition met, exercise the offending code path with an injected
failure (mock RPC 500, DB down, etc.), assert the response is 503 with
the structured body and the right `path`. See the existing
`TestExceptionHandler` class for the template.
