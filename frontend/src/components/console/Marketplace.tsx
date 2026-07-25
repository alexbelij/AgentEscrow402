import React, { useEffect, useMemo, useState } from 'react';
import { api, RegistryIdentity, RegistryStats, VerificationLevel } from '../../lib/api';
import {
  BadgeCheck,
  Search,
  ShieldAlert,
  Loader2,
  Store,
  X,
  ArrowUpDown,
  Star,
} from 'lucide-react';

const LEVEL_ORDER: VerificationLevel[] = ['UNVERIFIED', 'BASIC', 'ENHANCED', 'FULL'];

const LEVEL_COLOR: Record<VerificationLevel, string> = {
  UNVERIFIED: 'text-gray-400 border-gray-600 bg-gray-800/40',
  BASIC: 'text-sky-300 border-sky-500/40 bg-sky-500/10',
  ENHANCED: 'text-amber-300 border-amber-500/40 bg-amber-500/10',
  FULL: 'text-emerald-300 border-emerald-500/40 bg-emerald-500/10',
};

type SortKey = 'reputation' | 'deals' | 'verification' | 'recent';

const SORT_LABEL: Record<SortKey, string> = {
  reputation: 'Reputation',
  deals: 'Deals completed',
  verification: 'Verification level',
  recent: 'Recently active',
};

/**
 * Agent discovery marketplace (T3.6).
 *
 * Distinct from `IdentityRegistry.tsx` (the admin/testing console tab for
 * registering + simulating identity activity) — this page is the
 * discovery-first surface: browse every agent registered in the DID
 * reputation registry (server/identity_registry.py), filter by capability,
 * minimum reputation and verification level, free-text search on the
 * display name / DID, and sort by the dimension that matters for picking a
 * counterparty. Backed entirely by the existing `/identity-registry`
 * endpoints — no backend change required. Capability chips and the
 * "recently active" sort are derived client-side from the full result set
 * since the backend has no distinct-capability listing endpoint.
 */
