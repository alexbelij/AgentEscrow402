import React, { useEffect, useState } from 'react';
import {
  api,
  ApiResponse,
  RegistryIdentity,
  RegistryStats,
  VerificationLevel,
} from '../../lib/api';
import { randomHex64 } from '../../lib/format';
import { BadgeCheck, Search, ShieldAlert, TrendingDown, TrendingUp, Loader2 } from 'lucide-react';
import { useRole } from '../../lib/role';

const LEVELS: VerificationLevel[] = ['UNVERIFIED', 'BASIC', 'ENHANCED', 'FULL'];

const LEVEL_COLOR: Record<VerificationLevel, string> = {
  UNVERIFIED: 'text-gray-400',
  BASIC: 'text-sky-400',
  ENHANCED: 'text-amber-400',
  FULL: 'text-emerald-400',
};

export default function IdentityRegistry() {
  const { isObserver, blockedReason } = useRole();
  const [accountHash, setAccountHash] = useState(() => randomHex64().slice(0, 16));
  const [displayName, setDisplayName] = useState('Agent Alpha');
  const [registering, setRegistering] = useState(false);
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [identity, setIdentity] = useState<RegistryIdentity | null>(null);
  const [lookupBusy, setLookupBusy] = useState(false);
  const [lookupError, setLookupError] = useState<string | null>(null);

  const [dealsCompleted, setDealsCompleted] = useState(5);
  const [dealsDisputed, setDealsDisputed] = useState(0);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [minReputation, setMinReputation] = useState(0);
  const [minVerification, setMinVerification] = useState<VerificationLevel>('UNVERIFIED');
  const [results, setResults] = useState<RegistryIdentity[]>([]);
  const [searching, setSearching] = useState(false);

  const [stats, setStats] = useState<RegistryStats | null>(null);

  const loadStats = async () => {
    const res = await api.getRegistryStats();
    if (res.data) setStats(res.data);
  };

  const runSearch = async () => {
    setSearching(true);
    const res = await api.searchRegistryIdentities({ min_reputation: minReputation, min_verification: minVerification });
    setSearching(false);
    if (res.data) setResults(res.data);
  };

  useEffect(() => {
    loadStats();
    runSearch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const register = async () => {
    setRegistering(true);
    setRegisterError(null);
    const res = await api.registerRegistryIdentity({ account_hash: accountHash, display_name: displayName });
    setRegistering(false);
    if (res.error) {
      setRegisterError(res.error);
      return;
    }
    setIdentity(res.data ?? null);
    await Promise.all([loadStats(), runSearch()]);
  };

  // Select any existing identity from the registry (e.g. a search result, or
  // one registered in a previous session) as the "active" identity below, so
  // simulate/decay/slash/verify aren't only usable right after registering.
  const selectByDid = async (did: string) => {
    setLookupBusy(true);
    setLookupError(null);
    const res = await api.getRegistryIdentity(did);
    setLookupBusy(false);
    if (res.error) {
      setLookupError(res.error);
      return;
    }
    setIdentity(res.data ?? null);
  };

  const lookupByAccount = async () => {
    setLookupBusy(true);
    setLookupError(null);
    const res = await api.getRegistryIdentityByAccount(accountHash);
    setLookupBusy(false);
    if (res.error) {
      setLookupError(res.error);
      return;
    }
    setIdentity(res.data ?? null);
  };

  const withBusy = async (label: string, fn: () => Promise<ApiResponse<RegistryIdentity>>) => {
    setBusyAction(label);
    setActionError(null);
    const res = await fn();
    setBusyAction(null);
    if (res.error) {
      setActionError(res.error);
      return;
    }
    setIdentity(res.data ?? null);
    await Promise.all([loadStats(), runSearch()]);
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-[#12121c] border border-[#1e1e2e] rounded-lg p-5">
          <h2 className="text-lg font-semibold text-white mb-4">Register an identity</h2>
          <label className="block text-sm font-medium text-gray-300 mb-1">Account hash</label>
          <div className="flex gap-2 mb-3">
            <input
              value={accountHash}
              onChange={(e) => setAccountHash(e.target.value)}
              className="flex-1 p-3 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] font-mono text-sm"
            />
            <button
              onClick={() => setAccountHash(randomHex64().slice(0, 16))}
              className="px-3 rounded-md bg-gray-800 border border-[#1e1e2e] text-gray-300 hover:text-white"
              title="Generate new account hash"
            >
              ↻
            </button>
          </div>
          <label className="block text-sm font-medium text-gray-300 mb-1">Display name</label>
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="w-full p-3 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] mb-4"
          />
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={register}
              disabled={registering || isObserver}
              title={isObserver ? blockedReason : undefined}
              className="h-12 inline-flex items-center justify-center gap-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {registering ? <Loader2 className="w-4 h-4 animate-spin" /> : <BadgeCheck className="w-4 h-4" />}
              Register identity
            </button>
            <button
              onClick={lookupByAccount}
              disabled={lookupBusy}
              title="Look up an identity that already exists for this account hash, instead of registering a new one"
              className="h-12 inline-flex items-center justify-center gap-2 rounded-lg bg-gray-800 border border-[#1e1e2e] text-gray-200 hover:text-white font-semibold disabled:opacity-50"
            >
              {lookupBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
              Look up existing
            </button>
          </div>
          {registerError && <p className="text-red-400 text-sm mt-2">{registerError}</p>}
          {lookupError && <p className="text-red-400 text-sm mt-2">{lookupError}</p>}

          {identity && (
            <div className="mt-5 p-4 rounded-lg bg-gray-800/60 border border-[#1e1e2e] text-sm space-y-1">
              <p className="font-mono text-gray-300 break-all">{identity.did}</p>
              <div className="flex justify-between">
                <span className={`font-semibold ${LEVEL_COLOR[identity.verification_level]}`}>{identity.verification_level}</span>
                <span className="text-gray-400">reputation {identity.reputation_score}</span>
              </div>
              <p className="text-gray-500 text-xs">
                deals: {identity.total_deals} · dispute rate: {(identity.dispute_rate * 100).toFixed(1)}% · risk score:{' '}
                {identity.risk_score} · stake: {identity.stake} · slashed: {identity.slashed_count}×
              </p>
            </div>
          )}

          {identity && (
            <div className="mt-4 pt-4 border-t border-[#1e1e2e] space-y-3">
              <p className="text-sm font-medium text-gray-300">Simulate activity for this identity</p>
              <div className="flex gap-2">
                <input
                  type="number"
                  value={dealsCompleted}
                  onChange={(e) => setDealsCompleted(Number(e.target.value))}
                  className="w-1/2 p-2 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] text-sm"
                  placeholder="completed"
                />
                <input
                  type="number"
                  value={dealsDisputed}
                  onChange={(e) => setDealsDisputed(Number(e.target.value))}
                  className="w-1/2 p-2 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] text-sm"
                  placeholder="disputed"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() =>
                    withBusy('reputation', () => api.updateRegistryReputation(identity.did, dealsCompleted, dealsDisputed))
                  }
                  disabled={!!busyAction || isObserver}
                  title={isObserver ? blockedReason : undefined}
                  className="h-9 inline-flex items-center justify-center gap-1 rounded-md bg-gray-800 border border-[#1e1e2e] text-gray-200 hover:text-white text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <TrendingUp className="w-3.5 h-3.5" /> Record deals
                </button>
                <button
                  onClick={() => withBusy('decay', () => api.applyRegistryDecay(identity.did))}
                  disabled={!!busyAction || isObserver}
                  title={isObserver ? blockedReason : undefined}
                  className="h-9 inline-flex items-center justify-center gap-1 rounded-md bg-gray-800 border border-[#1e1e2e] text-gray-200 hover:text-white text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <TrendingDown className="w-3.5 h-3.5" /> Apply decay
                </button>
                <button
                  onClick={() => withBusy('slash', () => api.slashRegistryIdentity(identity.did, 10, 'console-demo-slash'))}
                  disabled={!!busyAction || isObserver}
                  title={isObserver ? blockedReason : undefined}
                  className="h-9 inline-flex items-center justify-center gap-1 rounded-md bg-gray-800 border border-[#1e1e2e] text-red-300 hover:text-red-200 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ShieldAlert className="w-3.5 h-3.5" /> Slash 10
                </button>
                <button
                  onClick={() => {
                    const idx = LEVELS.indexOf(identity.verification_level);
                    const next = LEVELS[Math.min(idx + 1, LEVELS.length - 1)];
                    withBusy('verify', () => api.verifyRegistryIdentity(identity.did, next));
                  }}
                  disabled={!!busyAction || identity.verification_level === 'FULL' || isObserver}
                  title={isObserver ? blockedReason : undefined}
                  className="h-9 inline-flex items-center justify-center gap-1 rounded-md bg-gray-800 border border-[#1e1e2e] text-gray-200 hover:text-white text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <BadgeCheck className="w-3.5 h-3.5" /> Advance verification
                </button>
                <button
                  onClick={() => {
                    const cap = prompt('Enter capability to add (e.g., escrow_agent, data_oracle, compute_provider):');
                    if (cap) {
                      const current = identity.capabilities?.map((c: any) => typeof c === 'string' ? c : c.name) ?? [];
                      withBusy('capabilities', () => api.updateRegistryCapabilities(identity.did, [...current, cap] as any));
                    }
                  }}
                  disabled={!!busyAction || isObserver}
                  title={isObserver ? blockedReason : undefined}
                  className="h-9 inline-flex items-center justify-center gap-1 rounded-md bg-gray-800 border border-[#1e1e2e] text-gray-200 hover:text-white text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  + Add capability
                </button>
              </div>
              {actionError && <p className="text-red-400 text-sm">{actionError}</p>}
            </div>
          )}
        </div>

        <div className="bg-[#12121c] border border-[#1e1e2e] rounded-lg p-5">
          <h2 className="text-lg font-semibold text-white mb-4">Registry overview</h2>
          {stats && (
            <div className="grid grid-cols-2 gap-3 mb-4">
              <div className="p-3 rounded-md bg-gray-800/40 border border-[#1e1e2e]">
                <p className="text-xs text-gray-500">Registered agents</p>
                <p className="text-xl font-bold text-white">{stats.total_agents}</p>
              </div>
              <div className="p-3 rounded-md bg-gray-800/40 border border-[#1e1e2e]">
                <p className="text-xs text-gray-500">Avg reputation</p>
                <p className="text-xl font-bold text-white">{stats.avg_reputation.toFixed(1)}</p>
              </div>
            </div>
          )}

          <div className="flex items-end gap-2 mb-3">
            <div className="w-20 shrink-0">
              <label className="block text-xs font-medium text-gray-400 mb-1">Min reputation</label>
              <input
                type="number"
                value={minReputation}
                onChange={(e) => setMinReputation(Number(e.target.value))}
                className="w-full p-2 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] text-sm"
              />
            </div>
            <div className="flex-1 min-w-0">
              <label className="block text-xs font-medium text-gray-400 mb-1">Min verification</label>
              <select
                value={minVerification}
                onChange={(e) => setMinVerification(e.target.value as VerificationLevel)}
                className="w-full p-2 pr-1 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] text-xs sm:text-sm"
              >
                {LEVELS.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </div>
            <button
              onClick={runSearch}
              disabled={searching}
              className="h-9 px-3 inline-flex items-center gap-1 rounded-md bg-amber-600 hover:bg-amber-700 text-white text-sm disabled:opacity-50"
            >
              <Search className="w-3.5 h-3.5" /> Search
            </button>
          </div>

          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-400 text-left border-b border-[#1e1e2e]">
                <th className="pb-2">DID</th>
                <th className="pb-2">Level</th>
                <th className="pb-2">Reputation</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr
                  key={r.did}
                  onClick={() => selectByDid(r.did)}
                  title="Select this identity to simulate activity / decay / slash / verify on it"
                  className={`border-b border-[#1e1e2e]/50 cursor-pointer hover:bg-gray-800/40 ${identity?.did === r.did ? 'bg-amber-500/10' : ''}`}
                >
                  <td className="py-2 font-mono text-gray-300 truncate max-w-[180px]">{r.did}</td>
                  <td className={`py-2 ${LEVEL_COLOR[r.verification_level]}`}>{r.verification_level}</td>
                  <td className="py-2 text-gray-300">{r.reputation_score}</td>
                </tr>
              ))}
              {results.length === 0 && (
                <tr>
                  <td colSpan={3} className="py-4 text-center text-gray-500">
                    No agents match this filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
