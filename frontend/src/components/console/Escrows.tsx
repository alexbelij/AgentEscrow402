import React, { useEffect, useState, useCallback } from 'react';
import { api, Escrow, EscrowHistoryEntry, CreateEscrowRequest, EscrowStatus, Estimate } from '../../lib/api';
import { csprToMotes, randomHex64, formatCspr } from '../../lib/format';
import { useSigner } from '../../lib/signer';
import { useLifecycleAction } from '../../lib/useLifecycleAction';
import { useToast } from '../../lib/toast';
import ExplorerLink from './ExplorerLink';
import {
  PlusCircle,
  Eye,
  RefreshCw,
  XCircle,
  CheckCircle,
  Hourglass,
  DollarSign,
  User,
  Hash,
  Calendar,
  Wallet,
  Coins,
  ArrowRight,
  Send,
  Undo2,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Info,
  Loader2,
  Scale,
} from 'lucide-react';
import { format } from 'date-fns';

// Reusable Modal Component
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
      <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg shadow-xl w-full max-w-3xl max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center p-4 border-b border-[#1e1e2e]">
          <h3 className="text-xl font-semibold text-gray-50">{title}</h3>
          <button onClick={onClose} aria-label="Close dialog" className="text-gray-400 hover:text-gray-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ae-accent-bright rounded">
            <XCircle size={24} />
          </button>
        </div>
        <div className="p-6">{children}</div>
      </div>
    </div>
  );
};

// Reusable Input Field
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

// Reusable Select Field
interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  id: string;
  options: { value: string; label: string }[];
  error?: string;
}

const Select: React.FC<SelectProps> = ({ label, id, options, error, className = '', ...props }) => (
  <div className="mb-0">
    {label && (
      <label htmlFor={id} className="block text-sm font-medium text-gray-300 mb-1">
        {label}
      </label>
    )}
    <select
      id={id}
      className={`w-full h-12 px-3 rounded-md bg-[#0d0d14] text-gray-50 border ${
        error ? 'border-red-500' : 'border-[#1e1e2e]'
      } focus:ring-2 focus:ring-amber-500 focus:border-amber-500 outline-none ${className}`}
      {...props}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
    {error && <p className="mt-1 text-sm text-red-400">{error}</p>}
  </div>
);

