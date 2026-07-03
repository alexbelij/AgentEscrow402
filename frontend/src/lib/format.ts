// Casper uses "motes" as the smallest unit: 1 CSPR = 1,000,000,000 motes.
export const MOTES_PER_CSPR = 1_000_000_000;

/** Convert motes (string | number) to a human CSPR amount. */
export function motesToCspr(motes: number | string | null | undefined): number {
  if (motes == null) return 0;
  const n = typeof motes === 'string' ? Number(motes) : motes;
  if (!isFinite(n)) return 0;
  return n / MOTES_PER_CSPR;
}

/** Format motes as a friendly CSPR string, e.g. "100 CSPR". */
export function formatCspr(motes: number | string | null | undefined, digits = 2): string {
  const v = motesToCspr(motes);
  const s = v.toLocaleString(undefined, { maximumFractionDigits: digits });
  return `${s} CSPR`;
}

/** Convert a CSPR amount to integer motes. */
export function csprToMotes(cspr: number): number {
  return Math.round(cspr * MOTES_PER_CSPR);
}

/** Generate a random 64-char hex string (e.g. for a demo service_hash). */
export function randomHex64(): string {
  const bytes = new Uint8Array(32);
  (window.crypto || (window as any).msCrypto).getRandomValues(bytes);
  return Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
}
