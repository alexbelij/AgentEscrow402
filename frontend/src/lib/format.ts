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

/**
 * Threshold used to detect legacy demo rows that were seeded in whole CSPR
 * before the unit contract was enforced. Any incoming `motes` value below
 * this bound is treated as a legacy CSPR figure and up-scaled by 1e9 at
 * the display boundary. Rationale: 1e6 motes = 0.001 CSPR — no realistic
 * on-chain escrow would ever be denominated below that, so a bare `98`
 * or `25000` is unambiguously legacy. Applied only in the *read* path;
 * writes always go through `csprToMotes()` and cannot be legacy-scaled.
 */
export const LEGACY_CSPR_HEURISTIC_MAX = 1_000_000;

/** Convert a motes value (bigint-safe integer) to CSPR (float). */
export function motesToCspr(amount: number | string | null | undefined): number {
  if (amount == null) return 0;
  const n = typeof amount === 'string' ? Number(amount) : amount;
  if (!isFinite(n) || n < 0) return 0;
  // Legacy demo rows: seeded in whole CSPR before the unit contract was
  // enforced. Treat implausibly small "motes" values as CSPR passthroughs
  // instead of rendering them as microscopic fractions.
  if (n > 0 && n < LEGACY_CSPR_HEURISTIC_MAX) {
    return n;
  }
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
