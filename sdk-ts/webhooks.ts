/**
 * Webhook signature verification for AgentEscrow402.
 *
 * Verifies HMAC-SHA256 signatures on webhook payloads delivered to a
 * customer's endpoint. Follows the Stripe/GitHub-style convention:
 *
 *   X-AE402-Signature: t=<unix-seconds>,v1=<hex-sha256-hmac>
 *
 * where the signed payload is `<t>.<raw-body>` and the HMAC key is a
 * per-endpoint secret shared out of band. Timestamp is compared against
 * the current wall clock with a configurable tolerance to reject
 * replayed webhook deliveries. Constant-time signature comparison
 * prevents timing side channels.
 *
 * Zero third-party dependencies — uses Node's built-in
 * `crypto.webcrypto.subtle.sign` (HMAC support is stable since Node 15,
 * verified on Node 24 in this repo's environment).
 */

import { webcrypto } from "node:crypto";

export type WebhookEventType =
  | "escrow.created"
  | "escrow.released"
  | "escrow.refunded"
  | "escrow.disputed"
  | "escrow.resolved"
  | "reputation.updated";

export interface WebhookEvent {
  /** Server-side event id (idempotency key). */
  id: string;
  /** Discriminator; new event types may be added in a minor release. */
  type: WebhookEventType | (string & {});
  /** Unix seconds when the server emitted the event. */
  created: number;
  /** Event payload — shape depends on `type`. See docs. */
  data: unknown;
  /** SDK/webhook envelope version (major bumps here are breaking). */
  api_version?: string;
}

export type WebhookSignatureErrorReason =
  | "missing_header"
  | "malformed_header"
  | "no_matching_signature"
  | "timestamp_out_of_tolerance"
  | "invalid_secret";

export class WebhookSignatureError extends Error {
  readonly reason: WebhookSignatureErrorReason;
  constructor(message: string, reason: WebhookSignatureErrorReason) {
    super(message);
    this.name = "WebhookSignatureError";
    this.reason = reason;
  }
}

const SIG_HEADER = "x-ae402-signature";
const DEFAULT_TOLERANCE_SECONDS = 5 * 60;
const SCHEME = "v1";

interface ParsedHeader {
  timestamp: number;
  signatures: string[];
}

function parseSignatureHeader(header: string): ParsedHeader {
  let timestamp = -1;
  const signatures: string[] = [];
  for (const raw of header.split(",")) {
    const eq = raw.indexOf("=");
    if (eq === -1) {
      throw new WebhookSignatureError(
        `Malformed signature header segment: ${raw}`,
        "malformed_header",
      );
    }
    const key = raw.slice(0, eq).trim();
    const value = raw.slice(eq + 1).trim();
    if (key === "t") {
      const n = Number.parseInt(value, 10);
      if (!Number.isFinite(n) || n <= 0) {
        throw new WebhookSignatureError(
          `Invalid t= value: ${value}`,
          "malformed_header",
        );
      }
      timestamp = n;
    } else if (key === SCHEME) {
      signatures.push(value);
    }
    // Unknown scheme keys are ignored to leave room for future v2/v3.
  }
  if (timestamp === -1) {
    throw new WebhookSignatureError(
      "Signature header missing t=",
      "malformed_header",
    );
  }
  if (signatures.length === 0) {
    throw new WebhookSignatureError(
      `Signature header missing ${SCHEME}= entries`,
      "malformed_header",
    );
  }
  return { timestamp, signatures };
}

function hexToBytes(hex: string): Uint8Array | null {
  if (hex.length === 0 || hex.length % 2 !== 0) return null;
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) {
    const b = Number.parseInt(hex.substr(i * 2, 2), 16);
    if (!Number.isFinite(b)) return null;
    out[i] = b;
  }
  return out;
}

function bytesToHex(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += b.toString(16).padStart(2, "0");
  return s;
}