export default function Marketplace() {
  const [allAgents, setAllAgents] = useState<RegistryIdentity[]>([]);
  const [stats, setStats] = useState<RegistryStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState('');
  const [activeCapabilities, setActiveCapabilities] = useState<Set<string>>(new Set());
  const [minReputation, setMinReputation] = useState(0);
  const [minVerification, setMinVerification] = useState<VerificationLevel>('UNVERIFIED');
  const [sortKey, setSortKey] = useState<SortKey>('reputation');
  const [selected, setSelected] = useState<RegistryIdentity | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    // Empty-filter search returns every registered agent — capability chips
    // and client-side text search are derived from this full set.
    const [agentsRes, statsRes] = await Promise.all([
      api.searchRegistryIdentities({}),
      api.getRegistryStats(),
    ]);
    setLoading(false);
    if (agentsRes.error) {
      setError(agentsRes.error);
      return;
    }
    setAllAgents(agentsRes.data ?? []);
    if (statsRes.data) setStats(statsRes.data);
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const allCapabilities = useMemo(() => {
    const names = new Set<string>();
    for (const agent of allAgents) {
      for (const cap of agent.capabilities ?? []) names.add(cap.name);
    }
    return Array.from(names).sort();
  }, [allAgents]);

  const toggleCapability = (name: string) => {
    setActiveCapabilities((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const filtered = useMemo(() => {
    const minLevelIdx = LEVEL_ORDER.indexOf(minVerification);
    const q = query.trim().toLowerCase();

    let list = allAgents.filter((agent) => {
      if (LEVEL_ORDER.indexOf(agent.verification_level) < minLevelIdx) return false;
      if (agent.reputation_score < minReputation) return false;
      if (activeCapabilities.size > 0) {
        const agentCaps = new Set((agent.capabilities ?? []).map((c) => c.name));
        for (const needed of activeCapabilities) {
          if (!agentCaps.has(needed)) return false;
        }
      }
      if (q) {
        const haystack = `${agent.display_name} ${agent.did} ${agent.account_hash}`.toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });

    list = [...list].sort((a, b) => {
      switch (sortKey) {
        case 'reputation':
          return b.reputation_score - a.reputation_score;
        case 'deals':
          return b.total_deals - a.total_deals;
        case 'verification':
          return LEVEL_ORDER.indexOf(b.verification_level) - LEVEL_ORDER.indexOf(a.verification_level);
        case 'recent':
          return b.last_active - a.last_active;
        default:
          return 0;
      }
    });

    return list;
  }, [allAgents, activeCapabilities, minReputation, minVerification, query, sortKey]);

  const clearFilters = () => {
    setQuery('');
    setActiveCapabilities(new Set());
    setMinReputation(0);
    setMinVerification('UNVERIFIED');
  };

  const hasActiveFilters =
    query || activeCapabilities.size > 0 || minReputation > 0 || minVerification !== 'UNVERIFIED';

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-amber-500/10 border border-amber-500/30 flex items-center justify-center">
            <Store className="w-5 h-5 text-amber-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">Agent discovery marketplace</h2>
            <p className="text-sm text-gray-400">
              Browse every agent in the identity registry — filter by capability, reputation and
              verification to find a counterparty for your next escrow.
            </p>
          </div>
        </div>
        {stats && (
          <div className="hidden md:flex gap-4 text-right">
            <div>
              <p className="text-xl font-semibold text-white">{stats.total_agents}</p>
              <p className="text-xs text-gray-500">agents</p>
            </div>
            <div>
              <p className="text-xl font-semibold text-white">{stats.avg_reputation.toFixed(0)}</p>
              <p className="text-xs text-gray-500">avg reputation</p>
            </div>
            <div>
              <p className="text-xl font-semibold text-emerald-400">{stats.distribution_by_level?.FULL ?? 0}</p>
              <p className="text-xs text-gray-500">fully verified</p>
            </div>
          </div>
        )}
      </div>

      {/* Search + sort */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex-1 relative">
          <Search className="w-4 h-4 text-gray-500 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name, DID, or account hash…"
            className="w-full pl-9 p-3 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] text-sm"
          />
        </div>
        <div className="flex items-center gap-2">
          <ArrowUpDown className="w-4 h-4 text-gray-500" />
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="p-3 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] text-sm"
          >
            {Object.entries(SORT_LABEL).map(([key, label]) => (
              <option key={key} value={key}>
                Sort: {label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-[#12121c] border border-[#1e1e2e] rounded-lg p-4 space-y-4">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-400">Min reputation</label>
            <input
              type="range"
              min={0}
              max={100}
              value={minReputation}
              onChange={(e) => setMinReputation(Number(e.target.value))}
              className="w-32"
            />
            <span className="text-xs text-gray-300 w-8">{minReputation}</span>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-400">Min verification</label>
            <select
              value={minVerification}
              onChange={(e) => setMinVerification(e.target.value as VerificationLevel)}
              className="p-1.5 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] text-xs"
            >
              {LEVEL_ORDER.map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </select>
          </div>
          {hasActiveFilters && (
            <button
              onClick={clearFilters}
              className="text-xs text-gray-400 hover:text-white flex items-center gap-1 ml-auto"
            >
              <X className="w-3 h-3" /> Clear filters
            </button>
          )}
        </div>

        {allCapabilities.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {allCapabilities.map((cap) => {
              const active = activeCapabilities.has(cap);
              return (
                <button
                  key={cap}
                  onClick={() => toggleCapability(cap)}
                  className={`px-3 py-1 rounded-full text-xs border transition-colors ${
                    active
                      ? 'bg-amber-500/20 border-amber-500/50 text-amber-300'
                      : 'bg-gray-800 border-[#1e1e2e] text-gray-400 hover:text-white'
                  }`}
                >
                  {cap}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Results */}
      {loading ? (
        <div className="flex items-center justify-center py-16 text-gray-400">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading agents…
        </div>
      ) : error ? (
        <p className="text-red-400 text-sm">{error}</p>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-gray-500">
          <p>No agents match these filters.</p>
          {allAgents.length === 0 && (
            <p className="text-xs mt-1">
              No agents are registered yet — head to Identity Registry to register the first one.
            </p>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((agent) => (
            <button
              key={agent.did}
              onClick={() => setSelected(agent)}
              className="text-left bg-[#12121c] border border-[#1e1e2e] rounded-lg p-4 hover:border-amber-500/40 transition-colors"
            >
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-semibold text-white truncate">{agent.display_name}</h3>
                <span
                  className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${LEVEL_COLOR[agent.verification_level]}`}
                >
                  {agent.verification_level}
                </span>
              </div>
              <p className="text-xs text-gray-500 font-mono truncate mb-3">{agent.did}</p>
              <div className="flex items-center gap-3 text-sm mb-3">
                <span className="flex items-center gap-1 text-amber-400">
                  <Star className="w-3.5 h-3.5 fill-current" /> {agent.reputation_score}
                </span>
                <span className="text-gray-400">{agent.total_deals} deals</span>
                {agent.dispute_rate > 0 && (
                  <span className="text-red-400">{(agent.dispute_rate * 100).toFixed(0)}% disputed</span>
                )}
                {agent.slashed_count > 0 && (
                  <span className="flex items-center gap-1 text-red-400">
                    <ShieldAlert className="w-3.5 h-3.5" /> {agent.slashed_count}×
                  </span>
                )}
              </div>
              <div className="flex flex-wrap gap-1">
                {(agent.capabilities ?? []).slice(0, 4).map((cap) => (
                  <span
                    key={cap.name}
                    className="text-[10px] px-2 py-0.5 rounded-full bg-gray-800 border border-[#1e1e2e] text-gray-400 flex items-center gap-1"
                  >
                    {cap.verified && <BadgeCheck className="w-3 h-3 text-emerald-400" />}
                    {cap.name}
                  </span>
                ))}
                {(agent.capabilities?.length ?? 0) > 4 && (
                  <span className="text-[10px] px-2 py-0.5 text-gray-500">
                    +{(agent.capabilities?.length ?? 0) - 4} more
                  </span>
                )}
                {(agent.capabilities?.length ?? 0) === 0 && (
                  <span className="text-[10px] text-gray-600">no listed capabilities</span>
                )}
              </div>
            </button>
          ))}
        </div>
      )}

      {/* Detail drawer */}
      {selected && (
        <div
          className="fixed inset-0 bg-black/60 z-40 flex items-center justify-center p-4"
          onClick={() => setSelected(null)}
        >
          <div
            className="bg-[#12121c] border border-[#1e1e2e] rounded-lg p-6 max-w-lg w-full space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-lg font-semibold text-white">{selected.display_name}</h3>
                <p className="text-xs text-gray-500 font-mono break-all mt-1">{selected.did}</p>
              </div>
              <button onClick={() => setSelected(null)} className="text-gray-500 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex items-center gap-2">
              <span
                className={`text-xs px-2.5 py-1 rounded-full border font-medium ${LEVEL_COLOR[selected.verification_level]}`}
              >
                {selected.verification_level}
              </span>
              <span className="text-xs text-gray-500">registered account {selected.account_hash}</span>
            </div>

            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="bg-gray-800/60 rounded-md p-3">
                <p className="text-gray-500 text-xs">Reputation</p>
                <p className="text-white font-semibold text-lg">{selected.reputation_score}</p>
              </div>
              <div className="bg-gray-800/60 rounded-md p-3">
                <p className="text-gray-500 text-xs">Risk score</p>
                <p className="text-white font-semibold text-lg">{selected.risk_score}</p>
              </div>
              <div className="bg-gray-800/60 rounded-md p-3">
                <p className="text-gray-500 text-xs">Total deals</p>
                <p className="text-white font-semibold text-lg">{selected.total_deals}</p>
              </div>
              <div className="bg-gray-800/60 rounded-md p-3">
                <p className="text-gray-500 text-xs">Dispute rate</p>
                <p className="text-white font-semibold text-lg">{(selected.dispute_rate * 100).toFixed(1)}%</p>
              </div>
              <div className="bg-gray-800/60 rounded-md p-3">
                <p className="text-gray-500 text-xs">Stake</p>
                <p className="text-white font-semibold text-lg">{selected.stake}</p>
              </div>
              <div className="bg-gray-800/60 rounded-md p-3">
                <p className="text-gray-500 text-xs">Slashed</p>
                <p className="text-white font-semibold text-lg">{selected.slashed_count}×</p>
              </div>
            </div>

            <div>
              <p className="text-xs text-gray-500 mb-2">Capabilities</p>
              {(selected.capabilities ?? []).length === 0 ? (
                <p className="text-sm text-gray-600">No capabilities listed.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {selected.capabilities.map((cap) => (
                    <span
                      key={cap.name}
                      className="text-xs px-2.5 py-1 rounded-full bg-gray-800 border border-[#1e1e2e] text-gray-300 flex items-center gap-1"
                      title={cap.description}
                    >
                      {cap.verified && <BadgeCheck className="w-3.5 h-3.5 text-emerald-400" />}
                      {cap.name} <span className="text-gray-500">v{cap.version}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
