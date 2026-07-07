import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, HealthStatus, Stats, Event } from '../../lib/api';
import { useEscrowEvents } from '../../lib/useEscrowEvents';
import { formatCspr } from '../../lib/format';
import {
  Activity,
  CheckCircle,
  XCircle,
  DollarSign,
  Scale,
  Hourglass,
  AlertTriangle,
  Zap,
  Calendar,
  Info,
  ExternalLink,
  BarChart3,
} from 'lucide-react';
import { format } from 'date-fns';

const EXPLORER_BASE = 'https://testnet.cspr.live';

// Reusable Card Component
interface CardProps {
  title: string;
  value: string | number;
  icon: React.ElementType;
  colorClass?: string;
  description?: string;
  /** Override the default value font size — long/verbose values (e.g. a CSPR
   * amount with several decimals) look oversized and inconsistent next to
   * short integer counts at the same 4xl size. */
  valueClass?: string;
  /** When set, the whole card becomes a link into the relevant console
   * section or block explorer instead of being a dead-end number. */
  linkTo?: string;
  external?: boolean;
}

const StatCard: React.FC<CardProps> = ({ title, value, icon: Icon, colorClass = 'text-amber-500', description, valueClass = 'text-3xl', linkTo, external }) => {
  const body = (
    <>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-400">{title}</h3>
        <Icon className={`h-6 w-6 ${colorClass}`} />
      </div>
      <p className={`${valueClass} font-bold text-gray-50 mb-2 break-all`}>{value}</p>
      {description && <p className="text-xs text-gray-500 flex items-center gap-1">{description}{linkTo && <ExternalLink className="h-3 w-3" />}</p>}
    </>
  );
  const cls = 'bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 shadow-md flex flex-col justify-between transition-colors hover:border-ae-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ae-accent-bright';
  if (linkTo && external) {
    return (
      <a href={linkTo} target="_blank" rel="noreferrer" className={cls}>
        {body}
      </a>
    );
  }
  if (linkTo) {
    return (
      <Link to={linkTo} className={cls}>
        {body}
      </Link>
    );
  }
  return <div className={cls}>{body}</div>;
};

