import React from 'react';
import { ExternalLink } from 'lucide-react';

/**
 * A small "View on CSPR.live" link for any Casper public key / account hash
 * shown in the console (payer, payee, agent identity, etc). These are real
 * testnet-format addresses — for seeded records they may not have on-chain
 * history yet (the explorer will just show an empty/not-found account page,
 * same as any brand-new unused Casper account), but the link is never fake:
 * it always points at the real CSPR.live testnet explorer for that exact key.
 */
const EXPLORER_BASE = 'https://testnet.cspr.live';

// A Casper public key is 66 hex chars (`01`/`02` prefix + 64-hex),
// and a bare account/contract hash is 64 hex chars. Anything shorter or
// containing non-hex characters is either a truncated display value
// (e.g. "612cea…d9ec") or noise, and doesn't route usefully to the
// explorer — we render the text plainly in that case rather than link
// to a broken page.
const HEX_ID_RE = /^[0-9a-fA-F]{64}$|^0[12][0-9a-fA-F]{64}$/;

export function isValidExplorerId(value: string): boolean {
  return typeof value === 'string' && HEX_ID_RE.test(value.trim());
}

export function explorerAccountUrl(publicKeyOrHash: string): string {
  return `${EXPLORER_BASE}/account/${publicKeyOrHash}`;
}

export function explorerSearchUrl(value: string): string {
  return `${EXPLORER_BASE}/search/${value}`;
}

const ExplorerLink: React.FC<{
  value: string;
  kind?: 'account' | 'search';
  children: React.ReactNode;
  className?: string;
  title?: string;
}> = ({ value, kind = 'account', children, className, title }) => {
  // Fallback: if the id looks malformed, render the children as plain
  // text so we never send the visitor to a broken explorer page.
  if (!isValidExplorerId(value)) {
    return (
      <span
        className={`inline-flex items-center gap-1 text-gray-400 ${className || ''}`}
        title={title || 'Invalid or truncated explorer id'}
      >
        {children}
      </span>
    );
  }

  return (
    <a
      href={kind === 'account' ? explorerAccountUrl(value) : explorerSearchUrl(value)}
      target="_blank"
      rel="noopener noreferrer"
      title={title || 'View on CSPR.live (testnet explorer)'}
      onClick={(e) => e.stopPropagation()}
      className={`inline-flex items-center gap-1 hover:text-ae-accent-bright hover:underline decoration-dotted underline-offset-2 transition-colors ${className || ''}`}
    >
      {children}
      <ExternalLink className="h-3 w-3 shrink-0 opacity-70" />
    </a>
  );
};

export default ExplorerLink;
