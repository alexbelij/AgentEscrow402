// Casper unit contract:
//   1 CSPR = 1,000,000,000 motes (1e9).
//
// This module is the frontend's single conversion boundary between the
// on-chain / API unit (motes, integer) and the human-facing unit (CSPR).
//
// Contract with the backend (server/models.py::CreateEscrowRequest, /estimate,
// /stats, /insurance, /arbitration, etc.): every `amount`, `net_amount`,
// `gross_amount`, `fee`, `premium_amount`, `total_volume`,
// `total_deposited`, `total_claims_paid`, `available_funds`,
// `escrow_amount`, `total_volume_motes`, `stake` field is expressed in
// **motes** (integer). The frontend must never pass a raw CSPR value into
// those fields, and never render a motes value without converting to CSPR
// first.
//
// Historical note (2026-07-20): a prior commit (65145bd) mis-classified
// this as a display-only issue and replaced `× 1e9` / `÷ 1e9` with an
// identity pass-through, which silently redefined "motes" to mean
// "whole CSPR" in the UI while the backend, contracts and OpenAPI kept
// documenting motes. This broke the invariant that a value round-trips
// unchanged through API → contract → DB → UI. The math below restores
// the real conversion. See docs/CSPR_UNITS.md for the full spec.

export const MOTES_PER_CSPR = 1_000_000_000;

/** Convert a motes value to CSPR at the human-display boundary.
 *
 * Every API and on-chain integer is motes, including a valid value of one.
 * Do not infer a legacy unit from magnitude: a heuristic would display one
 * real mote as one CSPR (a billion-fold error). Historic demo data must be
 * migrated at its source, never silently reinterpreted at read time.
 */
export function motesToCspr(amount: number | string | null | undefined): number {
  if (amount == null) return 0;
  const n = typeof amount === 'string' ? Number(amount) : amount;
  if (!isFinite(n) || n < 0) return 0;
  return n / MOTES_PER_CSPR;
}

/** Format a motes value as a friendly CSPR string, e.g. "1 CSPR", "0.02 CSPR". */
export function formatCspr(motes: number | string | null | undefined, digits = 2): string {
  const v = motesToCspr(motes);
  const s = v.toLocaleString(undefined, {
    minimumFractionDigits: v % 1 !== 0 ? 2 : 0,
    maximumFractionDigits: digits,
  });
  return `${s} CSPR`;
}

/** Convert a human CSPR value (float from an input field) to integer motes. */
export function csprToMotes(cspr: number): number {
  if (!isFinite(cspr) || cspr < 0) return 0;
  return Math.round(cspr * MOTES_PER_CSPR);
}

/** Generate a random 64-char hex string (e.g. for a demo service_hash). */
export function randomHex64(): string {
  const bytes = new Uint8Array(32);
  (window.crypto || (window as any).msCrypto).getRandomValues(bytes);
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}
