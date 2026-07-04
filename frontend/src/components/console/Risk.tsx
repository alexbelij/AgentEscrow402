import React, { useEffect, useMemo, useState } from 'react';
import { api, DEMO_AGENT_RECEIVER } from '../../lib/api';
import { formatCspr } from '../../lib/format';
import { AlertTriangle, Brain, Gauge, Loader2, RefreshCw, ShieldCheck, TrendingUp } from 'lucide-react';

type RiskAgent = {
  agent: string;
  risk_score: number;
  anomaly_flag: boolean;
  explanation: string;
  model_version: string;
  scored_at: number;
  escrow_count: number;
  total_volume_motes: number;
  dispute_rate: number;
};

type RiskDashboard = {
  total_agents: number;
  high_risk_count: number;
  avg_risk_score: number;
  agents: RiskAgent[];
  model_trained_at: number;
  training_samples: number;
};

const short = (value: string) => value.length > 22 ? `${value.slice(0, 10)}…${value.slice(-8)}` : value;
const pct = (value: number) => `${Math.round((value || 0) * 100)}%`;

const scoreColor = (score: number) => {
  if (score >= 75) return 'text-red-400 bg-red-500/10 border-red-500/30';
  if (score >= 45) return 'text-amber-400 bg-amber-500/10 border-amber-500/30';
  return 'text-green-400 bg-green-500/10 border-green-500/30';
};

