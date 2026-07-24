# CSPR / motes unit contract

**Owner:** hackathon team, 2026-07-20  
**Status:** enforced end-to-end (API ↔ contract ↔ DB ↔ UI)  
**Test enforcement:** `tests/test_cspr_motes_unit_contract.py` — 6 tests, must stay green.

## The rule

**1 CSPR = 1,000,000,000 motes (1e9).**

Every place in this codebase that stores, aggregates, or transports a
value across the API surface uses **motes as an integer**. The only two
places that convert between motes and CSPR are:

1. `frontend/src/lib/format.ts::motesToCspr()` — read boundary (motes → CSPR float, for display).
2. `frontend/src/lib/format.ts::csprToMotes()` — write boundary (user CSPR input → motes int, for the wire).

Any other layer must not convert.

## What "in motes" applies to

Every `amount`, `net_amount`, `gross_amount`, `insurance_fee`, `fee`,
`premium_amount`, `total_volume`, `total_volume_motes`,
`total_deposited`, `total_claims_paid`, `available_funds`,
`escrow_amount`, `stake`, `release_cap_motes`, `new_cap_motes` field in
the API, models, sandbox store, contracts, and OpenAPI schema is in
**motes (integer)**.

If a new endpoint accepts or returns a monetary value and the docstring
does not say "motes" explicitly, it is a bug — fix the docstring **and**
add a case to `tests/test_cspr_motes_unit_contract.py`.

## History (why this exists)

Commit `65145bd` treated a display bug as a display-only issue and
replaced the real math in `format.ts` with identity functions:

```ts
// BEFORE (65145bd — WRONG):
export function motesToCspr(amount) { return amount; }
export function csprToMotes(cspr)   { return Math.round(cspr); }
```

That silently redefined the frontend's meaning of "motes" to be "whole
CSPR" while the backend, contracts, and every OpenAPI/SDK docstring kept
saying motes. The invariant "a value round-trips unchanged through
API → contract → DB → UI" was broken: the same integer now meant two
different amounts of money depending on which side of the boundary you
were on.

## The fix (2026-07-20)

- Restored the real math in `format.ts`.
- Migrated `server/seed.py` to seed real motes values (`_cspr(25000)`
  reads as "25,000 CSPR" but stores `25_000_000_000_000` motes).
- Removed the legacy magnitude heuristic. A valid on-chain value can be one
  mote, so inferring “whole CSPR” from a small integer can create a
  billion-fold display error. Historic demo data must be migrated at its
  source; the read boundary always divides motes by `1e9`.
- Added `tests/test_cspr_motes_unit_contract.py`, 6 tests that lock in:
  - `create_escrow` splits gross into net+fee in motes with no unit hop;
  - `/estimate` is scale-invariant and linear;
  - `/stats.total_volume` aggregates net motes across many escrows;
  - `motes → CSPR → motes` round-trip is the identity function.

## Adding a new monetary field — checklist

1. Declare it in the Pydantic model as `int` with `description="Amount in motes"`.
2. If the frontend renders it: pass it through `formatCspr()` — never
   arithmetic on the raw number before display.
3. If the frontend collects it from the user: pass it through
   `csprToMotes()` before sending. Do not send `Number(input)` directly.
4. Add one row to `tests/test_cspr_motes_unit_contract.py`.
5. Update this document if the new field has a suffix convention
   (`_motes`, `_cspr`) different from the default.
