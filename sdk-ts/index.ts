/**
 * `@ae402/sdk` — AgentEscrow402 TypeScript SDK.
 *
 * Bundles the read-only HTTP client, Ed25519 signature verification,
 * and HMAC-SHA256 webhook signature verification into a single
 * publishable npm package. Zero third-party runtime dependencies —
 * uses Node's built-in `crypto.webcrypto.subtle` and global `fetch`
 * (Node >=19).
 *
 * See individual sub-path exports for tree-shaken imports:
 *   - `@ae402/sdk/client`
 *   - `@ae402/sdk/verify`
 *   - `@ae402/sdk/webhooks`
 *   - `@ae402/sdk/types`
 *   - `@ae402/sdk/errors`
 */

export { AgentEscrow402ReadClient } from "./client.ts";
export {
  buildResolveMessage,
  buildCapApprovalMessage,
  buildInsuranceClaimMessage,
  verifyEd25519Vote,
  countValidVotes,
  countValidCapApprovalVotes,
  countValidInsuranceClaimVotes,
} from "./verify.ts";
export {
  verifyWebhookSignature,
  signWebhookPayload,
  WebhookSignatureError,
} from "./webhooks.ts";
export type {
  WebhookEvent,
  WebhookEventType,
  VerifyOptions,
} from "./webhooks.ts";
export type {
  TokenType,
  EscrowStatus,
  EscrowResponse,
  ReputationResponse,
  HealthResponse,
} from "./types.ts";
export {
  AgentEscrowError,
  APIError,
  BadRequestError,
  UnauthorizedError,
  ForbiddenError,
  NotFoundError,
  ConflictError,
  errorForStatus,
} from "./errors.ts";

/** SDK package version — kept in sync with package.json `version`. */
export const SDK_VERSION = "0.1.0" as const;
