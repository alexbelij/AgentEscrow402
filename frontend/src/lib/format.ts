// Casper uses "motes" as the smallest unit: 1 CSPR = 1,000,000,000 motes.
export const MOTES_PER_CSPR = 1_000_000_000;

/**
 * The hosted API expresses escrow amounts, volumes, fees and pool balances as
 * whole CSPR integers (e.g. amount=25000 means 25,000 CSPR), NOT motes.
 * Confirmed via /estimate (1000 -> net 980, fee 20 = 2%) and /stats volume.
 * So the display layer must treat the incoming value as CSPR directly.
 */
export function motesToCspr(amount: number | string | null | undefined): number {
  if (amount == null) return 0;
  const n = typeof amount === 'string' ? Number(amount) : amount;
  if (!isFinite(n)) return 0;
  return n;
}

/** Format motes as a friendly CSPR string, e.g. "100 CSPR" or "0.02 CSPR". */
export function formatCspr(motes: number | string | null | undefined, digits = 2): string {
  const v = motesToCspr(motes);
  const s = v.toLocaleString(undefined, { minimumFractionDigits: v % 1 !== 0 ? 2 : 0, maximumFractionDigits: digits });
  return `${s} CSPR`;
}

/** The API accepts amounts as whole CSPR integers, so pass them through. */
export function csprToMotes(cspr: number): number {
  return Math.round(cspr);
}

/** Generate a random 64-char hex string (e.g. for a demo service_hash). */
export function randomHex64(): string {
  const bytes = new Uint8Array(32);
  (window.crypto || (window as any).msCrypto).getRandomValues(bytes);
  return Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
}