/** Timing-safe compare of two byte arrays of equal length. */
function timingSafeEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i]! ^ b[i]!;
  return diff === 0;
}

async function importKey(secret: string): Promise<CryptoKey> {
  if (!secret || secret.length === 0) {
    throw new WebhookSignatureError(
      "Webhook secret is empty",
      "invalid_secret",
    );
  }
  const keyBytes = new TextEncoder().encode(secret);
  return await webcrypto.subtle.importKey(
    "raw",
    keyBytes,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
}

async function hmacSha256Hex(secret: string, payload: string): Promise<string> {
  const key = await importKey(secret);
  const sig = await webcrypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(payload),
  );
  return bytesToHex(new Uint8Array(sig));
}

export interface VerifyOptions {
  /**
   * Max seconds between `X-AE402-Signature`'s `t=` and current wall
   * clock. Defaults to 300s (5 min) to reject replayed deliveries.
   */
  toleranceSeconds?: number;
  /**
   * Override "now" (unix seconds) — for tests. Defaults to
   * `Date.now() / 1000`.
   */
  nowSeconds?: number;
}

/**
 * Verify a webhook payload against the `X-AE402-Signature` header.
 *
 * @param payload  The raw request body as received (do not JSON.parse
 *                 and re-stringify — signature is over exact bytes).
 * @param header   The `X-AE402-Signature` header value.
 * @param secret   The endpoint's shared HMAC secret.
 * @param options  Optional tolerance + injectable clock.
 * @throws `WebhookSignatureError` on any mismatch.
 * @returns The parsed `WebhookEvent` from `JSON.parse(payload)`.
 */
export async function verifyWebhookSignature(
  payload: string,
  header: string | null | undefined,
  secret: string,
  options: VerifyOptions = {},
): Promise<WebhookEvent> {
  if (!header) {
    throw new WebhookSignatureError(
      `Missing ${SIG_HEADER} header`,
      "missing_header",
    );
  }
  const { timestamp, signatures } = parseSignatureHeader(header);
  const tolerance = options.toleranceSeconds ?? DEFAULT_TOLERANCE_SECONDS;
  const now = options.nowSeconds ?? Math.floor(Date.now() / 1000);
  if (Math.abs(now - timestamp) > tolerance) {
    throw new WebhookSignatureError(
      `Webhook timestamp ${timestamp} outside ±${tolerance}s of now (${now})`,
      "timestamp_out_of_tolerance",
    );
  }
  const signed = `${timestamp}.${payload}`;
  const expectedHex = await hmacSha256Hex(secret, signed);
  const expectedBytes = hexToBytes(expectedHex)!;
  let matched = false;
  for (const providedHex of signatures) {
    const providedBytes = hexToBytes(providedHex);
    if (!providedBytes) continue;
    if (timingSafeEqual(providedBytes, expectedBytes)) {
      matched = true;
      break;
    }
  }
  if (!matched) {
    throw new WebhookSignatureError(
      `No v1= signature in header matched HMAC-SHA256(secret, "${timestamp}.<body>")`,
      "no_matching_signature",
    );
  }
  return JSON.parse(payload) as WebhookEvent;
}

/**
 * Build the value a webhook sender should place in `X-AE402-Signature`.
 * Intended for tests, mocks, and server-side implementations — an SDK
 * user receiving webhooks should call `verifyWebhookSignature` instead.
 */
export async function signWebhookPayload(
  payload: string,
  secret: string,
  timestampSeconds: number = Math.floor(Date.now() / 1000),
): Promise<string> {
  if (!Number.isFinite(timestampSeconds) || timestampSeconds <= 0) {
    throw new WebhookSignatureError(
      `Invalid timestamp: ${timestampSeconds}`,
      "malformed_header",
    );
  }
  const signed = `${timestampSeconds}.${payload}`;
  const hex = await hmacSha256Hex(secret, signed);
  return `t=${timestampSeconds},${SCHEME}=${hex}`;
}
