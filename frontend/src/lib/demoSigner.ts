/**
 * Local, in-browser Ed25519 keypairs for console demo flows that require a
 * genuine cryptographic signature the backend actually verifies (identity
 * capability delegation, x402 payment headers) but are not Casper wallet
 * transactions.
 *
 * This is deliberately separate from `wallet.ts` / `signer.tsx` (Casper
 * Wallet / CSPR.click, used for real on-chain transactions): these keys
 * never touch the blockchain, are generated fresh in memory, and are only
 * ever labelled "local demo keypair" in the UI — never presented as a real
 * wallet identity.
 */
import * as ed from '@noble/ed25519'
import { sha512 } from '@noble/hashes/sha512'
import { sha256 } from '@noble/hashes/sha256'
import { bytesToHex } from '@noble/hashes/utils'

// @noble/ed25519 v1 needs a sha512 implementation injected; @noble/hashes
// gives us a synchronous one so both sign() and getPublicKey() work without
// relying on Node's crypto (browser-safe).
ed.utils.sha512Sync = (...messages: Uint8Array[]) => sha512(ed.utils.concatBytes(...messages))

export interface DemoKeypair {
  publicKeyHex: string
  privateKeyHex: string
}

export function generateDemoKeypair(): DemoKeypair {
  const privateKey = ed.utils.randomPrivateKey()
  const publicKey = ed.sync.getPublicKey(privateKey)
  return {
    publicKeyHex: ed.utils.bytesToHex(publicKey),
    privateKeyHex: ed.utils.bytesToHex(privateKey),
  }
}

/** Sign an arbitrary UTF-8 message with a locally-held demo private key, hex-encoded (matches backend's 128-char hex signature fields). */
export function signDemoMessage(message: string, privateKeyHex: string): string {
  const sig = ed.sync.sign(new TextEncoder().encode(message), ed.utils.hexToBytes(privateKeyHex))
  return ed.utils.bytesToHex(sig)
}

/** Hex-encoded SHA-256 digest of a UTF-8 string — mirrors the backend's `hashlib.sha256(msg.encode()).hexdigest()` used as the canonical delegation message. */
export function sha256Hex(message: string): string {
  return bytesToHex(sha256(new TextEncoder().encode(message)))
}
