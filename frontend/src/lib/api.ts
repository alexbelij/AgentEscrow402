
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
        error: data.detail || data.message || `API Error: ${response.statusText}`,
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
  chain?: string;
  contract_hash?: string;
  sandbox?: boolean;
}

export interface Stats {
  total_escrows: number;
  total_volume: string;
  pending_escrows: number;
  disputed_escrows: number;
  active_agents: number;
  total_transactions: number;
  released?: number;
  insurance_fee_bps?: number;
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
  net_amount?: number;
  insurance_fee?: number;
}

export interface TransactionHash {
  deploy_hash: string;
}

// Escrow
export type EscrowStatus = 'pending' | 'funded' | 'released' | 'refunded' | 'disputed' | 'cancelled' | 'expired';

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
  deploy_hash?: string;
  ttl?: number;
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
  signature: string;
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
  hash_lock: string;
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
  completed?: number;
  disputed?: number;
  role?: string;
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
  capabilities: string[];
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

// =========================================================
// RESPONSE NORMALIZERS — map backend fields to frontend types
// =========================================================

function normalizeHealth(raw: any): HealthStatus {
  return {
    status: raw.status || 'unknown',
    version: raw.version || '0.0.0',
    uptime: raw.uptime ?? 0,
    database: raw.db || raw.database || 'unknown',
    chain: raw.chain,
    contract_hash: raw.contract_hash,
    sandbox: raw.sandbox,
  };
}

function normalizeStats(raw: any): Stats {
  return {
    total_escrows: raw.total_escrows ?? raw.total ?? 0,
    total_volume: String(raw.total_volume ?? raw.volume ?? 0),
    pending_escrows: raw.pending_escrows ?? raw.pending ?? 0,
    disputed_escrows: raw.disputed_escrows ?? raw.disputed ?? 0,
    active_agents: raw.active_agents ?? 0,
    total_transactions: raw.total_transactions ?? (raw.total ?? 0),
    released: raw.released,
    insurance_fee_bps: raw.insurance_fee_bps,
  };
}

function normalizeAgent(raw: any): Agent {
  return {
    public_key: raw.public_key || raw.agent || raw.agent_id || 'unknown',
    name: raw.name || raw.agent || undefined,
    reputation_score: raw.reputation_score ?? raw.score ?? 0,
    registered_at: raw.registered_at || new Date().toISOString(),
    status: raw.status || (raw.availability !== false ? 'active' : 'inactive'),
    completed: raw.completed,
    disputed: raw.disputed,
    role: raw.role,
  };
}

function normalizeEscrow(raw: any): Escrow {
  const createdAt = raw.created_at
    ? typeof raw.created_at === 'number'
      ? new Date(raw.created_at * 1000).toISOString()
      : raw.created_at
    : new Date().toISOString();

  return {
    hash: raw.hash || raw.service_hash || 'unknown',
    payer: raw.payer || raw.sender || 'unknown',
    payee: raw.payee || raw.receiver || 'unknown',
    amount: String(raw.amount ?? 0),
    token_contract: raw.token_contract || 'CSPR',
    status: raw.status || 'pending',
    arbiter: raw.arbiter,
    created_at: createdAt,
    updated_at: raw.updated_at || createdAt,
    metadata: raw.metadata,
    deploy_hash: raw.deploy_hash,
    ttl: raw.ttl,
  };
}

function normalizeEscrowHistory(raw: any): EscrowHistoryEntry {
  const ts = raw.ts
    ? typeof raw.ts === 'number'
      ? new Date(raw.ts * 1000).toISOString()
      : raw.ts
    : raw.timestamp || new Date().toISOString();

  return {
    timestamp: ts,
    event_type: raw.event_type || raw.action || 'unknown',
    details: raw.details || { by: raw.by, amount: raw.amount },
  };
}

function normalizeReputation(agentKey: string, raw: any): Reputation {
  return {
    agent_public_key: raw.agent_public_key || agentKey,
    score: raw.score ?? raw.reputation_score ?? 0,
    total_escrows_completed: raw.total_escrows_completed ?? raw.completed ?? 0,
    successful_releases: raw.successful_releases ?? raw.completed ?? 0,
    disputes_won: raw.disputes_won ?? 0,
    disputes_lost: raw.disputes_lost ?? raw.disputed ?? 0,
    last_updated: raw.last_updated || new Date().toISOString(),
  };
}

function normalizeArbiter(raw: any): Arbiter {
  return {
    public_key: raw.public_key || raw.arbiter_id || 'unknown',
    name: raw.name || raw.arbiter_id || 'Unknown',
    reputation_score: raw.reputation_score ?? 0,
    active_elections: raw.active_elections ?? raw.completed_arbitrations ?? 0,
  };
}

function normalizeInsurancePoolStats(raw: any): InsurancePoolStats {
  return {
    total_deposited: String(raw.total_deposited ?? raw.total_assets ?? 0),
    total_claims_paid: String(raw.total_claims_paid ?? 0),
    available_funds: String(raw.available_funds ?? raw.total_assets ?? 0),
    active_policies: raw.active_policies ?? raw.total_claims_filed ?? 0,
  };
}

// --- API Client Functions ---

