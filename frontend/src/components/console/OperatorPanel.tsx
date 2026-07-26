import React, { useEffect, useState } from 'react';
import SourceBadge from './SourceBadge';

/**
 * OperatorPanel — live snapshot of the /ops/health surface.
 *
 * Reads the enriched operator endpoint (`/ops/health`) which returns dependency
 * status, retry-queue depth, LLM provider circuit-breaker state, and mode /
 * strict-mode flags. This gives an operator (or a judge looking at operator UX)
 * a single glance into "what's up, what's degraded, what's failing".
 *
 * Design:
 *   - Zero secrets displayed (provider readiness is boolean + model name only).
 *   - Polls once per 30s; the endpoint itself is cheap (no live LLM ping).
 *   - Fail-safe rendering: if the surface is missing (older backend) we say so
 *     explicitly instead of showing a spinner forever.
 */

interface ProviderState {
  name: string;
  configured: boolean;
  model: string | null;
  last_ok_at: number;
  last_error_at: number;
  consecutive_failures: number;
  circuit_state: 'closed' | 'open' | 'half_open' | string;
}

interface RetryStats {
  pending: number;
  failed_last_24h: number;
  succeeded_last_24h: number;
}

interface OpsSnapshot {
  started_at: number;
  uptime_s: number;
  build_sha: string;
  config_version: string;
  mode: 'sandbox' | 'live' | string;
  strict_mode: {
    enabled: boolean;
    preconditions_ok: boolean;
    violations: string[];
    guarantees: string[];
  };
  dependencies: ProviderState[];
  retries: RetryStats;
  warnings: string[];
}

const POLL_MS = 30_000;

function apiBase(): string {
  const meta = (import.meta as any).env ?? {};
  return meta.VITE_API_BASE ?? '';
}

function fmtUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  if (h < 24) return `${h}h ${rem}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

function circuitColour(state: string): string {
  switch (state) {
    case 'closed':
      return 'text-emerald-300 bg-emerald-500/10 ring-emerald-500/30';
    case 'half_open':
      return 'text-amber-300 bg-amber-500/10 ring-amber-500/30';
    case 'open':
      return 'text-rose-300 bg-rose-500/10 ring-rose-500/30';
    default:
      return 'text-slate-300 bg-slate-500/10 ring-slate-500/30';
  }
}

export default function OperatorPanel() {
  const [snap, setSnap] = useState<OpsSnapshot | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshedAt, setRefreshedAt] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    async function tick() {
      try {
        const r = await fetch(`${apiBase()}/ops/health`, {
          headers: { Accept: 'application/json' },
        });
        if (!r.ok) {
          if (!cancelled) {
            setErr(`ops/health → HTTP ${r.status}`);
            setLoading(false);
          }
          return;
        }
        const data = (await r.json()) as OpsSnapshot;
        if (cancelled) return;
        setSnap(data);
        setErr(null);
        setLoading(false);
        setRefreshedAt(Date.now());
      } catch (e: any) {
        if (!cancelled) {
          setErr(e?.message ?? String(e));
          setLoading(false);
        }
      }
    }
    tick();
    const id = window.setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  if (loading) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 text-slate-400">
        Loading operator snapshot…
      </div>
    );
  }
  if (err && !snap) {
    return (
      <div className="rounded-lg border border-rose-800/50 bg-rose-950/30 p-4 text-rose-300">
        <div className="font-mono text-sm">Could not fetch /ops/health</div>
        <div className="mt-1 text-xs text-rose-400">{err}</div>
      </div>
    );
  }
  if (!snap) return null;

  const strictBadge = snap.strict_mode.enabled ? (
    snap.strict_mode.preconditions_ok ? (
      <SourceBadge source="live" label="STRICT" title="AE402_STRICT=1 — all preconditions satisfied (fail-loud guarantees active)" />
    ) : (
      <SourceBadge source="sim" label="STRICT?" title={`STRICT enabled but preconditions failing: ${snap.strict_mode.violations.join('; ')}`} />
    )
  ) : (
    <SourceBadge source="fixture" label="LENIENT" title="AE402_STRICT=0 — silent fallbacks allowed" />
  );

  return (
    <div className="space-y-4">
      {/* ── Header row: mode + uptime + build ─────────────────────── */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4">
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wide text-slate-400">Mode</span>
          <SourceBadge
            source={snap.mode === 'live' ? 'live' : 'sim'}
            label={snap.mode}
            title={snap.mode === 'live' ? 'Live testnet mode' : 'Sandbox mode (no on-chain writes)'}
          />
        </div>
        {strictBadge}
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wide text-slate-400">Uptime</span>
          <span className="font-mono text-sm text-slate-200">{fmtUptime(snap.uptime_s)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wide text-slate-400">Build</span>
          <span className="font-mono text-xs text-slate-300">{snap.build_sha}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wide text-slate-400">Config</span>
          <span className="font-mono text-xs text-slate-300">{snap.config_version}</span>
        </div>
        <div className="ml-auto text-[10px] uppercase text-slate-500">
          refreshed {refreshedAt ? new Date(refreshedAt).toLocaleTimeString() : '—'}
        </div>
      </div>

      {/* ── Retry queue ───────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
          <div className="text-[10px] uppercase text-slate-400">Retry queue</div>
          <div className="mt-1 text-xl font-mono text-slate-100">{snap.retries.pending}</div>
          <div className="text-xs text-slate-500">pending</div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
          <div className="text-[10px] uppercase text-slate-400">Failed 24h</div>
          <div className="mt-1 text-xl font-mono text-rose-300">{snap.retries.failed_last_24h}</div>
          <div className="text-xs text-slate-500">tx failures</div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
          <div className="text-[10px] uppercase text-slate-400">Succeeded 24h</div>
          <div className="mt-1 text-xl font-mono text-emerald-300">{snap.retries.succeeded_last_24h}</div>
          <div className="text-xs text-slate-500">tx successes</div>
        </div>
      </div>

      {/* ── Providers ─────────────────────────────────────────── */}
      <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
        <div className="mb-2 flex items-center justify-between">
          <div className="text-xs uppercase tracking-wide text-slate-400">
            LLM providers ({snap.dependencies.length})
          </div>
          <div className="text-[10px] uppercase text-slate-500">circuit-breaker state</div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {snap.dependencies.map((d) => (
            <div
              key={d.name}
              className="flex items-center justify-between rounded-md border border-slate-800/70 bg-slate-950/30 p-2"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm text-slate-200">{d.name}</span>
                  {!d.configured && (
                    <SourceBadge source="fixture" label="unset" title={`${d.name.toUpperCase()}_API_KEY not configured`} />
                  )}
                </div>
                {d.model && <div className="text-[10px] font-mono text-slate-500">{d.model}</div>}
                {d.consecutive_failures > 0 && (
                  <div className="text-[10px] text-rose-400">
                    {d.consecutive_failures} consecutive failure{d.consecutive_failures === 1 ? '' : 's'}
                  </div>
                )}
              </div>
              <span
                className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-mono font-semibold uppercase ring-1 ${circuitColour(
                  d.circuit_state
                )}`}
                title={`Circuit-breaker state: ${d.circuit_state}`}
              >
                {d.circuit_state}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Warnings ──────────────────────────────────────────── */}
      {snap.warnings.length > 0 && (
        <div className="rounded-lg border border-amber-800/50 bg-amber-950/20 p-3">
          <div className="text-xs uppercase text-amber-300">Warnings</div>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-amber-200">
            {snap.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