const Overview: React.FC = () => {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastFetchedAt, setLastFetchedAt] = useState<Date | null>(null);

  const fetchData = useCallback(async (showSpinner: boolean) => {
    if (showSpinner) setLoading(true);
    setError(null);
    try {
      const [healthRes, statsRes, eventsRes] = await Promise.all([
        api.getHealth(),
        api.getStats(),
        api.getEvents(),
      ]);

      if (healthRes.error) throw new Error(healthRes.error);
      if (statsRes.error) throw new Error(statsRes.error);
      if (eventsRes.error) throw new Error(eventsRes.error);

      setHealth(healthRes.data);
      setStats(statsRes.data);
      setEvents(eventsRes.data || []);
      setLastFetchedAt(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch overview data.');
      console.error('Overview fetch error:', err);
    } finally {
      if (showSpinner) setLoading(false);
    }
  }, []);

  // SSE: real-time updates — refetch stats when on-chain events arrive
  const { connected: sseConnected } = useEscrowEvents(
    useCallback(() => { fetchData(false); }, [fetchData]),
  );

  useEffect(() => {
    fetchData(true);
    // Fallback poll (SSE handles real-time; this is a safety net)
    const id = window.setInterval(() => fetchData(false), 20000);
    return () => window.clearInterval(id);
  }, [fetchData]);

  // Real (not fabricated) 7-day activity trend derived from the same events
  // the list below shows — a day with zero events renders as an empty bar,
  // it is never backfilled with placeholder data.
  const dailyCounts = useMemo(() => {
    const days: { label: string; count: number }[] = [];
    const now = new Date();
    for (let i = 6; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(d.getDate() - i);
      const key = d.toDateString();
      const count = events.filter((e) => new Date(e.timestamp).toDateString() === key).length;
      days.push({ label: format(d, 'EEE'), count });
    }
    return days;
  }, [events]);
  const maxCount = Math.max(1, ...dailyCounts.map((d) => d.count));

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-16 w-16 border-t-2 border-b-2 border-amber-500"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-red-500 bg-red-900/20 border border-red-700 rounded-lg p-4 flex items-center">
        <XCircle className="h-6 w-6 mr-2" />
        <p>Error: {error}</p>
      </div>
    );
  }

  const neonConnected = health?.database === 'connected' || stats?.db === 'connected';
  const sourceLabel = stats?.data_source === 'neon' ? 'Neon persistent records' : 'Hosted demo fallback';
  const modeLabel = health?.sandbox || stats?.sandbox ? 'Sandbox runtime' : 'Casper testnet runtime';
  const uptimeText = health?.uptime && health.uptime > 60
    ? `${Math.floor(health.uptime / 3600)}h ${Math.floor((health.uptime % 3600) / 60)}m`
    : 'Live API session';
  const contractExplorerUrl = health?.contract_hash ? `${EXPLORER_BASE}/contract/${health.contract_hash}` : undefined;

  return (
    <div className="space-y-8">
      {/* Health Status */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-5 shadow-md">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm text-gray-400">API status</span>
            {health?.status === 'ok' ? <CheckCircle className="h-5 w-5 text-green-400" /> : <XCircle className="h-5 w-5 text-red-400" />}
          </div>
          <p className="text-2xl font-bold text-gray-50">{health?.status === 'ok' ? 'Online' : 'Needs attention'}</p>
          <p className="text-xs text-gray-500 mt-2">Version {health?.version || '0.2.0'} · {uptimeText}</p>
        </div>
        <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-5 shadow-md">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm text-gray-400">Persistence</span>
            <Info className={`h-5 w-5 ${neonConnected ? 'text-green-400' : 'text-amber-400'}`} />
          </div>
          <p className="text-2xl font-bold text-gray-50">{neonConnected ? 'Neon connected' : 'Neon fallback'}</p>
          <p className="text-xs text-gray-500 mt-2">{sourceLabel}</p>
        </div>
        <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-5 shadow-md">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm text-gray-400">Network mode</span>
            <Zap className="h-5 w-5 text-amber-400" />
          </div>
          <p className="text-2xl font-bold text-gray-50">Casper testnet</p>
          <p className="text-xs text-gray-500 mt-2">{modeLabel}</p>
        </div>
        {contractExplorerUrl ? (
          <a
            href={contractExplorerUrl}
            target="_blank"
            rel="noreferrer"
            className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-5 shadow-md hover:border-ae-accent/50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ae-accent-bright"
          >
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm text-gray-400">Contract target</span>
              <Info className="h-5 w-5 text-cyan-400" />
            </div>
            <p className="text-lg font-bold text-gray-50 break-all">{`${health?.contract_hash?.slice(0, 10)}…${health?.contract_hash?.slice(-8)}`}</p>
            <p className="text-xs text-gray-500 mt-2 flex items-center gap-1">View on CSPR.live <ExternalLink className="h-3 w-3" /></p>
          </a>
        ) : (
          <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-5 shadow-md">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm text-gray-400">Contract target</span>
              <Info className="h-5 w-5 text-cyan-400" />
            </div>
            <p className="text-lg font-bold text-gray-50">Configured</p>
            <p className="text-xs text-gray-500 mt-2">Escrow lifecycle endpoint</p>
          </div>
        )}
      </div>

      {/* Stats Cards — each links into the console section (or explorer) that
          explains the number, instead of being a dead-end metric. */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          title="Total Escrows"
          value={stats?.total_escrows ?? 'N/A'}
          icon={DollarSign}
          colorClass="text-amber-500"
          description="View in Escrows"
          linkTo="/console/escrows"
        />
        <StatCard
          title="Total Volume"
          value={stats ? formatCspr(stats.total_volume) : 'N/A'}
          icon={Scale}
          colorClass="text-orange-500"
          valueClass="text-xl sm:text-2xl"
        />
        <StatCard
          title="Pending Escrows"
          value={stats?.pending_escrows ?? 'N/A'}
          icon={Hourglass}
          colorClass="text-blue-500"
          description="View in Escrows"
          linkTo="/console/escrows"
        />
        <StatCard
          title="Disputed Escrows"
          value={stats?.disputed_escrows ?? 'N/A'}
          icon={AlertTriangle}
          colorClass="text-red-500"
          description="Resolve in Arbitration"
          linkTo="/console/arbitration"
        />
      </div>

      {/* Activity trend — a real (not simulated) 7-day bar chart built from
          the same event log shown below, so the console has at least one
          at-a-glance visual instead of numbers only. */}
      <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 shadow-md">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-400 mb-4 flex items-center">
          <BarChart3 className="h-5 w-5 mr-2 text-amber-500" />
          Event volume, last 7 days
        </h3>
        <div className="flex items-end gap-3 h-28">
          {dailyCounts.map((d) => (
            <div key={d.label} className="flex-1 flex flex-col items-center gap-1.5">
              <div className="w-full flex items-end h-20">
                <div
                  className="w-full rounded-t-md bg-gradient-to-t from-amber-600 to-amber-400 transition-[height] duration-500"
                  style={{ height: `${Math.max(4, (d.count / maxCount) * 100)}%` }}
                  title={`${d.count} event(s)`}
                />
              </div>
              <span className="text-[10px] text-gray-500">{d.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Recent Activity */}
      <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 shadow-md">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-400 flex items-center">
            <Activity className="h-5 w-5 mr-2 text-amber-500" />
            Recent Activity
          </h3>
          <span className="inline-flex items-center gap-1.5 text-xs text-gray-500">
            <span className="relative flex h-2 w-2">
              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${sseConnected ? 'bg-green-400' : 'bg-yellow-400'} opacity-75`} />
              <span className={`relative inline-flex rounded-full h-2 w-2 ${sseConnected ? 'bg-green-500' : 'bg-yellow-500'}`} />
            </span>
            {sseConnected ? 'Live (SSE)' : 'Polling'} · {lastFetchedAt ? format(lastFetchedAt, 'HH:mm:ss') : '—'}
          </span>
        </div>
        {events.length > 0 ? (
          <ul className="divide-y divide-[#1e1e2e]">
            {events.slice(0, 10).map((event) => (
              <li key={event.id} className="py-3 flex items-start space-x-3">
                <Calendar className="h-5 w-5 text-gray-500 flex-shrink-0 mt-1" />
                <div>
                  <p className="text-gray-300 font-medium">
                    <span className="text-amber-400">{event.type.replace(/_/g, ' ')}</span>{' '}
                    <span className="text-gray-500 text-sm">
                      {format(new Date(event.timestamp), 'MMM dd, yyyy HH:mm')}
                    </span>
                  </p>
                  <pre className="text-gray-400 text-xs bg-gray-800 p-2 rounded-md mt-1 overflow-x-auto">
                    {JSON.stringify(event.details, null, 2)}
                  </pre>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-gray-400">No recent activity found.</p>
        )}
      </div>
    </div>
  );
};

export default Overview;
