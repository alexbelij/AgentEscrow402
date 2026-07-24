/**
 * TypeScript mirror of `server/arbiter_crypto.py`'s off-chain Ed25519
 * verification of arbiter multisig vote signatures (canonical messages
 * must byte-for-byte match the Rust contract's `build_resolve_message` /
 * `build_cap_approval_message` / `build_claim_message`).
 *
 * Uses Node's built-in WebCrypto Ed25519 support (`crypto.webcrypto`,
 * available since Node 19+) — no external crypto dependency.
 */

const ED25519_TAG_HEX = "01";

function hexToBytes(hex: string): Uint8Array {
  if (hex.length % 2 !== 0) {
    throw new Error("odd-length hex string");
  }
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) {
    const byte = Number.parseInt(hex.slice(i * 2, i * 2 + 2), 16);
    if (Number.isNaN(byte)) {
      throw new Error("invalid hex string");
    }
    out[i] = byte;
  }
  return out;
}

/** Canonical message for a resolve() verdict vote. Must match `build_resolve_message` in Python/Rust. */
export function buildResolveMessage(serviceHash: string, inFavorOf: string): Uint8Array {
  return new TextEncoder().encode(`resolve:${serviceHash}:${inFavorOf}`);
}

/** Canonical message for an above-cap release()/reveal_swap() approval. Must match `build_cap_approval_message`. */
export function buildCapApprovalMessage(action: "release" | "reveal_swap", serviceHash: string): Uint8Array {
  return new TextEncoder().encode(`${action}:${serviceHash}:cap_approval`);
}

/** Canonical message for an insurance-pool claim() payout approval. Must match `build_insurance_claim_message`. */
export function buildInsuranceClaimMessage(
  escrowId: string,
  claimantAccountHash: string,
  amount: number,
): Uint8Array {
  return new TextEncoder().encode(`claim:${escrowId}:${claimantAccountHash}:${amount}`);
}

/**
 * Import a tag-prefixed-hex ("01" + 64 hex chars) Ed25519 public key for
 * WebCrypto verification. Returns null (never throws) on any malformed
 * input, matching `_pubkey_from_hex`'s "reject, don't raise" contract.
 */
async function importPubkeyFromHex(pubkeyHex: string): Promise<CryptoKey | null> {
  if (!pubkeyHex.toLowerCase().startsWith(ED25519_TAG_HEX)) {
    return null; // only ed25519 arbiter keys are supported
  }
  let raw: Uint8Array;
  try {
    raw = hexToBytes(pubkeyHex.slice(2));
  } catch {
    return null;
  }
  if (raw.length !== 32) {
    return null;
  }
  try {
    return await crypto.subtle.importKey("raw", raw as BufferSource, { name: "Ed25519" }, true, ["verify"]);
  } catch {
    return null;
  }
}

/** Decode a tag-prefixed-hex ("01" + 128 hex chars) Ed25519 signature. Returns null on malformed input. */
function signatureBytesFromHex(sigHex: string): Uint8Array | null {
  if (!sigHex.toLowerCase().startsWith(ED25519_TAG_HEX)) {
    return null;
  }
  let raw: Uint8Array;
  try {
    raw = hexToBytes(sigHex.slice(2));
  } catch {
    return null;
  }
  if (raw.length !== 64) {
    return null;
  }
  return raw;
}

/**
 * Verify a single arbiter vote: tag-prefixed-hex pubkey + signature
 * against an arbitrary message. Never throws — returns false for any
 * malformed input or a failed signature check, same as the Python
 * `_pubkey_from_hex`/`_signature_bytes_from_hex`/`InvalidSignature` path.
 */
export async function verifyEd25519Vote(
  pubkeyHex: string,
  sigHex: string,
  message: Uint8Array,
): Promise<boolean> {
  const pubkey = await importPubkeyFromHex(pubkeyHex);
  const sig = signatureBytesFromHex(sigHex);
  if (pubkey === null || sig === null) {
    return false;
  }
  try {
    return await crypto.subtle.verify({ name: "Ed25519" }, pubkey, sig as BufferSource, message as BufferSource);
  } catch {
    return false;
  }
}

/**
 * Count how many submitted (pubkey, signature) votes are valid against
 * `message`, deduplicated by pubkey and restricted to `registered` —
 * a byte-for-byte mirror of `count_valid_votes_for_message`.
 */
export async function countValidVotesForMessage(
  pubkeys: string[],
  signatures: string[],
  registered: readonly string[],
  message: Uint8Array,
): Promise<number> {
  const registeredSet = new Set(registered);
  const seen = new Set<string>();
  let valid = 0;
  const n = Math.min(pubkeys.length, signatures.length);
  for (let i = 0; i < n; i++) {
    const pubkeyHex = pubkeys[i];
    const sigHex = signatures[i];
    if (seen.has(pubkeyHex) || !registeredSet.has(pubkeyHex)) {
      continue;
    }
    const ok = await verifyEd25519Vote(pubkeyHex, sigHex, message);
    if (!ok) {
      continue;
    }
    valid += 1;
    seen.add(pubkeyHex);
  }
  return valid;
}

/** Mirror of `count_valid_votes`: resolve()-verdict-specific convenience wrapper. */
export async function countValidVotes(
  pubkeys: string[],
  signatures: string[],
  registered: readonly string[],
  serviceHash: string,
  inFavorOf: string,
): Promise<number> {
  return countValidVotesForMessage(pubkeys, signatures, registered, buildResolveMessage(serviceHash, inFavorOf));
}

/** Mirror of `count_valid_cap_approval_votes`. */
export async function countValidCapApprovalVotes(
  pubkeys: string[],
  signatures: string[],
  registered: readonly string[],
  action: "release" | "reveal_swap",
  serviceHash: string,
): Promise<number> {
  return countValidVotesForMessage(pubkeys, signatures, registered, buildCapApprovalMessage(action, serviceHash));
}

/** Mirror of `count_valid_insurance_claim_votes`. */
export async function countValidInsuranceClaimVotes(
  pubkeys: string[],
  signatures: string[],
  registered: readonly string[],
  escrowId: string,
  claimantAccountHash: string,
  amount: number,
): Promise<number> {
  return countValidVotesForMessage(
    pubkeys,
    signatures,
    registered,
    buildInsuranceClaimMessage(escrowId, claimantAccountHash, amount),
  );
}
