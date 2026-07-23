/**
 * Read-only TypeScript client for the AgentEscrow402 API.
 *
 * Ports only the unauthenticated GET endpoints from `sdk/client.py`
 * (`EscrowClient.get_escrow` / `.get_reputation` / `.health`) — no
 * x402 signing, no write path. See `sdk-ts/README.md` for rationale.
 */

import { errorForStatus } from "./errors.ts";
import type { EscrowResponse, HealthResponse, ReputationResponse } from "./types.ts";

export class AgentEscrow402ReadClient {
  private readonly baseUrl: string;
  private readonly timeoutMs: number;

  constructor(baseUrl: string = "http://localhost:8000", timeoutMs: number = 30_000) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.timeoutMs = timeoutMs;
  }

  private async getJson<T>(path: string): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const resp = await fetch(`${this.baseUrl}${path}`, { signal: controller.signal });
      const text = await resp.text();
      let data: unknown = undefined;
      if (text.length > 0) {
        try {
          data = JSON.parse(text);
        } catch {
          data = text;
        }
      }
      if (!resp.ok) {
        const message =
          data && typeof data === "object" && "detail" in (data as Record<string, unknown>)
            ? String((data as Record<string, unknown>).detail)
            : `HTTP ${resp.status}`;
        throw errorForStatus(resp.status, message, data);
      }
      return data as T;
    } finally {
      clearTimeout(timer);
    }
  }

  /** Fetch escrow status by service hash. GET /escrow/{service_hash}. */
  async getEscrow(serviceHash: string): Promise<EscrowResponse> {
    return this.getJson<EscrowResponse>(`/escrow/${serviceHash}`);
  }

  /** Get reputation score for an agent. GET /reputation/{agent}. */
  async getReputation(agent: string): Promise<ReputationResponse> {
    return this.getJson<ReputationResponse>(`/reputation/${agent}`);
  }

  /** Get IsolationForest anomaly-detection risk score. GET /risk/score/{agent}. */
  async riskScore(agent: string): Promise<Record<string, unknown>> {
    return this.getJson<Record<string, unknown>>(`/risk/score/${agent}`);
  }

  /** Health check. GET /health. */
  async health(): Promise<HealthResponse> {
    return this.getJson<HealthResponse>("/health");
  }
}
