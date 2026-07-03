import React, { useEffect, useState, useCallback } from 'react';
import { api, Agent, Reputation } from '../../lib/api';
import {
  ShieldAlert,
  Users,
  Star,
  RefreshCw,
  XCircle,
  Loader2,
  AlertTriangle,
  CheckCircle,
  Info,
} from 'lucide-react';

interface AgentRisk extends Agent {
  reputation_details?: Reputation | null;
}

const Risk: React.FC = () => {
  const [agents, setAgents] = useState<AgentRisk[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAgentData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const agentsRes = await api.getAgents();
      if (agentsRes.error) throw new Error(agentsRes.error);

      const fetchedAgents: AgentRisk[] = agentsRes.data || [];

      const agentsWithReputation = await Promise.all(
        fetchedAgents.map(async (agent) => {
          try {
            const reputationRes = await api.getReputation(agent.public_key);
            if (reputationRes.error) {
              console.warn(`Failed to fetch reputation for ${agent.public_key}: ${reputationRes.error}`);
              return { ...agent, reputation_details: undefined };
            }
            return { ...agent, reputation_details: reputationRes.data };
          } catch (repError) {
            console.warn(`Error fetching reputation for ${agent.public_key}:`, repError);
            return { ...agent, reputation_details: undefined };
          }
        })
      );
      setAgents(agentsWithReputation);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch agent risk data.');
      console.error('Risk data fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAgentData();
  }, [fetchAgentData]);

  const getRiskLevel = (score: number): { level: string; color: string; icon: React.ElementType } => {
    if (score >= 80) return { level: 'Low Risk', color: 'bg-green-500', icon: CheckCircle };
    if (score >= 50) return { level: 'Moderate Risk', color: 'bg-yellow-500', icon: AlertTriangle };
    return { level: 'High Risk', color: 'bg-red-500', icon: XCircle };
  };

  return (
    <div className="space-y-8">
      <h2 className="text-3xl font-bold text-gray-50">Agent Risk Assessment</h2>

      <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 shadow-md">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-xl font-semibold text-gray-300 flex items-center">
            <ShieldAlert className="h-6 w-6 mr-2 text-amber-500" />
            Agent Risk Overview
          </h3>
          <button
            onClick={fetchAgentData}
            className="p-2 bg-gray-700 hover:bg-gray-600 rounded-md text-gray-200 transition-colors"
            title="Refresh Data"
          >
            <RefreshCw size={20} />
          </button>
        </div>

        {loading ? (
          <div className="flex justify-center items-center h-64">
            <Loader2 className="animate-spin h-10 w-10 text-amber-500" />
          </div>
        ) : error ? (
          <div className="text-red-500 bg-red-900/20 border border-red-700 rounded-lg p-4 m-4 flex items-center">
            <XCircle className="h-6 w-6 mr-2" />
            <p>Error: {error}</p>
          </div>
        ) : agents.length === 0 ? (
          <div className="p-6 text-center text-gray-400">No agents found to assess risk.</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {agents.map((agent) => {
              const { level, color, icon: RiskIcon } = getRiskLevel(agent.reputation_score);
              return (
                <div key={agent.public_key} className="bg-gray-800 border border-[#1e1e2e] rounded-lg p-5 shadow-sm">
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="text-lg font-semibold text-gray-50">{agent.name || 'Unnamed Agent'}</h4>
                    <RiskIcon className={`h-6 w-6 ${color.replace('bg-', 'text-')}`} />
                  </div>
                  <p className="text-gray-400 text-sm mb-2 break-all">
                    Public Key: {agent.public_key.substring(0, 10)}...{agent.public_key.substring(agent.public_key.length - 8)}
                  </p>
                  <div className="mb-3">
                    <p className="text-gray-300 flex items-center mb-1">
                      <Star className="h-4 w-4 text-yellow-400 mr-2" />
                      Reputation Score: <span className="font-bold ml-1">{(agent.reputation_score ?? 0).toFixed(2)}</span>
                    </p>
                    <div className="w-full bg-gray-700 rounded-full h-2.5">
                      <div
                        className={`h-2.5 rounded-full ${color}`}
                        style={{ width: `${Math.min(100, Math.max(0, agent.reputation_score))}%` }}
                      ></div>
                    </div>
                    <p className={`text-sm font-medium mt-1 ${color.replace('bg-', 'text-')}`}>{level}</p>
                  </div>
                  {agent.reputation_details ? (
                    <div className="text-xs text-gray-500 space-y-1">
                      <p>Total Escrows: {agent.reputation_details.total_escrows_completed}</p>
                      <p>Successful Releases: {agent.reputation_details.successful_releases}</p>
                      <p>Disputes Lost: {agent.reputation_details.disputes_lost}</p>
                    </div>
                  ) : (
                    <p className="text-xs text-gray-500 flex items-center">
                      <Info className="h-3 w-3 mr-1" /> No detailed reputation.
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default Risk;
