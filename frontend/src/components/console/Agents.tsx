import React, { useEffect, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { api, Agent, Reputation, RegisterIdentityRequest, Identity, AgentCapabilities, DelegationRecord } from '../../lib/api';
import { generateDemoKeypair, signDemoMessage, sha256Hex } from '../../lib/demoSigner';
import { useToast } from '../../lib/toast';
import { useSigner } from '../../lib/signer';
import ExplorerLink from './ExplorerLink';
import EmptyState from './EmptyState';
import { SkeletonTable } from './Skeleton';
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
  KeyRound,
  Copy,
  Check,
} from 'lucide-react';
import { format } from 'date-fns';

/** Tiny inline copy-to-clipboard button with a brief ✓ confirmation. */
const CopyButton: React.FC<{ text: string }> = ({ text }) => {
  const [copied, setCopied] = React.useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <button
      type="button"
      onClick={handleCopy}
      className="inline-flex items-center justify-center ml-1.5 p-1 rounded hover:bg-gray-700 text-gray-500 hover:text-gray-300 transition-colors shrink-0"
      title="Copy to clipboard"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-green-400" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
};

// Reusable Modal Component (from Escrows.tsx)
interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}

const Modal: React.FC<ModalProps> = ({ isOpen, onClose, title, children }) => {
  if (!isOpen) return null;

  // Portalled to <body>: see identical comment in Escrows.tsx's Modal — the
  // page's own `space-y-8` sibling-margin utility was otherwise pushing this
  // "fixed inset-0" overlay ~32px down from the real viewport top.
  return createPortal(
    <div className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50 p-4">
      <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg shadow-xl w-full max-w-3xl max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center p-4 border-b border-[#1e1e2e]">
          <h3 className="text-xl font-semibold text-gray-50">{title}</h3>
          <button onClick={onClose} aria-label="Close dialog" className="text-gray-400 hover:text-gray-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ae-accent-bright rounded">
            <XCircle size={24} />
          </button>
        </div>
        <div className="p-6">{children}</div>
      </div>
    </div>,
    document.body,
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
  const toast = useToast();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [agentReputation, setAgentReputation] = useState<Reputation | null>(null);
  const [agentCapabilities, setAgentCapabilities] = useState<AgentCapabilities | null>(null);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [isRegisterModalOpen, setIsRegisterModalOpen] = useState(false);
  const [isDelegateModalOpen, setIsDelegateModalOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'inactive' | 'suspended'>('all');
  const [onlyMine, setOnlyMine] = useState(false);
  const { activePublicKey } = useSigner();

  const fetchAgents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getAgents();
      if (res.error) throw new Error(res.error);
      setAgents(res.data || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch agents.');
      if (import.meta.env.DEV) console.error('Agents fetch error:', err);
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
    setAgentCapabilities(null);

    try {
      const [reputationRes, capabilitiesRes] = await Promise.all([
        api.getReputation(agent.public_key),
        api.getIdentityCapabilities(agent.public_key),
      ]);

      if (reputationRes.error && import.meta.env.DEV) console.error('Failed to fetch reputation:', reputationRes.error);
      setAgentReputation(reputationRes.data || null);

      if (capabilitiesRes.error && import.meta.env.DEV) console.error('Failed to fetch capabilities:', capabilitiesRes.error);
      setAgentCapabilities(capabilitiesRes.data || null);
    } catch (err) {
      if (import.meta.env.DEV) console.error('Failed to fetch agent details:', err);
    }
  };

  const handleRegisterAgent = async (formData: RegisterIdentityRequest) => {
    setLoading(true); // Use a separate loading for forms if needed
    setError(null);
    try {
      const res = await api.registerIdentity(formData);
      if (res.error) throw new Error(res.error);
      toast.success(`Agent registered — deploy hash ${res.data?.deploy_hash}`);
      setIsRegisterModalOpen(false);
      fetchAgents(); // Refresh list
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to register agent.');
    } finally {
      setLoading(false);
    }
  };

  const filteredAgents = (statusFilter === 'all' ? agents : agents.filter((agent) => agent.status === statusFilter)).filter(
    (agent) => !onlyMine || !activePublicKey || agent.public_key === activePublicKey,
  );

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
      <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4 text-sm text-blue-100 leading-relaxed">
        <strong>What this section is for:</strong> agent identities bind a service agent to a public key, DID document hash, capabilities and reputation. The list is fetched from the live identity/reputation API. If the optional on-chain identity registry is not configured, the backend labels registrations as <span className="font-mono">local_registry</span> instead of pretending they were contract writes. Use the detail icon to inspect reputation and delegated capabilities before trusting an agent.
      </div>

      {/* Controls */}
      <div className="flex flex-row items-center justify-between gap-2 sm:gap-4">
        <div className="flex items-center gap-2 sm:gap-4 min-w-0">
          <button
            onClick={() => fetchAgents()}
            className="h-12 w-12 shrink-0 inline-flex items-center justify-center bg-gray-700 hover:bg-gray-600 rounded-md text-gray-200 transition-colors"
            title="Refresh Agents"
          >
            <RefreshCw size={20} />
          </button>
          <select
            aria-label="Filter agents by status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as any)}
            className="h-12 w-36 sm:w-44 px-3 rounded-md bg-[#0d0d14] text-gray-50 border border-[#1e1e2e] focus:ring-2 focus:ring-amber-500 focus:border-amber-500 outline-none"
          >
            <option value="all">All statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="suspended">Suspended</option>
          </select>
          <label
            className={`hidden sm:flex h-12 items-center gap-2 px-3 rounded-md border text-sm shrink-0 whitespace-nowrap transition-colors ${
              !activePublicKey
                ? 'border-[#1e1e2e] text-gray-600 cursor-not-allowed'
                : onlyMine
                ? 'border-amber-500/40 bg-amber-500/10 text-amber-200 cursor-pointer'
                : 'border-[#1e1e2e] text-gray-400 hover:text-gray-200 cursor-pointer'
            }`}
            title={!activePublicKey ? 'Connect a wallet or use the demo signer to filter by identity' : undefined}
          >
            <input
              type="checkbox"
              checked={onlyMine}
              disabled={!activePublicKey}
              onChange={(e) => setOnlyMine(e.target.checked)}
              className="accent-amber-500"
            />
            Only mine
          </label>
        </div>
        <button
          onClick={() => setIsDelegateModalOpen(true)}
          className="h-12 shrink-0 flex items-center px-3 sm:px-6 bg-gray-800 hover:bg-gray-700 border border-[#1e1e2e] text-gray-200 font-semibold rounded-lg shadow-md transition-colors duration-200 justify-center text-sm sm:text-base"
          title="Sign and record a real capability delegation between two demo identities"
        >
          <KeyRound className="h-5 w-5 mr-2" />
          Delegate Capability
        </button>
        <button
          onClick={() => setIsRegisterModalOpen(true)}
          className="h-12 shrink-0 flex items-center px-3 sm:px-6 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg shadow-md transition-colors duration-200 justify-center text-sm sm:text-base"
          title="Register a DID-style agent identity"
        >
          <UserPlus className="h-5 w-5 mr-2" />
          Register Agent
        </button>
      </div>

      {/* Agent List */}
      <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg shadow-md overflow-hidden">
        {loading ? (
          <div className="p-6">
            <SkeletonTable rows={6} />
          </div>
        ) : error ? (
          <div className="text-red-500 bg-red-900/20 border border-red-700 rounded-lg p-4 m-4 flex items-center">
            <XCircle className="h-6 w-6 mr-2" />
            <p>Error: {error}</p>
          </div>
        ) : filteredAgents.length === 0 ? (
          <EmptyState
            title="No agents registered"
            description="Register an agent via the API or the wallet to see it here."
          />
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
                {filteredAgents.map((agent) => (
                  <tr key={agent.public_key} className="hover:bg-gray-800 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300 max-w-[160px] truncate" title={agent.name || 'N/A'}>
                      <span className="inline-flex items-center gap-1">
                        <span className="truncate">{agent.name || 'N/A'}</span>
                        {agent.name && agent.name.length > 20 && <CopyButton text={agent.name} />}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                      <span className="inline-flex items-center gap-0.5">
                        <ExplorerLink value={agent.public_key}>
                          {agent.public_key.length > 20 ? `${agent.public_key.substring(0, 12)}…${agent.public_key.substring(agent.public_key.length - 8)}` : agent.public_key}
                        </ExplorerLink>
                        <CopyButton text={agent.public_key} />
                      </span>
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
              <div className="col-span-full">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">
                  <Hash className="h-4 w-4 text-amber-500" /> Public Key
                </div>
                <div className="flex items-center gap-1 font-mono text-sm text-gray-300">
                  <ExplorerLink value={selectedAgent.public_key}>
                    <span className="break-all">{selectedAgent.public_key}</span>
                  </ExplorerLink>
                  <CopyButton text={selectedAgent.public_key} />
                </div>
              </div>
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
            {agentCapabilities && agentCapabilities.total > 0 ? (
              <ul className="space-y-2 bg-gray-800 p-4 rounded-md border border-[#1e1e2e]">
                {agentCapabilities.own_capabilities.map((cap, index) => (
                  <li key={`own-${index}`} className="flex items-center text-gray-300">
                    <ShieldCheck className="h-5 w-5 mr-2 text-green-500" />
                    <span className="font-medium">{cap}</span>
                    <span className="ml-auto text-gray-400 text-sm">Own capability</span>
                  </li>
                ))}
                {agentCapabilities.delegated_capabilities.map((cap, index) => (
                  <li key={`delegated-${index}`} className="flex items-center text-gray-300">
                    <KeyRound className="h-5 w-5 mr-2 text-sky-400" />
                    <span className="font-medium">{cap}</span>
                    <span className="ml-auto text-gray-400 text-sm">Delegated to this agent</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-gray-400">No capabilities registered or delegated to this agent.</p>
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

      {/* Delegate Capability Modal */}
      <DelegateCapabilityModal
        isOpen={isDelegateModalOpen}
        onClose={() => setIsDelegateModalOpen(false)}
        onDelegated={fetchAgents}
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

// Delegate Capability Modal Component
//
// Capability delegation requires a genuine Ed25519 signature from the
// delegator's registered private key (server/agent_identity.py verifies it
// cryptographically) — this console never holds the private key for an
// arbitrary existing agent, so this flow generates two fresh local demo
// keypairs, registers both as agent identities, then signs and submits a
// real delegation between them. This is a self-contained demonstration of
// the feature, not a way to delegate rights *from* an arbitrary agent
// already in the list above.
interface DelegateCapabilityModalProps {
  isOpen: boolean;
  onClose: () => void;
  onDelegated: () => void;
}

const CAPABILITY_PRESETS = [
  'urn:escrow:release',
  'urn:escrow:refund',
  'urn:escrow:dispute',
  'urn:insurance:claim',
];

const DelegateCapabilityModal: React.FC<DelegateCapabilityModalProps> = ({ isOpen, onClose, onDelegated }) => {
  const [capabilityUri, setCapabilityUri] = useState(CAPABILITY_PRESETS[0]);
  const [durationHours, setDurationHours] = useState('24');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DelegationRecord | null>(null);

  const reset = () => {
    setCapabilityUri(CAPABILITY_PRESETS[0]);
    setDurationHours('24');
    setError(null);
    setResult(null);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const handleRun = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      // 1. Generate two fresh, local-only demo keypairs.
      const delegator = generateDemoKeypair();
      const delegatee = generateDemoKeypair();
      const delegatorId = `demo-delegator-${delegator.publicKeyHex.slice(0, 8)}`;
      const delegateeId = `demo-delegatee-${delegatee.publicKeyHex.slice(0, 8)}`;

      // 2. Register both as agent identities so the backend recognizes them.
      const regA = await api.registerIdentity({ agent_id: delegatorId, public_key: delegator.publicKeyHex, did_document_hash: 'a'.repeat(64) });
      if (regA.error) throw new Error(`Failed to register delegator identity: ${regA.error}`);
      const regB = await api.registerIdentity({ agent_id: delegateeId, public_key: delegatee.publicKeyHex, did_document_hash: 'b'.repeat(64) });
      if (regB.error) throw new Error(`Failed to register delegatee identity: ${regB.error}`);

      // 3. Build the canonical delegation message and sign it for real with
      // the delegator's freshly generated private key (never sent to the backend).
      const expiryTimestamp = Math.floor(Date.now() / 1000) + Number(durationHours) * 3600;
      const delegationMsg = `${delegatorId}:${delegateeId}:${capabilityUri}:${expiryTimestamp}`;
      const msgHashHex = sha256Hex(delegationMsg);
      const signature = signDemoMessage(msgHashHex, delegator.privateKeyHex);

      // 4. Submit the delegation; the backend independently re-derives the
      // same hash and verifies the signature against the delegator's
      // registered public key before recording it.
      const res = await api.delegateIdentity({
        delegator_id: delegatorId,
        delegatee_id: delegateeId,
        capability_uri: capabilityUri,
        expiry_timestamp: expiryTimestamp,
        signature,
      });
      if (res.error) throw new Error(res.error);
      setResult(res.data || null);
      onDelegated();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delegation failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="Delegate a Capability">
      <div className="space-y-4">
        <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3 text-sm text-blue-100">
          This generates two fresh Ed25519 keypairs locally in your browser (never your Casper wallet), registers them as
          demo agent identities, then signs a real delegation message with the delegator's private key. The backend
          independently verifies that signature cryptographically — it is not a hardcoded demo bypass.
        </div>

        <label className="space-y-2 block">
          <span className="text-sm font-medium text-gray-300">Capability URI</span>
          <select
            value={capabilityUri}
            onChange={(e) => setCapabilityUri(e.target.value)}
            className="w-full p-3 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] focus:ring-amber-500 focus:border-amber-500 outline-none"
          >
            {CAPABILITY_PRESETS.map((cap) => (
              <option key={cap} value={cap}>{cap}</option>
            ))}
          </select>
        </label>

        <Input
          label="Expires in (hours)"
          id="delegationDurationHours"
          type="number"
          min="1"
          value={durationHours}
          onChange={(e) => setDurationHours(e.target.value)}
        />

        {error && (
          <div className="text-red-500 bg-red-900/20 border border-red-700 rounded-lg p-3 flex items-center">
            <XCircle className="h-5 w-5 mr-2" />
            <p>{error}</p>
          </div>
        )}

        {result && (
          <div className="text-emerald-300 bg-emerald-900/20 border border-emerald-700 rounded-lg p-3 space-y-1 text-sm">
            <p className="flex items-center"><CheckCircle className="h-5 w-5 mr-2" /> Delegation recorded and signature verified.</p>
            <p className="font-mono break-all">{result.delegator_id} → {result.delegatee_id}</p>
            <p>Capability: <span className="font-mono">{result.capability_uri}</span></p>
            <p className="flex items-center flex-wrap gap-x-2">
              <span>Mode: <span className="font-mono">{result.mode}</span> · Deploy hash: <span className="font-mono">{result.deploy_hash}</span></span>
              {result.deploy_hash && <CopyButton text={result.deploy_hash} />}
            </p>
          </div>
        )}

        <div className="flex justify-end gap-3 mt-6">
          <button type="button" onClick={handleClose} className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg transition-colors" disabled={loading}>
            Close
          </button>
          <button
            type="button"
            onClick={handleRun}
            className="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg transition-colors flex items-center"
            disabled={loading}
          >
            {loading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
            Generate identities & sign delegation
          </button>
        </div>
      </div>
    </Modal>
  );
};

export default Agents;
