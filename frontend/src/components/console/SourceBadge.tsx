import React from 'react';

/**
 * SourceBadge — one visual token telling a judge, at a glance, whether the
 * data next to it is:
 *
 *   - "live"     → real Casper testnet / hosted API row, not a fixture
 *   - "sim"      → deterministic simulation (heuristic path, mocked provider)
 *   - "fixture"  → static fixture bundled with the frontend (a canned demo row)
 *   - "unknown"  → the source could not be resolved yet (loading state)
 *
 * The label is deliberately short so it fits inline in a table cell or next
 * to a metric. Colour + a tooltip carry the semantic weight.
 *
 * Usage:
 *   <SourceBadge source="live" />
 *   <SourceBadge source="fixture" title="Bundled demo row — no on-chain state" />
 */

type SourceKind = 'live' | 'sim' | 'fixture' | 'unknown';

interface Props {
  source: SourceKind;
  /** Optional tooltip; defaults to a per-kind explanation. */
  title?: string;
  /** Optional visible label override; defaults to the source kind uppercase. */
  label?: string;
  className?: string;
}

const STYLES: Record<SourceKind, { bg: string; fg: string; ring: string; label: string; title: string }> = {
  live: {
    bg: 'bg-emerald-500/10',
    fg: 'text-emerald-300',
    ring: 'ring-emerald-500/30',
    label: 'LIVE',
    title: 'Live on-chain / hosted-API data — a real Casper testnet row, not a fixture',
  },
  sim: {
    bg: 'bg-sky-500/10',
    fg: 'text-sky-300',
    ring: 'ring-sky-500/30',
    label: 'SIM',
    title: 'Simulated result — deterministic path (heuristic scoring or mocked provider)',
  },
  fixture: {
    bg: 'bg-amber-500/10',
    fg: 'text-amber-300',
    ring: 'ring-amber-500/30',
    label: 'FIXTURE',
    title: 'Bundled demo row shipped with the frontend — no on-chain state, safe to explore',
  },
  unknown: {
    bg: 'bg-slate-500/10',
    fg: 'text-slate-300',
    ring: 'ring-slate-500/30',
    label: '…',
    title: 'Source not yet resolved',
  },
};

export default function SourceBadge({ source, title, label, className = '' }: Props) {
  const s = STYLES[source] ?? STYLES.unknown;
  return (
    <span
      title={title ?? s.title}
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-mono font-semibold uppercase ring-1 ${s.bg} ${s.fg} ${s.ring} ${className}`.trim()}
    >
      {label ?? s.label}
    </span>
  );
}

export type { SourceKind };
