import React, { useEffect, useState, useCallback } from 'react';
import { api, Escrow, EscrowHistoryEntry, CreateEscrowRequest, EscrowActionRequest, EscrowStatus, Estimate } from '../../lib/api';
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

const Select: React.FC<SelectProps> = ({ label, id, options, error, ...props }) => (
  <div className="mb-4">
    <label htmlFor={id} className="block text-sm font-medium text-gray-300 mb-1">
      {label}
    </label>
    <select
      id={id}
      className={`w-full p-3 rounded-md bg-gray-800 text-gray-50 border ${
        error ? 'border-red-500' : 'border-[#1e1e2e]'
      } focus:ring-amber-500 focus:border-amber-500 outline-none`}
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
  const [escrows, setEscrows] = useState<Escrow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEscrow, setSelectedEscrow] = useState<Escrow | null>(null);
  const [history, setHistory] = useState<EscrowHistoryEntry[]>([]);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [isActionModalOpen, setIsActionModalOpen] = useState(false);
  const [actionType, setActionType] = useState<'release' | 'refund' | 'dispute' | null>(null);
  const [actionInitiator, setActionInitiator] = useState('');
  const [actionSignature, setActionSignature] = useState('');
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Pagination and Filtering
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize] = useState(10);
  const [filterStatus, setFilterStatus] = useState<EscrowStatus | 'all'>('all');
  const [totalEscrows, setTotalEscrows] = useState(0);

  const fetchEscrows = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: { limit?: number; offset?: number; status?: EscrowStatus } = {
        limit: pageSize,
        offset: (currentPage - 1) * pageSize,
      };
      if (filterStatus !== 'all') {
        params.status = filterStatus;
      }
      const res = await api.getEscrows(params);
      if (res.error) throw new Error(res.error);
      setEscrows(res.data || []);
      // Assuming API provides total count, if not, we'd need a separate endpoint or estimate
      // For now, let's assume the API returns all matching items and we paginate client-side
      // Or, if the API returns a subset, we'd need a `total_count` field in the response.
      // For this example, let's simulate a total count for pagination.
      // In a real app, `api.getEscrows` would need to return `total_count`
      // For now, we'll just use the length of the fetched data as a proxy for the current page.
      // A proper API would return { data: Escrow[], total_count: number }
      setTotalEscrows(res.data?.length || 0); // This is not accurate for real pagination
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch escrows.');
      console.error('Escrow fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, [currentPage, pageSize, filterStatus]);

  useEffect(() => {
    fetchEscrows();
  }, [fetchEscrows]);

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
      alert(`Escrow created! Deploy Hash: ${res.data?.deploy_hash}`);
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
      const requestBody: EscrowActionRequest = {
        escrow_hash: selectedEscrow.hash,
        initiator_account: actionInitiator,
        signature: actionSignature,
      };

      let res;
      if (actionType === 'release') {
        res = await api.releaseEscrow(requestBody);
      } else if (actionType === 'refund') {
        res = await api.refundEscrow(requestBody);
      } else if (actionType === 'dispute') {
        res = await api.disputeEscrow(requestBody);
      }

      if (res?.error) throw new Error(res.error);
      setActionSuccess(`Action "${actionType}" successful! Deploy Hash: ${res?.data?.deploy_hash}`);
      fetchEscrows(); // Refresh list
      // Optionally, close modal after a delay or on user click
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

  const totalPages = Math.ceil(totalEscrows / pageSize);

  return (
    <div className="space-y-8">
      <h2 className="text-3xl font-bold text-gray-50">Escrow Management</h2>

      {/* Controls */}
      <div className="flex flex-col md:flex-row justify-between items-center gap-4">
        <div className="flex items-center gap-4 w-full md:w-auto">
          <Select
            label="Filter by Status"
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
            className="w-full md:w-48"
          />
          <button
            onClick={() => fetchEscrows()}
            className="p-3 bg-gray-700 hover:bg-gray-600 rounded-md text-gray-200 transition-colors"
            title="Refresh Escrows"
          >
            <RefreshCw size={20} />
          </button>
        </div>
        <button
          onClick={() => setIsCreateModalOpen(true)}
          className="flex items-center px-6 py-3 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg shadow-md transition-colors duration-200 w-full md:w-auto justify-center"
        >
          <PlusCircle className="h-5 w-5 mr-2" />
          Create New Escrow
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
        ) : escrows.length === 0 ? (
          <div className="p-6 text-center text-gray-400">No escrows found.</div>
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
                {escrows.map((escrow) => (
                  <tr key={escrow.hash} className="hover:bg-gray-800 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                      {escrow.hash.substring(0, 8)}...{escrow.hash.substring(escrow.hash.length - 8)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                      {escrow.payer.substring(0, 8)}...
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                      {escrow.payee.substring(0, 8)}...
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                      {escrow.amount} {escrow.token_contract.substring(0, 8)}...
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
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-gray-300">
              <p className="flex items-center">
                <Hash className="h-5 w-5 mr-2 text-amber-500" />
                <strong>Hash:</strong> <span className="ml-2 break-all">{selectedEscrow.hash}</span>
              </p>
              <p className="flex items-center">
                <User className="h-5 w-5 mr-2 text-amber-500" />
                <strong>Payer:</strong> <span className="ml-2 break-all">{selectedEscrow.payer}</span>
              </p>
              <p className="flex items-center">
                <User className="h-5 w-5 mr-2 text-amber-500" />
                <strong>Payee:</strong> <span className="ml-2 break-all">{selectedEscrow.payee}</span>
              </p>
              <p className="flex items-center">
                <DollarSign className="h-5 w-5 mr-2 text-amber-500" />
                <strong>Amount:</strong> <span className="ml-2">{selectedEscrow.amount}</span>
              </p>
              <p className="flex items-center">
                <Coins className="h-5 w-5 mr-2 text-amber-500" />
                <strong>Token:</strong> <span className="ml-2 break-all">{selectedEscrow.token_contract}</span>
              </p>
              <p className="flex items-center">
                {getStatusIcon(selectedEscrow.status)}
                <strong>Status:</strong> <span className="ml-2 capitalize">{selectedEscrow.status}</span>
              </p>
              <p className="flex items-center">
                <Calendar className="h-5 w-5 mr-2 text-amber-500" />
                <strong>Created:</strong> <span className="ml-2">{format(new Date(selectedEscrow.created_at), 'MMM dd, yyyy HH:mm')}</span>
              </p>
              <p className="flex items-center">
                <Calendar className="h-5 w-5 mr-2 text-amber-500" />
                <strong>Updated:</strong> <span className="ml-2">{format(new Date(selectedEscrow.updated_at), 'MMM dd, yyyy HH:mm')}</span>
              </p>
              {selectedEscrow.arbiter && (
                <p className="flex items-center col-span-full">
                  <Scale className="h-5 w-5 mr-2 text-amber-500" />
                  <strong>Arbiter:</strong> <span className="ml-2 break-all">{selectedEscrow.arbiter}</span>
                </p>
              )}
            </div>

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
                disabled={selectedEscrow.status !== 'funded' && selectedEscrow.status !== 'disputed'}
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
                disabled={selectedEscrow.status !== 'funded' && selectedEscrow.status !== 'disputed'}
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
                disabled={selectedEscrow.status !== 'funded'}
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
            <Input
              label="Initiator Account Public Key"
              id="actionInitiator"
              value={actionInitiator}
              onChange={(e) => setActionInitiator(e.target.value)}
              placeholder="e.g., 0123..."
            />
            <Input
              label="Signature (Placeholder)"
              id="actionSignature"
              value={actionSignature}
              onChange={(e) => setActionSignature(e.target.value)}
              placeholder="e.g., 0123..."
            />
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
                className="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg transition-colors flex items-center"
                disabled={actionLoading || !actionInitiator || !actionSignature}
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
  const [payer, setPayer] = useState('');
  const [payee, setPayee] = useState('');
  const [amount, setAmount] = useState('');
  const [tokenContract, setTokenContract] = useState('hash-5dd33e8e79789d386832a80c39006002383fa44dd76ba677cae3279f3a134451'); // Default to contract hash
  const [arbiter, setArbiter] = useState('');
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
        const res = await api.getEstimate(Number(value));
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

    if (!payer || !payee || !amount || !tokenContract) {
      setFormError('All fields are required.');
      return;
    }
    if (isNaN(Number(amount)) || Number(amount) <= 0) {
      setFormError('Amount must be a positive number.');
      return;
    }

    setCreateLoading(true);
    try {
      await onCreate({
        payer,
        payee,
        amount,
        token_contract: tokenContract,
        arbiter: arbiter || undefined,
      });
      // Reset form on successful creation (handled by parent component's onCreate)
      setPayer('');
      setPayee('');
      setAmount('');
      setTokenContract('hash-5dd33e8e79789d386832a80c39006002383fa44dd76ba677cae3279f3a134451');
      setArbiter('');
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
          label="Payer Public Key"
          id="payer"
          value={payer}
          onChange={(e) => setPayer(e.target.value)}
          placeholder="e.g., 0123..."
          required
        />
        <Input
          label="Payee Public Key"
          id="payee"
          value={payee}
          onChange={(e) => setPayee(e.target.value)}
          placeholder="e.g., 0123..."
          required
        />
        <Input
          label="Amount"
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
              Estimated Fee: <span className="ml-1 text-amber-400">{estimate.fee} CSPR</span>
            </p>
            <p className="flex items-center">
              <DollarSign className="h-4 w-4 mr-2 text-gray-500" />
              Total (Amount + Fee): <span className="ml-1 text-amber-400">{estimate.total_with_fee} CSPR</span>
            </p>
          </div>
        )}
        <Input
          label="Token Contract Hash"
          id="tokenContract"
          value={tokenContract}
          onChange={(e) => setTokenContract(e.target.value)}
          placeholder="e.g., hash-..."
          required
        />
        <Input
          label="Arbiter Public Key (Optional)"
          id="arbiter"
          value={arbiter}
          onChange={(e) => setArbiter(e.target.value)}
          placeholder="e.g., 0123..."
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
