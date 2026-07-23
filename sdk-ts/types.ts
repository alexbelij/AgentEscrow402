/**
 * Type mirrors of `sdk/agentescrow402/models.py`, trimmed to the fields
 * the read + verify subset actually touches. Keep in sync with the
 * Python models when the API response shape changes.
 */

export const TokenType = {
  CSPR: "CSPR",
  USDC: "USDC",
} as const;
export type TokenType = (typeof TokenType)[keyof typeof TokenType];

export const EscrowStatus = {
  CREATED: "CREATED",
  FUNDED: "FUNDED",
  IN_PROGRESS: "IN_PROGRESS",
  COMPLETED: "COMPLETED",
  DISPUTED: "DISPUTED",
  REFUNDED: "REFUNDED",
  CANCELLED: "CANCELLED",
} as const;
export type EscrowStatus = (typeof EscrowStatus)[keyof typeof EscrowStatus];

export interface StreamConfig {
  interval_seconds: number;
  total_periods: number;
  start_time?: string | null;
}

export interface EscrowResponse {
  id: string;
  agent_id: string;
  client_id: string;
  amount: number;
  current_balance: number;
  token_type: TokenType;
  status: EscrowStatus;
  description: string;
  created_at: string;
  updated_at: string;
  deadline?: string | null;
  streaming_config?: StreamConfig | null;
  dispute_details?: Record<string, unknown> | null;
  insurance_policy_id?: string | null;
}

export interface ReputationResponse {
  agent_id?: string;
  score?: number;
  [key: string]: unknown;
}

export interface HealthResponse {
  status: string;
  [key: string]: unknown;
}
