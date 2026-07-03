
const BASE_URL = 'https://agentescrow402-api.onrender.com';

// --- Utility Fetcher ---
interface ApiResponse<T> {
  data: T | null;
  error: string | null;
  status: number | null;
}

async function fetcher<T>(
  url: string,
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  body?: object
): Promise<ApiResponse<T>> {
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };

  const config: RequestInit = {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  };

  try {
    const response = await fetch(`${BASE_URL}${url}`, config);
    const data = await response.json();

    if (!response.ok) {
      return {
        data: null,
        error: data.message || `API Error: ${response.statusText}`,
        status: response.status,
      };
    }

    return {
      data: data as T,
      error: null,
      status: response.status,
    };
  } catch (err) {
    console.error(`Fetch error for ${url}:`, err);
    return {
      data: null,
      error: err instanceof Error ? err.message : 'An unknown error occurred',
      status: 500,
    };
  }
}

// --- Type Definitions ---

// General
export interface HealthStatus {
  status: string;
  version: string;
  uptime: number;
  database: string;
}

export interface Stats {
  total_escrows: number;
  total_volume: string; // Assuming U512 as string
  pending_escrows: number;
  disputed_escrows: number;
  active_agents: number;
  total_transactions: number;
}

export interface Event {
  id: string;
  type: string;
  timestamp: string;
  details: Record<string, any>;
}

export interface Estimate {
  amount: string;
  fee: string;
  total_with_fee: string;
}

export interface TransactionHash {
  deploy_hash: string;
}

// Escrow
export type EscrowStatus = 'pending' | 'funded' | 'released' | 'refunded' | 'disputed' | 'cancelled';

export interface Escrow {
  hash: string;
  payer: string;
  payee: string;
  amount: string;
  token_contract: string;
  status: EscrowStatus;
  arbiter?: string;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, any>;
}

export interface EscrowHistoryEntry {
  timestamp: string;
  event_type: string;
  details: Record<string, any>;
}

export interface CreateEscrowRequest {
  payer: string;
  payee: string;
  amount: string;
  token_contract: string;
  arbiter?: string;
  metadata?: Record<string, any>;
}

export interface EscrowActionRequest {
  escrow_hash: string;
  initiator_account: string;
  signature: string; // Placeholder for actual signature
}

// Multi-asset Escrow
export interface MultiAssetEscrowRequest {
  payer: string;
  payee: string;
  assets: Array<{
    amount: string;
    token_contract: string;
  }>;
  arbiter?: string;
  metadata?: Record<string, any>;
}

export interface StreamEscrowRequest {
  payer: string;
  payee: string;
  total_amount: string;
  token_contract: string;
  duration_seconds: number;
  interval_seconds: number;
  arbiter?: string;
  metadata?: Record<string, any>;
}

export interface StreamStatus {
  escrow_hash: string;
  total_amount: string;
  streamed_amount: string;
  remaining_amount: string;
  start_time: string;
  end_time: string;
  last_stream_time: string;
  status: EscrowStatus;
}

export interface AtomicSwapCommitRequest {
  initiator: string;
  target: string;
  initiator_asset: {
    amount: string;
    token_contract: string;
  };
  target_asset: {
    amount: string;
    token_contract: string;
  };
  hash_lock: string; // Hashed secret
  timelock_seconds: number;
}

export interface AtomicSwapRevealRequest {
  swap_hash: string;
  secret: string;
}

// Agent & Identity
export interface Agent {
  public_key: string;
  name?: string;
  reputation_score: number;
  registered_at: string;
  status: 'active' | 'inactive' | 'suspended';
}

export interface Reputation {
  agent_public_key: string;
  score: number;
  total_escrows_completed: number;
  successful_releases: number;
  disputes_won: number;
  disputes_lost: number;
  last_updated: string;
}

export interface RegisterIdentityRequest {
  public_key: string;
  name: string;
  metadata?: Record<string, any>;
}

export interface Identity {
  public_key: string;
  name: string;
  registered_at: string;
  metadata?: Record<string, any>;
}

export interface DelegateIdentityRequest {
  delegator_public_key: string;
  delegatee_public_key: string;
  capabilities: string[]; // e.g., ['create_escrow', 'release_escrow']
  duration_seconds: number;
  signature: string;
}

export interface Capability {
  capability: string;
  delegated_by: string;
  expires_at: string;
}

// Insurance
export interface InsurancePoolStats {
  total_deposited: string;
  total_claims_paid: string;
  available_funds: string;
  active_policies: number;
}

export interface PremiumQuote {
  amount: string;
  duration_seconds: number;
  premium_amount: string;
  fee_rate: number;
}

export interface DepositInsuranceRequest {
  depositor_public_key: string;
  amount: string;
  token_contract: string;
  signature: string;
}

export interface ClaimInsuranceRequest {
  claimer_public_key: string;
  escrow_hash: string;
  reason: string;
  signature: string;
}

// Arbitration
export interface ElectArbiterRequest {
  initiator_public_key: string;
  escrow_hash: string;
  candidate_arbiter: string;
  reason: string;
  signature: string;
}

