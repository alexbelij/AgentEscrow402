
// Requests go through the Vercel proxy (/backend/*) to bypass ad-blockers
// that block direct calls to *.onrender.com hostnames containing "api".
// Vercel rewrites /backend/:path* → https://agentescrow402-api.onrender.com/:path*
const BASE_URL = '/backend';

// --- Utility Fetcher ---
export interface ApiResponse<T> {
  data: T | null;
  error: string | null;
  status: number | null;
}

// The demo backend sleeps after ~15 min idle and takes ~50s to cold-start.
// Instead of a hard timeout that crashes the UI, we retry with backoff and let a
// global preloader (see BackendWakeOverlay) inform the user the server is waking.
const PER_ATTEMPT_TIMEOUT_MS = 20000;
const RETRY_DELAYS_MS = [1500, 3000, 5000, 8000, 12000]; // ~30s of retries after 1st try
const RETRYABLE_STATUS = new Set([502, 503, 504]);

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Emit a window event so a global overlay can show/hide a "waking up" preloader. */
function emitBackendState(state: 'waking' | 'ready') {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('backend:state', { detail: state }));
  }
}

/**
 * Normalise API error payloads into a readable string.
 * FastAPI validation errors return `detail` as an ARRAY of objects, which is why
 * the UI previously rendered "[object Object],[object Object]".
 */
function normalizeError(data: any, statusText: string): string {
  if (data == null) return `API Error: ${statusText || 'unknown'}`;
  const detail = data.detail ?? data.message ?? data.error;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (typeof d === 'string') return d;
        const loc = Array.isArray(d?.loc) ? d.loc.filter((x: any) => x !== 'query' && x !== 'body').join('.') : '';
        const msg = d?.msg || d?.message || JSON.stringify(d);
        return loc ? `${loc}: ${msg}` : msg;
      })
      .join('; ');
  }
  if (detail && typeof detail === 'object') return JSON.stringify(detail);
  return `API Error: ${statusText || 'unknown'}`;
}

export const DEMO_AGENT_SENDER = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';
export const DEMO_AGENT_RECEIVER = 'fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210';

const HEX_64 = /^[0-9a-f]{64}$/i;

export function buildDemoXPaymentHeader(escrowHash?: string, amount = 0, sender = DEMO_AGENT_SENDER): string {
  if (!HEX_64.test(sender)) throw new Error('Demo sender must be a 64-char hex public key');
  if (!Number.isSafeInteger(amount) || amount < 0) throw new Error('Demo payment amount must be a non-negative safe integer');
  const hash = (escrowHash && HEX_64.test(escrowHash))
    ? escrowHash.toLowerCase()
    : Array.from(crypto.getRandomValues(new Uint8Array(32))).map((b) => b.toString(16).padStart(2, '0')).join('');
  const nonce = Array.from(crypto.getRandomValues(new Uint8Array(16))).map((b) => b.toString(16).padStart(2, '0')).join('');
  // Hosted-console demo identity only. Production wallets sign the canonical
  // x402 payload with Ed25519 and replay protection; the extra demo header
  // lets the backend distinguish this labelled demo path from production auth.
  const mockSignature = 'a'.repeat(128);
  return `x402-v1;${hash};${amount};${sender.toLowerCase()};${Math.floor(Date.now() / 1000)};${nonce};${mockSignature}`;
}

export function buildDemoPaymentHeaders(escrowHash?: string, amount = 0): HeadersInit {
  return {
    'X-Payment': buildDemoXPaymentHeader(escrowHash, amount),
    'X-AE402-Demo-Identity': 'hosted-console',
  };
}

