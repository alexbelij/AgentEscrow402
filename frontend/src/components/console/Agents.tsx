import React, { useEffect, useState, useCallback } from 'react';
import { api, Agent, Reputation, RegisterIdentityRequest, Identity, Capability } from '../../lib/api';
import {
  Users,
  UserPlus,
  RefreshCw,
  XCircle,
  CheckCircle,
  Star,
  Hash,
  Calendar,
  Info,
  Loader2,
  ShieldCheck,
  DollarSign,
  Scale,
} from 'lucide-react';
import { format } from 'date-fns';

// Reusable Modal Component (from Escrows.tsx)
interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}

const Modal: React.FC<ModalProps> = ({ isOpen, onClose, title, children }) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50 p-4">
      <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center p-4 border-b border-[#1e1e2e]">
          <h3 className="text-xl font-semibold text-gray-50">{title}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-200">
            <XCircle size={24} />
          </button>
        </div>
        <div className="p-6">{children}</div>
      </div>
    </div>
  );
};

// Reusable Input Field (from Escrows.tsx)
interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
  id: string;
  error?: string;
}

const Input: React.FC<InputProps> = ({ label, id, error, ...props }) => (
  <div className="mb-4">
    <label htmlFor={id} className="block text-sm font-medium text-gray-300 mb-1">
      {label}
    </label>
    <input
      id={id}
      className={`w-full p-3 rounded-md bg-gray-800 text-gray-50 border ${
        error ? 'border-red-500' : 'border-[#1e1e2e]'
      } focus:ring-amber-500 focus:border-amber-500 outline-none`}
      {...props}
    />
    {error && <p className="mt-1 text-sm text-red-400">{error}</p>}
  </div>
);