export interface ElectionStatus {
  election_id: string;
  escrow_hash: string;
  candidate_arbiter: string;
  status: 'pending' | 'approved' | 'rejected';
  votes_for: number;
  votes_against: number;
  created_at: string;
  expires_at: string;
}

export interface Arbiter {
  public_key: string;
  name: string;
  reputation_score: number;
  active_elections: number;
}

// --- API Client Functions ---

export const api = {
  // Main Endpoints
  getHealth: () => fetcher<HealthStatus>('/health', 'GET'),
  getStats: () => fetcher<Stats>('/stats', 'GET'),
  getEscrows: async (params?: { limit?: number; offset?: number; status?: EscrowStatus }): Promise<ApiResponse<Escrow[]>> => {
    const query = new URLSearchParams();
    if (params?.limit) query.append('limit', params.limit.toString());
    if (params?.offset) query.append('offset', params.offset.toString());
    if (params?.status) query.append('status', params.status);
    const res = await fetcher<any>(`/escrows?${query.toString()}`, 'GET');
    if (res.data?.escrows) return { ...res, data: res.data.escrows };
    if (Array.isArray(res.data)) return res as ApiResponse<Escrow[]>;
    return { ...res, data: [] };
  },
  createEscrow: (data: CreateEscrowRequest) => fetcher<TransactionHash>('/escrow', 'POST', data),
  releaseEscrow: (data: EscrowActionRequest) => fetcher<TransactionHash>('/release', 'POST', data),
  refundEscrow: (data: EscrowActionRequest) => fetcher<TransactionHash>('/refund', 'POST', data),
  disputeEscrow: (data: EscrowActionRequest) => fetcher<TransactionHash>('/dispute', 'POST', data),
  getEscrowByHash: (hash: string) => fetcher<Escrow>(`/escrow/${hash}`, 'GET'),
  getReputation: (agent: string) => fetcher<Reputation>(`/reputation/${agent}`, 'GET'),
  getAgents: async (): Promise<ApiResponse<Agent[]>> => {
    const res = await fetcher<any>('/agents', 'GET');
    if (res.data?.agents) return { ...res, data: res.data.agents };
    if (Array.isArray(res.data)) return res as ApiResponse<Agent[]>;
    return { ...res, data: [] };
  },
  getEscrowHistory: (hash: string) => fetcher<EscrowHistoryEntry[]>(`/escrow/${hash}/history`, 'GET'),
  getEstimate: (amount: number) => fetcher<Estimate>(`/estimate?amount=${amount}`, 'GET'),
  getEvents: () => fetcher<Event[]>('/events', 'GET'),
  computeHash: (data: { value: string }) => fetcher<{ hash: string }>('/compute-hash', 'POST', data),

  // Multi-asset Escrow Endpoints
  createMultiAssetEscrow: (data: MultiAssetEscrowRequest) => fetcher<TransactionHash>('/escrow/multi-asset', 'POST', data),
  createStreamEscrow: (data: StreamEscrowRequest) => fetcher<TransactionHash>('/escrow/stream', 'POST', data),
  getStreamStatus: (hash: string) => fetcher<StreamStatus>(`/escrow/${hash}/stream-status`, 'GET'),
  commitAtomicSwap: (data: AtomicSwapCommitRequest) => fetcher<TransactionHash>('/escrow/atomic-swap/commit', 'POST', data),
  revealAtomicSwap: (data: AtomicSwapRevealRequest) => fetcher<TransactionHash>('/escrow/atomic-swap/reveal', 'POST', data),

  // Insurance Endpoints
  depositInsurance: (data: DepositInsuranceRequest) => fetcher<TransactionHash>('/insurance/deposit', 'POST', data),
  claimInsurance: (data: ClaimInsuranceRequest) => fetcher<TransactionHash>('/insurance/claim', 'POST', data),
  getInsurancePoolStats: () => fetcher<InsurancePoolStats>('/insurance/pool-stats', 'GET'),
  getPremiumQuote: (amount: number, duration: number) => fetcher<PremiumQuote>(`/insurance/premium-quote?amount=${amount}&duration=${duration}`, 'GET'),

  // Arbitration Endpoints
  electArbiter: (data: ElectArbiterRequest) => fetcher<TransactionHash>('/arbitration/elect', 'POST', data),
  getElectionStatus: (id: string) => fetcher<ElectionStatus>(`/arbitration/election/${id}`, 'GET'),
  getArbiters: () => fetcher<Arbiter[]>('/arbitration/arbiters', 'GET'),

  // Identity Endpoints
  registerIdentity: (data: RegisterIdentityRequest) => fetcher<TransactionHash>('/identity/register', 'POST', data),
  getIdentity: (id: string) => fetcher<Identity>(`/identity/${id}`, 'GET'),
  delegateIdentity: (data: DelegateIdentityRequest) => fetcher<TransactionHash>('/identity/delegate', 'POST', data),
  getIdentityCapabilities: (id: string) => fetcher<Capability[]>(`/identity/capabilities/${id}`, 'GET'),
};