export const api = {
  // Main Endpoints
  getHealth: async (): Promise<ApiResponse<HealthStatus>> => {
    const res = await fetcher<any>('/health', 'GET');
    if (res.data) return { ...res, data: normalizeHealth(res.data) };
    return res as ApiResponse<HealthStatus>;
  },

  getStats: async (): Promise<ApiResponse<Stats>> => {
    const res = await fetcher<any>('/stats', 'GET');
    if (res.data) return { ...res, data: normalizeStats(res.data) };
    return res as ApiResponse<Stats>;
  },

  getEscrows: async (params?: { limit?: number; offset?: number; status?: EscrowStatus }): Promise<ApiResponse<Escrow[]>> => {
    const query = new URLSearchParams();
    if (params?.limit) query.append('limit', params.limit.toString());
    if (params?.offset) query.append('offset', params.offset.toString());
    if (params?.status) query.append('status', params.status);
    const res = await fetcher<any>(`/escrows?${query.toString()}`, 'GET');
    const raw = res.data?.escrows || (Array.isArray(res.data) ? res.data : []);
    return { ...res, data: raw.map(normalizeEscrow) };
  },

  createEscrow: (data: CreateEscrowRequest) => fetcher<TransactionHash>('/escrow', 'POST', data),
  releaseEscrow: (data: EscrowActionRequest) => fetcher<TransactionHash>('/release', 'POST', data),
  refundEscrow: (data: EscrowActionRequest) => fetcher<TransactionHash>('/refund', 'POST', data),
  disputeEscrow: (data: EscrowActionRequest) => fetcher<TransactionHash>('/dispute', 'POST', data),

  getEscrowByHash: async (hash: string): Promise<ApiResponse<Escrow>> => {
    const res = await fetcher<any>(`/escrow/${hash}`, 'GET');
    if (res.data) return { ...res, data: normalizeEscrow(res.data) };
    return res as ApiResponse<Escrow>;
  },

  getReputation: async (agent: string): Promise<ApiResponse<Reputation>> => {
    const res = await fetcher<any>(`/reputation/${agent}`, 'GET');
    if (res.data) return { ...res, data: normalizeReputation(agent, res.data) };
    return res as ApiResponse<Reputation>;
  },

  getAgents: async (): Promise<ApiResponse<Agent[]>> => {
    const res = await fetcher<any>('/agents', 'GET');
    const raw = res.data?.agents || (Array.isArray(res.data) ? res.data : []);
    return { ...res, data: raw.map(normalizeAgent) };
  },

  getEscrowHistory: async (hash: string): Promise<ApiResponse<EscrowHistoryEntry[]>> => {
    const res = await fetcher<any>(`/escrow/${hash}/history`, 'GET');
    const raw = res.data?.events || (Array.isArray(res.data) ? res.data : []);
    return { ...res, data: raw.map(normalizeEscrowHistory) };
  },

  getEstimate: async (amount: number): Promise<ApiResponse<Estimate>> => {
    const res = await fetcher<any>(`/estimate?amount=${amount}`, 'GET');
    if (res.data) {
      return {
        ...res,
        data: {
          amount: String(res.data.amount ?? amount),
          fee: String(res.data.insurance_fee ?? res.data.fee ?? 0),
          total_with_fee: String(res.data.total_with_fee ?? amount),
          net_amount: res.data.net_amount,
          insurance_fee: res.data.insurance_fee,
        },
      };
    }
    return res as ApiResponse<Estimate>;
  },

  // /events is an SSE stream — return empty array for REST callers
  getEvents: async (): Promise<ApiResponse<Event[]>> => {
    return { data: [], error: null, status: 200 };
  },

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
  getInsurancePoolStats: async (): Promise<ApiResponse<InsurancePoolStats>> => {
    const res = await fetcher<any>('/insurance/pool-stats', 'GET');
    if (res.data) return { ...res, data: normalizeInsurancePoolStats(res.data) };
    // If endpoint fails, return safe defaults
    if (res.error) {
      return {
        data: { total_deposited: '0', total_claims_paid: '0', available_funds: '0', active_policies: 0 },
        error: null,
        status: 200,
      };
    }
    return res as ApiResponse<InsurancePoolStats>;
  },
  getPremiumQuote: (amount: number, duration: number) => fetcher<PremiumQuote>(`/insurance/premium-quote?amount=${amount}&duration=${duration}`, 'GET'),

  // Arbitration Endpoints
  electArbiter: (data: ElectArbiterRequest) => fetcher<TransactionHash>('/arbitration/elect', 'POST', data),
  getElectionStatus: (id: string) => fetcher<ElectionStatus>(`/arbitration/election/${id}`, 'GET'),
  getArbiters: async (): Promise<ApiResponse<Arbiter[]>> => {
    const res = await fetcher<any>('/arbitration/arbiters', 'GET');
    const raw = res.data?.arbiters || (Array.isArray(res.data) ? res.data : []);
    return { ...res, data: raw.map(normalizeArbiter) };
  },

  // Identity Endpoints
  registerIdentity: (data: RegisterIdentityRequest) => fetcher<TransactionHash>('/identity/register', 'POST', data),
  getIdentity: (id: string) => fetcher<Identity>(`/identity/${id}`, 'GET'),
  delegateIdentity: (data: DelegateIdentityRequest) => fetcher<TransactionHash>('/identity/delegate', 'POST', data),
  getIdentityCapabilities: (id: string) => fetcher<Capability[]>(`/identity/capabilities/${id}`, 'GET'),
};