async function fetcher<T>(
  url: string,
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  body?: object,
  extraHeaders?: HeadersInit
): Promise<ApiResponse<T>> {
  const headers: HeadersInit = { 'Content-Type': 'application/json', ...(extraHeaders || {}) };
  const config: RequestInit = {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  };

  const maxAttempts = RETRY_DELAYS_MS.length + 1;
  let waking = false;
  let lastError = 'An unknown error occurred';
  let lastStatus: number | null = 500;

  try {
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), PER_ATTEMPT_TIMEOUT_MS);
      try {
        const response = await fetch(`${BASE_URL}${url}`, { ...config, signal: controller.signal });
        clearTimeout(timeoutId);

        // Gateway/cold-start responses -> retry (backend still waking).
        if (RETRYABLE_STATUS.has(response.status) && attempt < maxAttempts - 1) {
          if (!waking) { waking = true; emitBackendState('waking'); }
          await sleep(RETRY_DELAYS_MS[attempt]);
          continue;
        }

        const text = await response.text();
        const data = text ? JSON.parse(text) : {};

        if (!response.ok) {
          return { data: null, error: normalizeError(data, response.statusText), status: response.status };
        }
        return { data: data as T, error: null, status: response.status };
      } catch (err) {
        clearTimeout(timeoutId);
        const isTimeout = err instanceof DOMException && err.name === 'AbortError';
        lastError = isTimeout ? 'Server is waking up, please wait…' : (err instanceof Error ? err.message : 'Network error');
        lastStatus = isTimeout ? 504 : 503;
        // A mid-flight abort on a non-GET could double-submit if the server already
        // received it, so only retry non-GET on connection-level failures.
        const safeToRetry = method === 'GET' || !isTimeout;
        if (safeToRetry && attempt < maxAttempts - 1) {
          if (!waking) { waking = true; emitBackendState('waking'); }
          await sleep(RETRY_DELAYS_MS[attempt]);
          continue;
        }
      }
    }
    return { data: null, error: lastError, status: lastStatus };
  } finally {
    if (waking) emitBackendState('ready');
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
  db?: string;
  data_source?: string;
  sandbox?: boolean;
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
  deploy_hash?: string;
  service_hash?: string;
  [key: string]: any;
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
  mlkem_ciphertext?: string;
  mlkem_decap_key?: string;
  mlkem_algorithm?: string;
}

export interface EscrowHistoryEntry {
  timestamp: string;
  event_type: string;
  details: Record<string, any>;
}

export interface CreateEscrowRequest {
  receiver: string;      // Casper account hash of the receiver
  amount: number;        // amount in motes (1 CSPR = 1e9 motes)
  service_hash: string;  // 64-char hex identifier for the service
  ttl?: number;          // time-to-live in seconds (60..86400), default 300
}

export interface EscrowActionRequest {
  service_hash: string;
  reason_hash?: string;  // required only for dispute
  // Set when a connected wallet already built, signed and submitted the
  // on-chain transaction directly (live mode). The backend then only
  // confirms on-chain state instead of signing/submitting itself.
  wallet_tx_hash?: string;
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
  agent_id: string;
  public_key: string;
  did_document_hash: string;
}

export interface Identity {
  agent_id: string;
  public_key: string;
  did_document_hash: string;
  registered_at: string | number;
  deploy_hash?: string;
  mode?: string;
  capabilities?: string[];
}

// Matches server/agent_identity.py's DelegateCapabilityRequest exactly: one
// capability_uri per call (not an array) and an absolute expiry_timestamp
// (not a duration). signature is a 128-char hex Ed25519 signature over
// sha256(f"{delegator_id}:{delegatee_id}:{capability_uri}:{expiry_timestamp}")
// signed by the delegator's registered public key — see lib/demoSigner.ts.
export interface DelegateIdentityRequest {
  delegator_id: string;
  delegatee_id: string;
  capability_uri: string;
  expiry_timestamp: number;
  signature: string;
}

// Actual response shape of GET /identity/capabilities/{agent_id} (server/agent_identity.py).
export interface AgentCapabilities {
  agent_id: string;
  own_capabilities: string[];
  delegated_capabilities: string[];
  total: number;
}

// Actual response shape of POST /identity/delegate (server/agent_identity.py).
export interface DelegationRecord {
  delegator_id: string;
  delegatee_id: string;
  capability_uri: string;
  expiry_timestamp: number;
  delegated_at: number;
  deploy_hash: string;
  mode: string;
}

// Insurance
export interface InsurancePoolStats {
  total_deposited: string;
  total_claims_paid: string;
  available_funds: string;
  active_policies: number;
}

export interface PremiumQuote {
  premium_amount: number; // in motes
  risk_multiplier: number;
  base_rate_bps: number;
}

export interface DepositInsuranceRequest {
  depositor_public_key?: string;
  amount: number;
  token_contract?: string;
  signature?: string;
}

export interface ClaimInsuranceRequest {
  claimer_public_key: string;
  escrow_hash: string;
  reason: string;
  signature: string;
}

