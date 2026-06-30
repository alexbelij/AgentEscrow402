const API_BASE = import.meta.env.VITE_API_URL || '/api'

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...opts?.headers },
    ...opts,
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`API ${res.status}: ${body}`)
  }
  return res.json()
}

export interface EscrowRecord {
  sender: string
  receiver: string
  amount: number
  service_hash: string
  status: string
  created_at: number
  ttl: number
}

export interface ReputationRecord {
  agent: string
  completed: number
  disputed: number
  slashed: number
  last_active: number
  score: number
}

export interface HealthResponse {
  status: string
  version: string
  sandbox: boolean
  chain: string
}

export function getHealth(): Promise<HealthResponse> {
  return request('/health')
}

export function createEscrow(data: {
  receiver: string
  amount: number
  service_hash: string
  ttl: number
}, sender?: string): Promise<EscrowRecord> {
  return request('/escrow', {
    method: 'POST',
    headers: sender ? { 'X-402-Sender': sender } : undefined,
    body: JSON.stringify(data),
  })
}

export function releaseEscrow(serviceHash: string): Promise<EscrowRecord> {
  return request('/release', {
    method: 'POST',
    body: JSON.stringify({ service_hash: serviceHash }),
  })
}

export function refundEscrow(serviceHash: string): Promise<EscrowRecord> {
  return request('/refund', {
    method: 'POST',
    body: JSON.stringify({ service_hash: serviceHash }),
  })
}

export function disputeEscrow(serviceHash: string, reasonHash: string): Promise<EscrowRecord> {
  return request('/dispute', {
    method: 'POST',
    body: JSON.stringify({ service_hash: serviceHash, reason_hash: reasonHash }),
  })
}

export function lookupEscrow(serviceHash: string): Promise<EscrowRecord> {
  return request(`/escrow/${serviceHash}`)
}

export function getReputation(agent: string): Promise<ReputationRecord> {
  return request(`/reputation/${agent}`)
}

export function computeHash(data: Record<string, unknown>): Promise<{ hash: string }> {
  return request('/compute-hash', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}
