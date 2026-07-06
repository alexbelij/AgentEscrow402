/**
 * CEP-2612-inspired gasless permit helpers (see contracts/ fork docs in
 * skills/integrations/casper/SKILL.md and server/multi_asset.py
 * PermitProof). Two distinct off-chain signatures are needed here, with
 * two different encodings -- don't mix them up:
 *
 * 1. The **permit message** itself: verified on-chain by the CEP-18
 *    contract's `permit()` entry point via `casper_types::crypto::verify`,
 *    which expects a Casper-tag-prefixed signature (0x01 ed25519 / 0x02
 *    secp256k1 + raw bytes) -- see buildPermitMessage/signPermit below.
 * 2. The **x402 payment header** signature: verified server-side by
 *    `server/middleware.py::_verify_signature`, which expects a bare,
 *    untagged pubkey (32-byte Ed25519 or 33-byte compressed secp256k1) +
 *    64-byte signature -- see buildLiveXPaymentHeader below. Both Ed25519
 *    (`_verify_ed25519`) and secp256k1 (`_verify_secp256k1`, compact r||s
 *    re-encoded as DER for the `cryptography` lib) are supported.
 */
import type { ICSPRClickSDK } from '@make-software/csprclick-core-types'

export type PermitSignResult =
  | { ok: true; signatureHex: string }
  | { ok: false; cancelled: true }
  | { ok: false; cancelled: false; error: string }

/** Casper-tag-prefixed account-hash bytes for a Key::Account, base64-encoded
 * -- must byte-for-byte match the Rust side's
 * `base64_encode(spender.to_bytes())` (see contracts/cep18 fork's
 * permit() -- allowances.rs/main.rs in skills/integrations/casper). */
function spenderKeyBase64(spenderAccountHashHex: string): string {
  const bytes = new Uint8Array(33)
  bytes[0] = 0x00 // Key::Account tag
  const acctBytes = hexToBytes(spenderAccountHashHex)
  bytes.set(acctBytes, 1)
  return bytesToBase64(bytes)
}

function hexToBytes(hex: string): Uint8Array {
  const clean = hex.length % 2 === 0 ? hex : `0${hex}`
  const out = new Uint8Array(clean.length / 2)
  for (let i = 0; i < out.length; i++) out[i] = parseInt(clean.substr(i * 2, 2), 16)
  return out
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  for (const b of bytes) binary += String.fromCharCode(b)
  return btoa(binary)
}

/** Canonical permit message -- must match the Rust contract's `format!`
 * byte-for-byte (see permit() in the cep18 fork's main.rs). */
export function buildPermitMessage(
  ownerPublicKeyHex: string,
  spenderAccountHashHex: string,
  amount: number | string,
  deadlineMs: number,
  nonce: number,
): string {
  return `ae402-cep18-permit:${ownerPublicKeyHex.toLowerCase()}:${spenderKeyBase64(spenderAccountHashHex)}:${amount}:${deadlineMs}:${nonce}`
}

/** Signs the permit message via the connected wallet and returns a
 * Casper-tag-prefixed signature hex ready to send to the backend /
 * on-chain `permit()` call. */
export async function signPermitMessage(
  clickRef: ICSPRClickSDK,
  ownerPublicKeyHex: string,
  message: string,
): Promise<PermitSignResult> {
  try {
    const res = await clickRef.signMessage(message, ownerPublicKeyHex)
    if (!res || res.cancelled || !res.signatureHex) return { ok: false, cancelled: true }
    // ed25519-only: Casper's algorithm tag is the public key's own first
    // hex byte (01=ed25519, 02=secp256k1) -- reuse it for the signature.
    const tag = ownerPublicKeyHex.slice(0, 2).toLowerCase()
    return { ok: true, signatureHex: `${tag}${res.signatureHex.toLowerCase()}` }
  } catch (e) {
    return { ok: false, cancelled: false, error: e instanceof Error ? e.message : String(e) }
  }
}

/** Builds + signs a genuine (non-demo) X-Payment header with the connected
 * wallet, matching server/middleware.py's `_build_signing_payload` exactly
 * (`version;escrow_hash;amount;sender;timestamp;nonce;method;path`). Works
 * for both Ed25519 and secp256k1 wallets -- `_verify_signature` dispatches
 * on the raw pubkey length (32 bytes vs 33-byte compressed). Just strip the
 * 1-byte Casper algorithm tag; `ownerPublicKeyHexTagged` must be the tagged
 * hex CSPR.click hands back (`01...` or `02...`). */
export async function buildLiveXPaymentHeader(
  clickRef: ICSPRClickSDK,
  ownerPublicKeyHexTagged: string,
  escrowHash: string,
  amount: number,
  method: string,
  path: string,
): Promise<{ ok: true; header: string } | { ok: false; cancelled: boolean; error?: string }> {
  const tag = ownerPublicKeyHexTagged.slice(0, 2).toLowerCase()
  if (tag !== '01' && tag !== '02') {
    return { ok: false, cancelled: false, error: 'Unsupported wallet key type for gasless permit deposit.' }
  }
  const rawSenderHex = ownerPublicKeyHexTagged.slice(2).toLowerCase()
  const timestamp = Math.floor(Date.now() / 1000)
  const nonce = Array.from(crypto.getRandomValues(new Uint8Array(16)))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
  const payload = `x402-v1;${escrowHash};${amount};${rawSenderHex};${timestamp};${nonce};${method};${path}`
  try {
    const res = await clickRef.signMessage(payload, ownerPublicKeyHexTagged)
    if (!res || res.cancelled || !res.signatureHex) return { ok: false, cancelled: true }
    const header = `x402-v1;${escrowHash};${amount};${rawSenderHex};${timestamp};${nonce};${res.signatureHex.toLowerCase()}`
    return { ok: true, header }
  } catch (e) {
    return { ok: false, cancelled: false, error: e instanceof Error ? e.message : String(e) }
  }
}
