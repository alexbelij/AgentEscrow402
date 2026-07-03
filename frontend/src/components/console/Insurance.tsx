import React, { useEffect, useState } from 'react';
import { api, InsurancePoolStats, PremiumQuote, DepositInsuranceRequest, ClaimInsuranceRequest } from '../../lib/api';
import {
  Shield,
  DollarSign,
  Coins,
  Activity,
  Calculator,
  Wallet,
  FileText,
  RefreshCw,
  XCircle,
  CheckCircle,
  Loader2,
  Info,
  AlertTriangle,
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

// Reusable Textarea Field
interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  id: string;
  error?: string;
}

const Textarea: React.FC<TextareaProps> = ({ label, id, error, ...props }) => (
  <div className="mb-4">
    <label htmlFor={id} className="block text-sm font-medium text-gray-300 mb-1">
      {label}
    </label>
    <textarea
      id={id}
      rows={3}
      className={`w-full p-3 rounded-md bg-gray-800 text-gray-50 border ${
        error ? 'border-red-500' : 'border-[#1e1e2e]'
      } focus:ring-amber-500 focus:border-amber-500 outline-none`}
      {...props}
    />
    {error && <p className="mt-1 text-sm text-red-400">{error}</p>}
  </div>
);


const Insurance: React.FC = () => {
  const [poolStats, setPoolStats] = useState<InsurancePoolStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [premiumAmount, setPremiumAmount] = useState<number | ''>('');
  const [premiumDuration, setPremiumDuration] = useState<number | ''>(30); // Default 30 days
  const [premiumQuote, setPremiumQuote] = useState<PremiumQuote | null>(null);
  const [premiumLoading, setPremiumLoading] = useState(false);
  const [premiumError, setPremiumError] = useState<string | null>(null);

  const [isDepositModalOpen, setIsDepositModalOpen] = useState(false);
  const [isClaimModalOpen, setIsClaimModalOpen] = useState(false);

  const fetchPoolStats = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getInsurancePoolStats();
      if (res.error) throw new Error(res.error);
      setPoolStats(res.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch insurance pool stats.');
      console.error('Insurance pool stats fetch error:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPoolStats();
  }, []);

  const handleCalculatePremium = async () => {
    if (!premiumAmount || !premiumDuration || premiumAmount <= 0 || premiumDuration <= 0) {
      setPremiumError('Please enter valid amount and duration.');
      setPremiumQuote(null);
      return;
    }

    setPremiumLoading(true);
    setPremiumError(null);
    try {
      const res = await api.getPremiumQuote(premiumAmount, premiumDuration * 24 * 3600); // Convert days to seconds
      if (res.error) throw new Error(res.error);
      setPremiumQuote(res.data);
    } catch (err) {
      setPremiumError(err instanceof Error ? err.message : 'Failed to calculate premium.');
      setPremiumQuote(null);
    } finally {
      setPremiumLoading(false);
    }
  };

  const handleDeposit = async (formData: DepositInsuranceRequest) => {
    setLoading(true); // Use a separate loading for forms if needed
    setError(null);
    try {
      const res = await api.depositInsurance(formData);
      if (res.error) throw new Error(res.error);
      alert(`Deposit successful! Deploy Hash: ${res.data?.deploy_hash}`);
      setIsDepositModalOpen(false);
      fetchPoolStats(); // Refresh stats
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to deposit insurance.');
    } finally {
      setLoading(false);
    }
  };

  const handleClaim = async (formData: ClaimInsuranceRequest) => {
    setLoading(true); // Use a separate loading for forms if needed
    setError(null);
    try {
      const res = await api.claimInsurance(formData);
      if (res.error) throw new Error(res.error);
      alert(`Claim submitted! Deploy Hash: ${res.data?.deploy_hash}`);
      setIsClaimModalOpen(false);
      fetchPoolStats(); // Refresh stats
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit claim.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8">
      <h2 className="text-3xl font-bold text-gray-50">Insurance Protocol</h2>

      {/* Pool Stats */}
      <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 shadow-md">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-xl font-semibold text-gray-300 flex items-center">
            <Shield className="h-6 w-6 mr-2 text-amber-500" />
            Insurance Pool Statistics
          </h3>
          <button
            onClick={fetchPoolStats}
            className="p-2 bg-gray-700 hover:bg-gray-600 rounded-md text-gray-200 transition-colors"
            title="Refresh Pool Stats"
          >
            <RefreshCw size={20} />
          </button>
        </div>
        {loading ? (
          <div className="flex justify-center items-center h-32">
            <Loader2 className="animate-spin h-8 w-8 text-amber-500" />
          </div>
        ) : error ? (
          <div className="text-red-500 bg-red-900/20 border border-red-700 rounded-lg p-4 flex items-center">
            <XCircle className="h-6 w-6 mr-2" />
            <p>Error: {error}</p>
          </div>
        ) : poolStats ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <div className="flex flex-col items-center p-4 bg-gray-800 rounded-md border border-[#1e1e2e]">
              <DollarSign className="h-8 w-8 text-green-500 mb-2" />
              <p className="text-gray-400 text-sm">Total Deposited</p>
              <p className="text-2xl font-bold text-gray-50">{poolStats.total_deposited} CSPR</p>
            </div>
            <div className="flex flex-col items-center p-4 bg-gray-800 rounded-md border border-[#1e1e2e]">
              <Coins className="h-8 w-8 text-red-500 mb-2" />
              <p className="text-gray-400 text-sm">Total Claims Paid</p>
              <p className="text-2xl font-bold text-gray-50">{poolStats.total_claims_paid} CSPR</p>
            </div>
            <div className="flex flex-col items-center p-4 bg-gray-800 rounded-md border border-[#1e1e2e]">
              <Wallet className="h-8 w-8 text-blue-500 mb-2" />
              <p className="text-gray-400 text-sm">Available Funds</p>
              <p className="text-2xl font-bold text-gray-50">{poolStats.available_funds} CSPR</p>
            </div>
            <div className="flex flex-col items-center p-4 bg-gray-800 rounded-md border border-[#1e1e2e]">
              <Activity className="h-8 w-8 text-purple-500 mb-2" />
              <p className="text-gray-400 text-sm">Active Policies</p>
              <p className="text-2xl font-bold text-gray-50">{poolStats.active_policies}</p>
            </div>
          </div>
        ) : (
          <p className="text-gray-400">No pool stats available.</p>
        )}
      </div>

      {/* Premium Calculator */}
      <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 shadow-md">
        <h3 className="text-xl font-semibold text-gray-300 mb-4 flex items-center">
          <Calculator className="h-6 w-6 mr-2 text-amber-500" />
          Premium Calculator
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-end">
          <Input
            label="Escrow Amount (CSPR)"
            id="premiumAmount"
            type="number"
            value={premiumAmount}
            onChange={(e) => setPremiumAmount(Number(e.target.value))}
            placeholder="e.g., 100"
            min="0.01"
            step="any"
            required
          />
          <Input
            label="Duration (Days)"
            id="premiumDuration"
            type="number"
            value={premiumDuration}
            onChange={(e) => setPremiumDuration(Number(e.target.value))}
            placeholder="e.g., 30"
            min="1"
            step="1"
            required
          />
          <button
            onClick={handleCalculatePremium}
            className="flex items-center justify-center px-6 py-3 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg shadow-md transition-colors duration-200"
            disabled={premiumLoading}
          >
            {premiumLoading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
            Calculate Premium
          </button>
        </div>
        {premiumError && (
          <div className="text-red-500 bg-red-900/20 border border-red-700 rounded-lg p-3 mt-4 flex items-center">
            <XCircle className="h-5 w-5 mr-2" />
            <p>{premiumError}</p>
          </div>
        )}
        {premiumQuote && (
          <div className="bg-gray-800 p-4 rounded-md border border-[#1e1e2e] mt-4 text-gray-300">
            <p className="flex items-center mb-2">
              <Info className="h-5 w-5 mr-2 text-gray-500" />
              <strong>Quoted Premium:</strong> <span className="ml-2 text-amber-400">{premiumQuote.premium_amount} CSPR</span>
            </p>
            <p className="flex items-center mb-2">
              <Info className="h-5 w-5 mr-2 text-gray-500" />
              <strong>Fee Rate:</strong> <span className="ml-2">{premiumQuote.fee_rate * 100}%</span>
            </p>
            <p className="flex items-center">
              <Info className="h-5 w-5 mr-2 text-gray-500" />
              <strong>Duration:</strong> <span className="ml-2">{premiumQuote.duration_seconds / (24 * 3600)} days</span>
            </p>
          </div>
        )}
      </div>

      {/* Deposit & Claim Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 shadow-md">
          <h3 className="text-xl font-semibold text-gray-300 mb-4 flex items-center">
            <Wallet className="h-6 w-6 mr-2 text-amber-500" />
            Deposit to Pool
          </h3>
          <p className="text-gray-400 mb-4">Contribute funds to the insurance pool to earn rewards and support the protocol.</p>
          <button
            onClick={() => setIsDepositModalOpen(true)}
            className="flex items-center px-6 py-3 bg-green-600 hover:bg-green-700 text-white font-semibold rounded-lg shadow-md transition-colors duration-200 w-full justify-center"
          >
            <DollarSign className="h-5 w-5 mr-2" />
            Make a Deposit
          </button>
        </div>

        <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 shadow-md">
          <h3 className="text-xl font-semibold text-gray-300 mb-4 flex items-center">
            <FileText className="h-6 w-6 mr-2 text-amber-500" />
            Submit a Claim
          </h3>
          <p className="text-gray-400 mb-4">If an escrow is disputed or failed, submit a claim for insurance payout.</p>
          <button
            onClick={() => setIsClaimModalOpen(true)}
            className="flex items-center px-6 py-3 bg-red-600 hover:bg-red-700 text-white font-semibold rounded-lg shadow-md transition-colors duration-200 w-full justify-center"
          >
            <AlertTriangle className="h-5 w-5 mr-2" />
            File a Claim
          </button>
        </div>
      </div>

      {/* Deposit Modal */}
      <DepositInsuranceModal isOpen={isDepositModalOpen} onClose={() => setIsDepositModalOpen(false)} onDeposit={handleDeposit} />

      {/* Claim Modal */}
      <ClaimInsuranceModal isOpen={isClaimModalOpen} onClose={() => setIsClaimModalOpen(false)} onClaim={handleClaim} />
    </div>
  );
};

// Deposit Insurance Modal Component
interface DepositInsuranceModalProps {
  isOpen: boolean;
  onClose: () => void;
  onDeposit: (data: DepositInsuranceRequest) => void;
}

const DepositInsuranceModal: React.FC<DepositInsuranceModalProps> = ({ isOpen, onClose, onDeposit }) => {
  const [depositorPublicKey, setDepositorPublicKey] = useState('');
  const [amount, setAmount] = useState('');
  const [tokenContract, setTokenContract] = useState('hash-5dd33e8e79789d386832a80c39006002383fa44dd76ba677cae3279f3a134451'); // Default to contract hash
  const [signature, setSignature] = useState(''); // Placeholder
  const [formError, setFormError] = useState<string | null>(null);
  const [depositLoading, setDepositLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (!depositorPublicKey || !amount || !tokenContract || !signature) {
      setFormError('All fields are required.');
      return;
    }
    if (isNaN(Number(amount)) || Number(amount) <= 0) {
      setFormError('Amount must be a positive number.');
      return;
    }

    setDepositLoading(true);
    try {
      await onDeposit({
        depositor_public_key: depositorPublicKey,
        amount,
        token_contract: tokenContract,
        signature,
      });
      setDepositorPublicKey('');
      setAmount('');
      setTokenContract('hash-5dd33e8e79789d386832a80c39006002383fa44dd76ba677cae3279f3a134451');
      setSignature('');
      setFormError(null);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to deposit insurance.');
    } finally {
      setDepositLoading(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Deposit to Insurance Pool">
      <form onSubmit={handleSubmit}>
        <Input
          label="Depositor Public Key"
          id="depositorPublicKey"
          value={depositorPublicKey}
          onChange={(e) => setDepositorPublicKey(e.target.value)}
          placeholder="e.g., 0123..."
          required
        />
        <Input
          label="Amount (CSPR)"
          id="depositAmount"
          type="number"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="e.g., 1000"
          min="0.01"
          step="any"
          required
        />
        <Input
          label="Token Contract Hash"
          id="depositTokenContract"
          value={tokenContract}
          onChange={(e) => setTokenContract(e.target.value)}
          placeholder="e.g., hash-..."
          required
        />
        <Input
          label="Signature (Placeholder)"
          id="depositSignature"
          value={signature}
          onChange={(e) => setSignature(e.target.value)}
          placeholder="e.g., 0123..."
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
            disabled={depositLoading}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white font-semibold rounded-lg transition-colors flex items-center"
            disabled={depositLoading}
          >
            {depositLoading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
            Deposit Funds
          </button>
        </div>
      </form>
    </Modal>
  );
};

// Claim Insurance Modal Component
interface ClaimInsuranceModalProps {
  isOpen: boolean;
  onClose: () => void;
  onClaim: (data: ClaimInsuranceRequest) => void;
}

const ClaimInsuranceModal: React.FC<ClaimInsuranceModalProps> = ({ isOpen, onClose, onClaim }) => {
  const [claimerPublicKey, setClaimerPublicKey] = useState('');
  const [escrowHash, setEscrowHash] = useState('');
  const [reason, setReason] = useState('');
  const [signature, setSignature] = useState(''); // Placeholder
  const [formError, setFormError] = useState<string | null>(null);
  const [claimLoading, setClaimLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (!claimerPublicKey || !escrowHash || !reason || !signature) {
      setFormError('All fields are required.');
      return;
    }

    setClaimLoading(true);
    try {
      await onClaim({
        claimer_public_key: claimerPublicKey,
        escrow_hash: escrowHash,
        reason,
        signature,
      });
      setClaimerPublicKey('');
      setEscrowHash('');
      setReason('');
      setSignature('');
      setFormError(null);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to submit claim.');
    } finally {
      setClaimLoading(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Submit Insurance Claim">
      <form onSubmit={handleSubmit}>
        <Input
          label="Claimer Public Key"
          id="claimerPublicKey"
          value={claimerPublicKey}
          onChange={(e) => setClaimerPublicKey(e.target.value)}
          placeholder="e.g., 0123..."
          required
        />
        <Input
          label="Escrow Hash"
          id="claimEscrowHash"
          value={escrowHash}
          onChange={(e) => setEscrowHash(e.target.value)}
          placeholder="e.g., hash-..."
          required
        />
        <Textarea
          label="Reason for Claim"
          id="claimReason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Describe why you are filing this claim..."
          required
        />
        <Input
          label="Signature (Placeholder)"
          id="claimSignature"
          value={signature}
          onChange={(e) => setSignature(e.target.value)}
          placeholder="e.g., 0123..."
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
            disabled={claimLoading}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white font-semibold rounded-lg transition-colors flex items-center"
            disabled={claimLoading}
          >
            {claimLoading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
            Submit Claim
          </button>
        </div>
      </form>
    </Modal>
  );
};

export default Insurance;