// Arbitration
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
    db: raw.db,
    data_source: raw.data_source,
    sandbox: raw.sandbox,
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
    mlkem_ciphertext: raw.mlkem_ciphertext,
    mlkem_decap_key: raw.mlkem_decap_key,
    mlkem_algorithm: raw.mlkem_algorithm,
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
    const mapped = raw.map(normalizeEscrow);
    (mapped as any).total = res.data?.total ?? mapped.length;
    return { ...res, data: mapped };
  },

  createEscrow: (data: CreateEscrowRequest) => fetcher<TransactionHash>('/escrow', 'POST', data, buildDemoPaymentHeaders(data.service_hash, data.amount)),
  releaseEscrow: (data: EscrowActionRequest) => fetcher<TransactionHash>('/release', 'POST', data, buildDemoPaymentHeaders(data.service_hash, 0)),
  refundEscrow: (data: EscrowActionRequest) => fetcher<TransactionHash>('/refund', 'POST', data, buildDemoPaymentHeaders(data.service_hash, 0)),
  disputeEscrow: (data: EscrowActionRequest) => fetcher<TransactionHash>('/dispute', 'POST', data, buildDemoPaymentHeaders(data.service_hash, 0)),

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

  // /events is an SSE stream, not a REST list. Return a marker object so UI can explain this honestly.
  getEvents: async (): Promise<ApiResponse<Event[]>> => {
    return {
      data: [{
        id: 'sse-stream',
        type: 'SSE stream',
        timestamp: new Date().toISOString(),
        details: { endpoint: '/events', note: 'Live Server-Sent Events stream; open connection is used for new escrow_created/released/disputed messages.' },
      }],
      error: null,
      status: 200,
    };
  },

  computeServiceHash: (params: { sender: string; receiver: string; amount: number; nonce: string }) =>
    fetcher<{ service_hash: string }>(`/compute-hash?sender=${encodeURIComponent(params.sender)}&receiver=${encodeURIComponent(params.receiver)}&amount=${params.amount}&nonce=${encodeURIComponent(params.nonce)}`, 'POST'),
  computeHash: (data: { value: string }) => fetcher<{ hash: string }>(`/compute-hash?sender=${encodeURIComponent(data.value)}&receiver=${encodeURIComponent(DEMO_AGENT_RECEIVER)}&amount=1&nonce=console`, 'POST'),

  // Multi-asset Escrow Endpoints
  createMultiAssetEscrow: (data: MultiAssetEscrowRequest) => fetcher<TransactionHash>('/escrow/multi-asset', 'POST', data),
  createStreamEscrow: (data: StreamEscrowRequest) => fetcher<TransactionHash>('/escrow/stream', 'POST', data),
  getStreamStatus: (hash: string) => fetcher<StreamStatus>(`/escrow/${hash}/stream-status`, 'GET'),
  commitAtomicSwap: (data: AtomicSwapCommitRequest) => fetcher<TransactionHash>('/escrow/atomic-swap/commit', 'POST', data),
  revealAtomicSwap: (data: AtomicSwapRevealRequest) => fetcher<TransactionHash>('/escrow/atomic-swap/reveal', 'POST', data),

  // Insurance Endpoints
  depositInsurance: (data: DepositInsuranceRequest) => fetcher<TransactionHash>('/insurance/deposit', 'POST', data, buildDemoPaymentHeaders(undefined, data.amount)),
  claimInsurance: (data: ClaimInsuranceRequest) => fetcher<TransactionHash>('/insurance/claim', 'POST', data, buildDemoPaymentHeaders(data.escrow_hash, 0)),
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
  getPremiumQuote: (escrowAmountMotes: number, agentId: string, serviceType = 'general') =>
    fetcher<PremiumQuote>(
      `/insurance/premium-quote?escrow_amount=${escrowAmountMotes}&agent_id=${encodeURIComponent(agentId)}&service_type=${encodeURIComponent(serviceType)}`,
      'GET'
    ),

  // Risk / VRF Endpoints
  getRiskDashboard: () => fetcher<any>('/risk/dashboard', 'GET'),
  getRiskScore: (agent: string) => fetcher<any>(`/risk/score/${encodeURIComponent(agent)}`, 'GET'),
  electVrfArbiter: (data: { dispute_id: string; sender: string; receiver: string; seed_hash: string }) => fetcher<any>('/vrf/elect', 'POST', data),

  // Arbitration Endpoints
  getArbiters: async (): Promise<ApiResponse<Arbiter[]>> => {
    const res = await fetcher<any>('/arbitration/arbiters', 'GET');
    const raw = res.data?.arbiters || (Array.isArray(res.data) ? res.data : []);
    return { ...res, data: raw.map(normalizeArbiter) };
  },

  // Identity Endpoints
  registerIdentity: (data: RegisterIdentityRequest) => fetcher<TransactionHash>('/identity/register', 'POST', data),
  getIdentity: (id: string) => fetcher<Identity>(`/identity/${id}`, 'GET'),
  delegateIdentity: (data: DelegateIdentityRequest) => fetcher<DelegationRecord>('/identity/delegate', 'POST', data),
  getIdentityCapabilities: (id: string) => fetcher<AgentCapabilities>(`/identity/capabilities/${id}`, 'GET'),
};
