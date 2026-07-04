import React, { useEffect, useState } from 'react';
import { api, HealthStatus, Stats, Event } from '../../lib/api';
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
} from 'lucide-react';
import { format } from 'date-fns';

// Reusable Card Component
interface CardProps {
  title: string;
  value: string | number;
  icon: React.ElementType;
  colorClass?: string;
  description?: string;
}

const StatCard: React.FC<CardProps> = ({ title, value, icon: Icon, colorClass = 'text-amber-500', description }) => (
  <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 shadow-md flex flex-col justify-between">
    <div className="flex items-center justify-between mb-4">
      <h3 className="text-lg font-semibold text-gray-300">{title}</h3>
      <Icon className={`h-8 w-8 ${colorClass}`} />
    </div>
    <p className="text-4xl font-bold text-gray-50 mb-2">{value}</p>
    {description && <p className="text-sm text-gray-400">{description}</p>}
  </div>
);

const Overview: React.FC = () => {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
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
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch overview data.');
        console.error('Overview fetch error:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

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
        <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-5 shadow-md">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm text-gray-400">Contract target</span>
            <Info className="h-5 w-5 text-cyan-400" />
          </div>
          <p className="text-lg font-bold text-gray-50 break-all">{health?.contract_hash ? `${health.contract_hash.slice(0, 10)}…${health.contract_hash.slice(-8)}` : 'Configured'}</p>
          <p className="text-xs text-gray-500 mt-2">Escrow lifecycle endpoint</p>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          title="Total Escrows"
          value={stats?.total_escrows ?? 'N/A'}
          icon={DollarSign}
          colorClass="text-amber-500"
        />
        <StatCard
          title="Total Volume"
          value={stats ? formatCspr(stats.total_volume) : 'N/A'}
          icon={Scale}
          colorClass="text-orange-500"
        />
        <StatCard
          title="Pending Escrows"
          value={stats?.pending_escrows ?? 'N/A'}
          icon={Hourglass}
          colorClass="text-blue-500"
        />
        <StatCard
          title="Disputed Escrows"
          value={stats?.disputed_escrows ?? 'N/A'}
          icon={AlertTriangle}
          colorClass="text-red-500"
        />
      </div>

      {/* Recent Activity */}
      <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 shadow-md">
        <h3 className="text-xl font-semibold text-gray-300 mb-4 flex items-center">
          <Activity className="h-6 w-6 mr-2 text-amber-500" />
          Recent Activity
        </h3>
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