const Risk: React.FC = () => {
  const [dashboard, setDashboard] = useState<RiskDashboard | null>(null);
  const [selectedAgent, setSelectedAgent] = useState(DEMO_AGENT_RECEIVER);
  const [agentScore, setAgentScore] = useState<RiskAgent | null>(null);
  const [loading, setLoading] = useState(true);
  const [scoreLoading, setScoreLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const topAgents = useMemo(() => dashboard?.agents?.slice(0, 8) || [], [dashboard]);

  const loadDashboard = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getRiskDashboard();
      if (res.error) throw new Error(res.error);
      setDashboard(res.data as RiskDashboard);
      const first = (res.data as RiskDashboard)?.agents?.[0]?.agent;
      if (first && selectedAgent === DEMO_AGENT_RECEIVER) setSelectedAgent(first);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load risk dashboard');
    } finally {
      setLoading(false);
    }
  };

  const scoreAgent = async (agent = selectedAgent) => {
    if (!agent.trim()) return;
    setScoreLoading(true);
    setError(null);
    try {
      const res = await api.getRiskScore(agent.trim());
      if (res.error) throw new Error(res.error);
      setAgentScore(res.data as RiskAgent);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to score agent');
    } finally {
      setScoreLoading(false);
    }
  };

  useEffect(() => {
    loadDashboard();
  }, []);

  useEffect(() => {
    if (dashboard?.agents?.[0]?.agent) scoreAgent(dashboard.agents[0].agent);
  }, [dashboard?.model_trained_at]);

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-end">
        <button
          onClick={loadDashboard}
          disabled={loading}
          className="inline-flex h-12 items-center justify-center px-5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-5 w-5 mr-2 animate-spin" /> : <RefreshCw className="h-5 w-5 mr-2" />}
          Recalculate
        </button>
      </div>

      <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4 text-sm text-blue-100 leading-relaxed">
        <p className="font-semibold mb-1">What is real here / why it matters</p>
        <p>
          Scores are computed by the live backend from the escrow dataset currently available to it: Neon-persisted records when the database is connected, otherwise the explicitly labelled hosted demo records. The IsolationForest model is real business logic, not a static mock: it uses amounts, TTLs, dispute rate, activity frequency and volume dispersion to flag anomalous agents. Product use: warn buyers before hiring risky agents, route high-risk jobs to stronger arbitration, and price insurance premiums dynamically.
        </p>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-200 flex items-center">
          <AlertTriangle className="h-5 w-5 mr-2" /> {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Metric icon={Brain} label="Model" value={agentScore?.model_version || 'IsolationForest'} />
        <Metric icon={Gauge} label="Avg risk" value={loading ? '…' : `${dashboard?.avg_risk_score ?? 0}/100`} />
        <Metric icon={AlertTriangle} label="High-risk agents" value={loading ? '…' : String(dashboard?.high_risk_count ?? 0)} />
        <Metric icon={TrendingUp} label="Training samples" value={loading ? '…' : String(dashboard?.training_samples ?? 0)} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2 bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6">
          <div className="flex items-center justify-between gap-4 mb-5">
            <h3 className="text-xl font-semibold text-gray-50">Live agent scores</h3>
            <span className="text-xs text-gray-500">{dashboard?.total_agents ?? 0} agents from live/demo escrow records</span>
          </div>
          {loading ? (
            <div className="flex items-center text-gray-400"><Loader2 className="h-5 w-5 animate-spin mr-2" /> Loading risk data…</div>
          ) : topAgents.length === 0 ? (
            <div className="text-gray-400">No escrow agents found yet. Create an escrow in the demo/sandbox, then recalculate.</div>
          ) : (
            <div className="space-y-3">
              {topAgents.map((agent) => (
                <button
                  key={agent.agent}
                  onClick={() => { setSelectedAgent(agent.agent); scoreAgent(agent.agent); }}
                  className="w-full text-left bg-[#0d0d14] border border-[#1e1e2e] hover:border-amber-500/50 rounded-lg p-4 transition-colors"
                >
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <p className="font-mono text-gray-100">{short(agent.agent)}</p>
                      <p className="text-xs text-gray-500">Escrows: {agent.escrow_count} · Volume: {formatCspr(agent.total_volume_motes)} · Disputes: {pct(agent.dispute_rate)}</p>
                    </div>
                    <span className={`px-3 py-1 rounded-full border text-sm font-semibold ${scoreColor(agent.risk_score)}`}>
                      {agent.risk_score}/100{agent.anomaly_flag ? ' anomaly' : ''}
                    </span>
                  </div>
                  <p className="text-sm text-gray-400 mt-2">{agent.explanation}</p>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 space-y-4">
          <h3 className="text-xl font-semibold text-gray-50">Score any agent</h3>
          <p className="text-sm text-gray-400">Use this as a risk oracle before escrow creation or insurance quote calculation.</p>
          <textarea
            value={selectedAgent}
            onChange={(e) => setSelectedAgent(e.target.value)}
            className="w-full min-h-[110px] p-3 rounded-md bg-[#0d0d14] text-gray-100 border border-[#1e1e2e] focus:ring-2 focus:ring-amber-500 outline-none font-mono text-sm"
          />
          <button
            onClick={() => scoreAgent()}
            disabled={scoreLoading}
            className="w-full h-12 inline-flex items-center justify-center rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold disabled:opacity-50"
          >
            {scoreLoading ? <Loader2 className="h-5 w-5 mr-2 animate-spin" /> : <Gauge className="h-5 w-5 mr-2" />}
            Score agent
          </button>

          {agentScore && (
            <div className={`rounded-lg border p-4 ${scoreColor(agentScore.risk_score)}`}>
              <div className="flex items-center justify-between mb-2">
                <span className="font-semibold">Risk score</span>
                <span className="text-2xl font-bold">{agentScore.risk_score}/100</span>
              </div>
              <p className="text-sm">{agentScore.explanation}</p>
              <div className="grid grid-cols-2 gap-2 text-xs mt-4 text-gray-300">
                <span>Escrows: {agentScore.escrow_count}</span>
                <span>Disputes: {pct(agentScore.dispute_rate)}</span>
                <span>Volume: {formatCspr(agentScore.total_volume_motes)}</span>
                <span>Model: {agentScore.model_version}</span>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <ActionCard title="Before escrow" text="Block or warn on high-risk counterparties before funds are locked." />
        <ActionCard title="Insurance pricing" text="Feed this score into premium-quote so risky jobs pay more into the pool." />
        <ActionCard title="Arbitration routing" text="Route anomalies to VRF-selected arbiters or require stronger evidence up front." />
      </div>
    </div>
  );
};

const Metric: React.FC<{ icon: React.ElementType; label: string; value: string }> = ({ icon: Icon, label, value }) => (
  <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-5">
    <Icon className="h-6 w-6 text-amber-500 mb-3" />
    <p className="text-sm text-gray-400">{label}</p>
    <p className="text-2xl font-bold text-gray-50 mt-1">{value}</p>
  </div>
);

const ActionCard: React.FC<{ title: string; text: string }> = ({ title, text }) => (
  <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-5">
    <ShieldCheck className="h-6 w-6 text-green-400 mb-3" />
    <p className="text-gray-50 font-semibold mb-1">{title}</p>
    <p className="text-sm text-gray-400">{text}</p>
  </div>
);

export default Risk;