const Agents: React.FC = () => {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [agentReputation, setAgentReputation] = useState<Reputation | null>(null);
  const [agentCapabilities, setAgentCapabilities] = useState<Capability[]>([]);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [isRegisterModalOpen, setIsRegisterModalOpen] = useState(false);

  const fetchAgents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getAgents();
      if (res.error) throw new Error(res.error);
      setAgents(res.data || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch agents.');
      console.error('Agents fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  const handleViewDetails = async (agent: Agent) => {
    setSelectedAgent(agent);
    setIsDetailModalOpen(true);
    setAgentReputation(null);
    setAgentCapabilities([]);

    try {
      const [reputationRes, capabilitiesRes] = await Promise.all([
        api.getReputation(agent.public_key),
        api.getIdentityCapabilities(agent.public_key),
      ]);

      if (reputationRes.error) console.error('Failed to fetch reputation:', reputationRes.error);
      setAgentReputation(reputationRes.data || null);

      if (capabilitiesRes.error) console.error('Failed to fetch capabilities:', capabilitiesRes.error);
      setAgentCapabilities(capabilitiesRes.data || []);
    } catch (err) {
      console.error('Failed to fetch agent details:', err);
    }
  };

  const handleRegisterAgent = async (formData: RegisterIdentityRequest) => {
    setLoading(true); // Use a separate loading for forms if needed
    setError(null);
    try {
      const res = await api.registerIdentity(formData);
      if (res.error) throw new Error(res.error);
      alert(`Agent registered! Deploy Hash: ${res.data?.deploy_hash}`);
      setIsRegisterModalOpen(false);
      fetchAgents(); // Refresh list
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to register agent.');
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status: Agent['status']) => {
    switch (status) {
      case 'active':
        return 'text-green-400';
      case 'inactive':
        return 'text-gray-400';
      case 'suspended':
        return 'text-red-400';
      default:
        return 'text-gray-400';
    }
  };

  return (
    <div className="space-y-8">
      <h2 className="text-3xl font-bold text-gray-50">Agent Management</h2>

      {/* Controls */}
      <div className="flex flex-col md:flex-row justify-between items-center gap-4">
        <button
          onClick={() => fetchAgents()}
          className="p-3 bg-gray-700 hover:bg-gray-600 rounded-md text-gray-200 transition-colors"
          title="Refresh Agents"
        >
          <RefreshCw size={20} />
        </button>
        <button
          onClick={() => setIsRegisterModalOpen(true)}
          className="flex items-center px-6 py-3 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg shadow-md transition-colors duration-200 w-full md:w-auto justify-center"
        >
          <UserPlus className="h-5 w-5 mr-2" />
          Register New Agent
        </button>
      </div>

      {/* Agent List */}
      <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg shadow-md overflow-hidden">
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
          <div className="p-6 text-center text-gray-400">No agents found.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-[#1e1e2e]">
              <thead className="bg-[#1e1e2e]">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Name</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Public Key</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Reputation</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Status</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Registered At</th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1e1e2e]">
                {agents.map((agent) => (
                  <tr key={agent.public_key} className="hover:bg-gray-800 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">{agent.name || 'N/A'}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                      {agent.public_key.length > 20 ? `${agent.public_key.substring(0, 12)}...${agent.public_key.substring(agent.public_key.length - 8)}` : agent.public_key}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300 flex items-center">
                      <Star className="h-4 w-4 text-yellow-400 mr-1" /> {(agent.reputation_score ?? 0).toFixed(2)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <span className={`font-medium ${getStatusColor(agent.status)} capitalize`}>
                        {agent.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                      {format(new Date(agent.registered_at), 'MMM dd, yyyy HH:mm')}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <button
                        onClick={() => handleViewDetails(agent)}
                        className="text-amber-500 hover:text-amber-400 ml-4"
                        title="View Details"
                      >
                        <Info size={20} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Agent Detail Modal */}
      <Modal isOpen={isDetailModalOpen} onClose={() => setIsDetailModalOpen(false)} title="Agent Details">
        {selectedAgent && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-gray-300">
              <p className="flex items-center">
                <UserPlus className="h-5 w-5 mr-2 text-amber-500" />
                <strong>Name:</strong> <span className="ml-2">{selectedAgent.name || 'N/A'}</span>
              </p>
              <p className="flex items-center col-span-full">
                <Hash className="h-5 w-5 mr-2 text-amber-500" />
                <strong>Public Key:</strong> <span className="ml-2 break-all">{selectedAgent.public_key}</span>
              </p>
              <p className="flex items-center">
                <Star className="h-5 w-5 mr-2 text-amber-500" />
                <strong>Reputation Score:</strong> <span className="ml-2">{selectedAgent.reputation_score.toFixed(2)}</span>
              </p>
              <p className="flex items-center">
                <CheckCircle className="h-5 w-5 mr-2 text-amber-500" />
                <strong>Status:</strong> <span className={`ml-2 font-medium capitalize ${getStatusColor(selectedAgent.status)}`}>
                  {selectedAgent.status}
                </span>
              </p>
              <p className="flex items-center">
                <Calendar className="h-5 w-5 mr-2 text-amber-500" />
                <strong>Registered At:</strong> <span className="ml-2">{format(new Date(selectedAgent.registered_at), 'MMM dd, yyyy HH:mm')}</span>
              </p>
            </div>

            <h4 className="text-lg font-semibold text-gray-300 mt-6 mb-3">Reputation Metrics</h4>
            {agentReputation ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-gray-300 bg-gray-800 p-4 rounded-md border border-[#1e1e2e]">
                <p className="flex items-center">
                  <DollarSign className="h-5 w-5 mr-2 text-gray-500" />
                  <strong>Total Escrows:</strong> <span className="ml-2">{agentReputation.total_escrows_completed}</span>
                </p>
                <p className="flex items-center">
                  <CheckCircle className="h-5 w-5 mr-2 text-gray-500" />
                  <strong>Successful Releases:</strong> <span className="ml-2">{agentReputation.successful_releases}</span>
                </p>
                <p className="flex items-center">
                  <Scale className="h-5 w-5 mr-2 text-gray-500" />
                  <strong>Disputes Won:</strong> <span className="ml-2">{agentReputation.disputes_won}</span>
                </p>
                <p className="flex items-center">
                  <XCircle className="h-5 w-5 mr-2 text-gray-500" />
                  <strong>Disputes Lost:</strong> <span className="ml-2">{agentReputation.disputes_lost}</span>
                </p>
                <p className="flex items-center col-span-full">
                  <Calendar className="h-5 w-5 mr-2 text-gray-500" />
                  <strong>Last Updated:</strong> <span className="ml-2">{format(new Date(agentReputation.last_updated), 'MMM dd, yyyy HH:mm')}</span>
                </p>
              </div>
            ) : (
              <p className="text-gray-400">No detailed reputation data available.</p>
            )}

            <h4 className="text-lg font-semibold text-gray-300 mt-6 mb-3">Capabilities</h4>
            {agentCapabilities.length > 0 ? (
              <ul className="space-y-2 bg-gray-800 p-4 rounded-md border border-[#1e1e2e]">
                {agentCapabilities.map((cap, index) => (
                  <li key={index} className="flex items-center text-gray-300">
                    <ShieldCheck className="h-5 w-5 mr-2 text-green-500" />
                    <span className="font-medium">{cap.capability}</span>
                    <span className="ml-auto text-gray-400 text-sm">
                      Delegated by: {(cap.delegated_by || '').substring(0, 8)}... (Expires: {cap.expires_at ? format(new Date(cap.expires_at), 'MMM dd, yyyy') : 'N/A'})
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-gray-400">No specific capabilities delegated to this agent.</p>
            )}
          </div>
        )}
      </Modal>

      {/* Register Agent Modal */}
      <RegisterAgentModal
        isOpen={isRegisterModalOpen}
        onClose={() => setIsRegisterModalOpen(false)}
        onRegister={handleRegisterAgent}
      />
    </div>
  );
};

// Register Agent Modal Component
interface RegisterAgentModalProps {
  isOpen: boolean;
  onClose: () => void;
  onRegister: (data: RegisterIdentityRequest) => void;
}

const RegisterAgentModal: React.FC<RegisterAgentModalProps> = ({ isOpen, onClose, onRegister }) => {
  const [agentId, setAgentId] = useState('demo-agent-001');
  const [publicKey, setPublicKey] = useState('0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef');
  const [didHash, setDidHash] = useState('b'.repeat(64));
  const [formError, setFormError] = useState<string | null>(null);
  const [registerLoading, setRegisterLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (!agentId || !publicKey || !didHash) {
      setFormError('Agent ID, public key and DID document hash are required.');
      return;
    }
    if (!/^[0-9a-fA-F]{64}$/.test(didHash)) {
      setFormError('DID document hash must be exactly 64 hex characters.');
      return;
    }

    setRegisterLoading(true);
    try {
      await onRegister({ agent_id: agentId, public_key: publicKey, did_document_hash: didHash });
      setAgentId('demo-agent-001');
      setPublicKey('0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef');
      setDidHash('b'.repeat(64));
      setFormError(null);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to register agent.');
    } finally {
      setRegisterLoading(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Register New Agent Identity">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3 text-sm text-blue-100">
          Backend expects DID-style identity fields: <span className="font-mono">agent_id</span>, <span className="font-mono">public_key</span>, <span className="font-mono">did_document_hash</span>.
          If the optional identity contract is not configured, the demo stores it in the local registry and returns that mode explicitly.
        </div>
        <Input
          label="Agent ID"
          id="agentId"
          value={agentId}
          onChange={(e) => setAgentId(e.target.value)}
          placeholder="e.g., agent-compute-gpt4"
          required
        />
        <Input
          label="Agent Public Key"
          id="agentPublicKey"
          value={publicKey}
          onChange={(e) => setPublicKey(e.target.value)}
          placeholder="64-char hex public key"
          required
        />
        <Input
          label="DID Document Hash"
          id="didDocumentHash"
          value={didHash}
          onChange={(e) => setDidHash(e.target.value)}
          placeholder="64-char hex hash"
          required
        />

        {formError && (
          <div className="text-red-500 bg-red-900/20 border border-red-700 rounded-lg p-3 mb-4 flex items-center">
            <XCircle className="h-5 w-5 mr-2" />
            <p>{formError}</p>
          </div>
        )}

        <div className="flex justify-end gap-3 mt-6">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg transition-colors"
            disabled={registerLoading}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg transition-colors flex items-center"
            disabled={registerLoading}
          >
            {registerLoading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
            Register Identity
          </button>
        </div>
      </form>
    </Modal>
  );
};

export default Agents;