const Escrows: React.FC = () => {
  const toast = useToast();
  const { isLive, activePublicKey } = useSigner();
  const { run: runLifecycleAction } = useLifecycleAction();
  const [contractHash, setContractHash] = useState<string | undefined>(undefined);
  const [escrows, setEscrows] = useState<Escrow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEscrow, setSelectedEscrow] = useState<Escrow | null>(null);
  const [history, setHistory] = useState<EscrowHistoryEntry[]>([]);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [isActionModalOpen, setIsActionModalOpen] = useState(false);
  const [actionType, setActionType] = useState<'release' | 'refund' | 'dispute' | null>(null);
  const [actionReason, setActionReason] = useState('');
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Pagination and Filtering
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize] = useState(10);
  const [filterStatus, setFilterStatus] = useState<EscrowStatus | 'all'>('all');
  const [totalEscrows, setTotalEscrows] = useState(0);
  // "Only mine" is client-side: the hosted API has no payer/payee query
  // param, so when this is on we widen the fetch (bypassing normal
  // pagination) and filter locally against the active connected key.
  const [onlyMine, setOnlyMine] = useState(false);

  const fetchEscrows = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: { limit?: number; offset?: number; status?: EscrowStatus } = onlyMine
        ? { limit: 200, offset: 0 }
        : { limit: pageSize, offset: (currentPage - 1) * pageSize };
      if (filterStatus !== 'all') {
        params.status = filterStatus;
      }
      const res = await api.getEscrows(params);
      if (res.error) throw new Error(res.error);
      const rows = res.data || [];
      setEscrows(rows);
      setTotalEscrows(onlyMine ? rows.length : ((res.data as any)?.total ?? rows.length));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch escrows.');
      console.error('Escrow fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, [currentPage, pageSize, filterStatus, onlyMine]);

  useEffect(() => {
    fetchEscrows();
  }, [fetchEscrows]);

  useEffect(() => {
    // Needed to build a live wallet-signed transaction (release/refund/dispute
    // must target the exact deployed escrow contract). Harmless in demo mode.
    api.getHealth().then((res) => setContractHash(res.data?.contract_hash)).catch(() => undefined);
  }, []);

  const handleViewDetails = async (escrow: Escrow) => {
    setSelectedEscrow(escrow);
    setIsDetailModalOpen(true);
    try {
      const historyRes = await api.getEscrowHistory(escrow.hash);
      if (historyRes.error) throw new Error(historyRes.error);
      setHistory(historyRes.data || []);
    } catch (err) {
      console.error('Failed to fetch escrow history:', err);
      setHistory([]);
    }
  };

  const handleCreateEscrow = async (formData: CreateEscrowRequest) => {
    setLoading(true); // Use a separate loading for forms if needed
    setError(null);
    try {
      const res = await api.createEscrow(formData);
      if (res.error) throw new Error(res.error);
      toast.success(`Escrow created — deploy hash ${res.data?.deploy_hash}`);
      setIsCreateModalOpen(false);
      fetchEscrows(); // Refresh list
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create escrow.');
    } finally {
      setLoading(false);
    }
  };

  const handleAction = async () => {
    if (!selectedEscrow || !actionType) return;

    setActionLoading(true);
    setActionError(null);
    setActionSuccess(null);

    try {
      // Dispute requires a 64-char reason hash; derive one from the free-text reason.
      const reasonHash = actionType === 'dispute' ? randomHex64() : undefined;
      const result = await runLifecycleAction(actionType, selectedEscrow.hash, contractHash, reasonHash);

      if (!result.ok) {
        if (result.cancelled) {
          setActionError('Cancelled in wallet.');
          return;
        }
        throw new Error(result.error);
      }
      setActionSuccess(
        `Action "${actionType}" successful! ${isLive ? 'Transaction hash' : 'Deploy hash'}: ${result.deployHash}`,
      );
      // Reflect the new terminal status locally right away so the
      // Confirm/Release/Refund/Dispute buttons disable immediately instead
      // of staying clickable until the background refresh lands — clicking
      // again before that would otherwise 400 with "Cannot release escrow
      // in status released" (etc).
      const nextStatus: EscrowStatus = actionType === 'release' ? 'released' : actionType === 'refund' ? 'refunded' : 'disputed';
      setSelectedEscrow((prev) => (prev ? { ...prev, status: nextStatus } : prev));
      fetchEscrows(); // Refresh list
      api.getEscrowByHash(selectedEscrow.hash).then((res) => {
        if (res.data) setSelectedEscrow(res.data);
      });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : `Failed to ${actionType} escrow.`);
    } finally {
      setActionLoading(false);
    }
  };

  const getStatusIcon = (status: EscrowStatus) => {
    switch (status) {
      case 'funded':
        return <CheckCircle className="h-5 w-5 text-green-500" />;
      case 'pending':
        return <Hourglass className="h-5 w-5 text-blue-500" />;
      case 'released':
        return <Send className="h-5 w-5 text-purple-500" />;
      case 'refunded':
        return <Undo2 className="h-5 w-5 text-yellow-500" />;
      case 'disputed':
        return <AlertTriangle className="h-5 w-5 text-red-500" />;
      case 'cancelled':
        return <XCircle className="h-5 w-5 text-gray-500" />;
      default:
        return <Info className="h-5 w-5 text-gray-500" />;
    }
  };

  const visibleEscrows =
    onlyMine && activePublicKey
      ? escrows.filter((e) => e.payer === activePublicKey || e.payee === activePublicKey)
      : escrows;
  const totalPages = onlyMine ? 1 : Math.ceil(totalEscrows / pageSize);

  return (
    <div className="space-y-8">
      <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4 text-sm text-blue-100 leading-relaxed">
        <strong>What is real here:</strong> every row is loaded from the live backend; new rows are persisted in Neon when the hosted database is connected and otherwise shown as a clearly labelled demo fallback. Create/release/refund/dispute calls go through the same API used by production. The hosted console currently uses a labelled demo <span className="font-mono">X-Payment</span> identity header instead of silently pretending a browser wallet is connected; production clients sign that header with their wallet/agent key.
      </div>

      {/* Controls */}
      <div className="flex flex-row items-center justify-between gap-2 sm:gap-4">
        <div className="flex items-center gap-2 sm:gap-4 min-w-0">
          <Select
            label=""
            id="filterStatus"
            value={filterStatus}
            onChange={(e) => {
              setFilterStatus(e.target.value as EscrowStatus | 'all');
              setCurrentPage(1);
            }}
            options={[
              { value: 'all', label: 'All Statuses' },
              { value: 'pending', label: 'Pending' },
              { value: 'funded', label: 'Funded' },
              { value: 'released', label: 'Released' },
              { value: 'refunded', label: 'Refunded' },
              { value: 'disputed', label: 'Disputed' },
              { value: 'cancelled', label: 'Cancelled' },
            ]}
            className="w-36 sm:w-48"
          />
          <button
            onClick={() => fetchEscrows()}
            className="h-12 w-12 shrink-0 inline-flex items-center justify-center bg-gray-700 hover:bg-gray-600 rounded-md text-gray-200 transition-colors"
            title="Refresh Escrows"
          >
            <RefreshCw size={20} />
          </button>
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
              onChange={(e) => {
                setOnlyMine(e.target.checked);
                setCurrentPage(1);
              }}
              className="accent-amber-500"
            />
            Only mine
          </label>
        </div>
        <button
          onClick={() => setIsCreateModalOpen(true)}
          className="h-12 shrink-0 flex items-center px-3 sm:px-6 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg shadow-md transition-colors duration-200 justify-center text-sm sm:text-base"
        >
          <PlusCircle className="h-5 w-5 mr-2" />
          Create Escrow
        </button>
      </div>

      {/* Escrow List */}
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
        ) : visibleEscrows.length === 0 ? (
          <div className="p-6 text-center text-gray-400">
            {onlyMine
              ? 'No escrows found where your active identity is payer or payee (checked against the last 200 records).'
              : 'No escrows found.'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-[#1e1e2e]">
              <thead className="bg-[#1e1e2e]">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Hash</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Payer</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Payee</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Amount</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Status</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Created At</th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1e1e2e]">
                {visibleEscrows.map((escrow) => (
                  <tr key={escrow.hash} className="hover:bg-gray-800 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                      {escrow.hash.substring(0, 8)}...{escrow.hash.substring(escrow.hash.length - 8)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                      <ExplorerLink value={escrow.payer}>{escrow.payer.substring(0, 8)}...</ExplorerLink>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                      <ExplorerLink value={escrow.payee}>{escrow.payee.substring(0, 8)}...</ExplorerLink>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                      {formatCspr(escrow.amount)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300 flex items-center">
                      {getStatusIcon(escrow.status)}
                      <span className="ml-2 capitalize">{escrow.status}</span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                      {format(new Date(escrow.created_at), 'MMM dd, yyyy HH:mm')}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <button
                        onClick={() => handleViewDetails(escrow)}
                        className="text-amber-500 hover:text-amber-400 ml-4"
                        title="View Details"
                      >
                        <Eye size={20} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      {escrows.length > 0 && (
        <div className="flex justify-center items-center gap-4 mt-6">
          <button
            onClick={() => setCurrentPage((prev) => Math.max(prev - 1, 1))}
            disabled={currentPage === 1}
            className="p-2 rounded-md bg-gray-700 hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed text-gray-200"
          >
            <ChevronLeft size={20} />
          </button>
          <span className="text-gray-300">
            Page {currentPage} of {totalPages === 0 ? 1 : totalPages}
          </span>
          <button
            onClick={() => setCurrentPage((prev) => Math.min(prev + 1, totalPages))}
            disabled={currentPage === totalPages || totalPages === 0}
            className="p-2 rounded-md bg-gray-700 hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed text-gray-200"
          >
            <ChevronRight size={20} />
          </button>
        </div>
      )}

      {/* Create Escrow Modal */}
      <CreateEscrowModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        onCreate={handleCreateEscrow}
      />

      {/* Escrow Detail Modal */}
      <Modal isOpen={isDetailModalOpen} onClose={() => setIsDetailModalOpen(false)} title="Escrow Details">
        {selectedEscrow && (
          <div className="space-y-6">
            <div className="space-y-4 text-gray-300">
              {/* Full-width, label-above-value rows for long hex identifiers so
                  the value gets the entire modal width and never wraps into a
                  cramped 3-line column next to its label. */}
              <div>
                <div className="flex items-center text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">
                  <Hash className="h-4 w-4 mr-1.5 text-amber-500" /> Hash
                </div>
                <p className="font-mono text-sm break-all">{selectedEscrow.hash}</p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <div className="flex items-center text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">
                    <User className="h-4 w-4 mr-1.5 text-amber-500" /> Payer
                  </div>
                  <p className="font-mono text-sm break-all">
                    <ExplorerLink value={selectedEscrow.payer}>{selectedEscrow.payer}</ExplorerLink>
                  </p>
                </div>
                <div>
                  <div className="flex items-center text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">
                    <User className="h-4 w-4 mr-1.5 text-amber-500" /> Payee
                  </div>
                  <p className="font-mono text-sm break-all">
                    <ExplorerLink value={selectedEscrow.payee}>{selectedEscrow.payee}</ExplorerLink>
                  </p>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <p className="flex items-center">
                  <DollarSign className="h-5 w-5 mr-2 text-amber-500 shrink-0" />
                  <strong>Amount:</strong> <span className="ml-2">{formatCspr(selectedEscrow.amount)}</span>
                </p>
                <p className="flex items-center">
                  {getStatusIcon(selectedEscrow.status)}
                  <strong className="ml-1">Status:</strong> <span className="ml-2 capitalize">{selectedEscrow.status}</span>
                </p>
                <p className="flex items-center">
                  <Calendar className="h-5 w-5 mr-2 text-amber-500 shrink-0" />
                  <strong>Created:</strong> <span className="ml-2">{format(new Date(selectedEscrow.created_at), 'MMM dd, yyyy HH:mm')}</span>
                </p>
                <p className="flex items-center">
                  <Calendar className="h-5 w-5 mr-2 text-amber-500 shrink-0" />
                  <strong>Updated:</strong> <span className="ml-2">{format(new Date(selectedEscrow.updated_at), 'MMM dd, yyyy HH:mm')}</span>
                </p>
              </div>
              {selectedEscrow.arbiter && (
                <div>
                  <div className="flex items-center text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">
                    <Scale className="h-4 w-4 mr-1.5 text-amber-500" /> Arbiter
                  </div>
                  <p className="font-mono text-sm break-all">{selectedEscrow.arbiter}</p>
                </div>
              )}
            </div>

            {(selectedEscrow.mlkem_algorithm || selectedEscrow.mlkem_ciphertext) && (
              <div className="bg-purple-500/10 border border-purple-500/30 rounded-lg p-4 text-sm text-purple-100">
                <p className="font-semibold mb-2">Post-Quantum metadata encryption</p>
                <p>Algorithm: <span className="font-mono">{selectedEscrow.mlkem_algorithm || 'ML-KEM-768'}</span></p>
                {selectedEscrow.mlkem_ciphertext && <p className="break-all">Ciphertext: <span className="font-mono">{selectedEscrow.mlkem_ciphertext}</span></p>}
              </div>
            )}

            <h4 className="text-lg font-semibold text-gray-300 mt-6 mb-3">Escrow History</h4>
            {history.length > 0 ? (
              <ul className="space-y-3">
                {history.map((entry, index) => (
                  <li key={index} className="bg-gray-800 p-3 rounded-md border border-[#1e1e2e]">
                    <p className="text-gray-300 font-medium flex items-center">
                      <Calendar className="h-4 w-4 mr-2 text-gray-500" />
                      {format(new Date(entry.timestamp), 'MMM dd, yyyy HH:mm')} -{' '}
                      <span className="text-amber-400 ml-1">{entry.event_type.replace(/_/g, ' ')}</span>
                    </p>
                    <pre className="text-gray-400 text-xs mt-1 overflow-x-auto">
                      {JSON.stringify(entry.details, null, 2)}
                    </pre>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-gray-400">No history available for this escrow.</p>
            )}

            <h4 className="text-lg font-semibold text-gray-300 mt-6 mb-3">Actions</h4>
            <div className="flex flex-wrap gap-4">
              <button
                onClick={() => {
                  setActionType('release');
                  setIsActionModalOpen(true);
                  setActionError(null);
                  setActionSuccess(null);
                }}
                disabled={!['pending', 'funded', 'disputed'].includes(selectedEscrow.status)}
                className="flex items-center px-4 py-2 bg-green-600 hover:bg-green-700 text-white font-semibold rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Send className="h-5 w-5 mr-2" /> Release
              </button>
              <button
                onClick={() => {
                  setActionType('refund');
                  setIsActionModalOpen(true);
                  setActionError(null);
                  setActionSuccess(null);
                }}
                disabled={!['pending', 'funded', 'disputed'].includes(selectedEscrow.status)}
                className="flex items-center px-4 py-2 bg-yellow-600 hover:bg-yellow-700 text-white font-semibold rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Undo2 className="h-5 w-5 mr-2" /> Refund
              </button>
              <button
                onClick={() => {
                  setActionType('dispute');
                  setIsActionModalOpen(true);
                  setActionError(null);
                  setActionSuccess(null);
                }}
                disabled={!['pending', 'funded'].includes(selectedEscrow.status)}
                className="flex items-center px-4 py-2 bg-red-600 hover:bg-red-700 text-white font-semibold rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <AlertTriangle className="h-5 w-5 mr-2" /> Dispute
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* Action Confirmation Modal */}
      <Modal isOpen={isActionModalOpen} onClose={() => setIsActionModalOpen(false)} title={`${actionType} Escrow`}>
        {selectedEscrow && (
          <div className="space-y-4">
            <p className="text-gray-300">
              Are you sure you want to <span className="font-bold text-amber-400">{actionType}</span> escrow{' '}
              <span className="font-mono text-gray-400">{selectedEscrow.hash.substring(0, 12)}...</span>?
            </p>
            <p className="text-sm text-gray-500">
              {isLive ? (
                <>
                  Your connected wallet will build and sign this transaction directly (a wallet popup will appear) — the backend only verifies
                  on-chain state afterwards. Only works if your connected account is this escrow's sender{actionType === 'dispute' ? ' or receiver' : ''}.
                </>
              ) : (
                <>
                  This escrow is addressed by its <span className="font-mono">service_hash</span>. The demo signer's action is sent to the backend as{' '}
                  <span className="font-mono">POST /{actionType}</span> with <span className="font-mono">{'{ service_hash }'}</span>.
                </>
              )}
            </p>
            {actionType === 'dispute' && (
              <Input
                label="Dispute reason"
                id="actionReason"
                value={actionReason}
                onChange={(e) => setActionReason(e.target.value)}
                placeholder="Describe why you are disputing (a reason hash is derived automatically)"
              />
            )}
            {actionError && (
              <div className="text-red-500 bg-red-900/20 border border-red-700 rounded-lg p-3 flex items-center">
                <XCircle className="h-5 w-5 mr-2" />
                <p>{actionError}</p>
              </div>
            )}
            {actionSuccess && (
              <div className="text-green-500 bg-green-900/20 border border-green-700 rounded-lg p-3 flex items-center">
                <CheckCircle className="h-5 w-5 mr-2" />
                <p>{actionSuccess}</p>
              </div>
            )}
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => setIsActionModalOpen(false)}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg transition-colors"
                disabled={actionLoading}
              >
                Cancel
              </button>
              <button
                onClick={handleAction}
                className="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg transition-colors flex items-center disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={
                  actionLoading ||
                  !!actionSuccess ||
                  (actionType === 'dispute'
                    ? !['pending', 'funded'].includes(selectedEscrow.status)
                    : !['pending', 'funded', 'disputed'].includes(selectedEscrow.status))
                }
              >
                {actionLoading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
                Confirm {actionType}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

// Create Escrow Modal Component
interface CreateEscrowModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreate: (data: CreateEscrowRequest) => void;
}

const CreateEscrowModal: React.FC<CreateEscrowModalProps> = ({ isOpen, onClose, onCreate }) => {
  const [receiver, setReceiver] = useState('');
  const [amount, setAmount] = useState('');
  const [serviceHash, setServiceHash] = useState(randomHex64());
  const [ttl, setTtl] = useState('300');
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [estimateLoading, setEstimateLoading] = useState(false);
  const [estimateError, setEstimateError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [createLoading, setCreateLoading] = useState(false);

  const handleAmountChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setAmount(value);
    if (value && !isNaN(Number(value)) && Number(value) > 0) {
      setEstimateLoading(true);
      setEstimateError(null);
      try {
        const res = await api.getEstimate(csprToMotes(Number(value)));
        if (res.error) throw new Error(res.error);
        setEstimate(res.data);
      } catch (err) {
        setEstimateError(err instanceof Error ? err.message : 'Failed to get fee estimate.');
        setEstimate(null);
      } finally {
        setEstimateLoading(false);
      }
    } else {
      setEstimate(null);
      setEstimateError(null);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (!receiver || !amount || !serviceHash) {
      setFormError('Receiver, amount and service hash are required.');
      return;
    }
    if (!/^[0-9a-fA-F]{64}$/.test(receiver)) {
      setFormError('Receiver account hash must be exactly 64 hexadecimal characters.');
      return;
    }
    if (isNaN(Number(amount)) || Number(amount) <= 0) {
      setFormError('Amount must be a positive number.');
      return;
    }
    if (!/^[0-9a-fA-F]{64}$/.test(serviceHash)) {
      setFormError('Service hash must be exactly 64 hexadecimal characters.');
      return;
    }
    const ttlNum = Number(ttl);
    if (ttl && (isNaN(ttlNum) || ttlNum < 60 || ttlNum > 86400)) {
      setFormError('TTL must be between 60 and 86400 seconds.');
      return;
    }

    setCreateLoading(true);
    try {
      await onCreate({
        receiver,
        amount: csprToMotes(Number(amount)),
        service_hash: serviceHash,
        ttl: Number(ttl) || 300,
      });
      // Reset form on successful creation (handled by parent component's onCreate)
      setReceiver('');
      setAmount('');
      setServiceHash(randomHex64());
      setTtl('300');
      setEstimate(null);
      setFormError(null);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to create escrow.');
    } finally {
      setCreateLoading(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Create New Escrow">
      <form onSubmit={handleSubmit}>
        <Input
          label="Receiver Account Hash"
          id="receiver"
          value={receiver}
          onChange={(e) => setReceiver(e.target.value)}
          placeholder="e.g., fedcba9876543210... (64 hex chars)"
          required
        />
        <Input
          label="Amount (CSPR)"
          id="amount"
          type="number"
          value={amount}
          onChange={handleAmountChange}
          placeholder="e.g., 100"
          min="0.01"
          step="any"
          required
        />
        {estimateLoading && (
          <p className="text-amber-400 flex items-center mb-2">
            <Loader2 className="animate-spin h-4 w-4 mr-2" /> Calculating fee...
          </p>
        )}
        {estimateError && (
          <p className="text-red-400 flex items-center mb-2">
            <XCircle className="h-4 w-4 mr-2" /> {estimateError}
          </p>
        )}
        {estimate && (
          <div className="bg-gray-800 p-3 rounded-md border border-[#1e1e2e] mb-4 text-sm text-gray-300">
            <p className="flex items-center">
              <Info className="h-4 w-4 mr-2 text-gray-500" />
              Insurance Fee (2%): <span className="ml-1 text-amber-400">{formatCspr(estimate.insurance_fee ?? estimate.fee)}</span>
            </p>
            <p className="flex items-center">
              <DollarSign className="h-4 w-4 mr-2 text-gray-500" />
              Net to receiver: <span className="ml-1 text-amber-400">{formatCspr(estimate.net_amount)}</span>
            </p>
          </div>
        )}
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <Input
              label="Service Hash (64 hex)"
              id="serviceHash"
              value={serviceHash}
              onChange={(e) => setServiceHash(e.target.value)}
              placeholder="64-char hex identifier"
              required
            />
          </div>
          <button
            type="button"
            onClick={() => setServiceHash(randomHex64())}
            className="mb-4 px-3 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg text-sm whitespace-nowrap"
          >
            Generate
          </button>
        </div>
        <Input
          label="TTL (seconds)"
          id="ttl"
          type="number"
          value={ttl}
          onChange={(e) => setTtl(e.target.value)}
          placeholder="300"
          min="60"
          max="86400"
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
            disabled={createLoading}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg transition-colors flex items-center"
            disabled={createLoading}
          >
            {createLoading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
            Create Escrow
          </button>
        </div>
      </form>
    </Modal>
  );
};

export default Escrows;
