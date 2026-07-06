/**
 * Client-side transaction building for the "Connect wallet" (live) signing
 * path — mirrors `server/casper_tx/lifecycle.mjs` exactly (same contract
 * call shape, same 5 CSPR payment amount) but builds and signs the
 * transaction in the browser via the connected wallet instead of the
 * backend's hosted key.
 *
 * Flow for release/refund/dispute in live mode:
 *   1. Build a ContractCallBuilder tx here, calling the escrow contract's
 *      entry point directly, `.from(connectedWalletPublicKey)`.
 *   2. Hand it to `clickRef.send(tx, sender, onStatusUpdate)` — this pops
 *      the user's own wallet (Casper Wallet/Ledger/MetaMask Snap) to review
 *      and sign, then submits it to a Casper node itself.
 *   3. Once we have a transaction hash, tell the backend via
 *      `wallet_tx_hash` — the backend does NOT sign or submit anything in
 *      this path, it only polls on-chain contract state until it reflects
 *      the expected status before touching hosted records (see
 *      `CasperClient.confirm_wallet_lifecycle_tx` in the backend).
 *
 * This only works if the connected wallet account is genuinely the escrow's
 * sender (release/refund) or sender/receiver (dispute) — the contract's own
 * `get_caller()` check enforces this on-chain; there is no way around it
 * from the frontend, by design.
 */
import {
  Args,
  CLTypeString,
  CLValue,
  ContractCallBuilder,
  PublicKey,
  SessionBuilder,
} from 'casper-js-sdk'
import type { ICSPRClickSDK } from '@make-software/csprclick-core-types'

export const CASPER_CHAIN_NAME = 'casper-test'
export const LIFECYCLE_PAYMENT_MOTES = 5_000_000_000 // matches lifecycle.mjs
// Matches server/casper_tx/create_escrow.mjs — proven sufficient for the
// escrow_funder.wasm session module (deploy + one purse-to-purse transfer).
export const CREATE_ESCROW_PAYMENT_MOTES = 12_000_000_000

function hexToBytes(hex: string): Uint8Array {
  const clean = hex.length % 2 === 0 ? hex : `0${hex}`
  const out = new Uint8Array(clean.length / 2)
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(clean.substring(i * 2, i * 2 + 2), 16)
  }
  return out
}

export type LifecycleEntryPoint = 'release' | 'refund' | 'dispute'

export type LiveTxResult =
  | { ok: true; transactionHash: string }
  | { ok: false; cancelled: true }
  | { ok: false; cancelled: false; error: string }

/**
 * Build + sign + submit a release/refund/dispute call via the connected
 * wallet. Returns the transaction hash on success, or a typed
 * cancelled/error result — never throws, so callers can render each case.
 */
export async function sendLifecycleTx(
  clickRef: ICSPRClickSDK,
  opts: {
    contractHash: string
    entryPoint: LifecycleEntryPoint
    serviceHash: string
    senderPublicKeyHex: string
  },
): Promise<LiveTxResult> {
  try {
    // The contract's `release` (and `reveal_swap`) entry points always read
    // `arbiter_pubkeys`/`arbiter_signatures` via `get_named_arg` even when
    // the escrow is under the arbiter-approval cap (they're only *used* when
    // over-cap, but must still be *present* as empty lists or the call
    // reverts with `ApiError::MissingArgument [2]`). `refund`/`dispute` take
    // only `service_hash`. Mirrors `server/casper_tx/lifecycle.mjs`.
    const argsMap: Record<string, CLValue> = {
      service_hash: CLValue.newCLString(opts.serviceHash),
    }
    if (opts.entryPoint === 'release') {
      argsMap.arbiter_pubkeys = CLValue.newCLList(CLTypeString, [])
      argsMap.arbiter_signatures = CLValue.newCLList(CLTypeString, [])
    }

    const tx = new ContractCallBuilder()
      .byHash(opts.contractHash)
      .entryPoint(opts.entryPoint)
      .runtimeArgs(Args.fromMap(argsMap))
      .from(PublicKey.fromHex(opts.senderPublicKeyHex))
      .chainName(CASPER_CHAIN_NAME)
      .payment(LIFECYCLE_PAYMENT_MOTES)
      .build()

    const res = await clickRef.send(tx.toJSON() as object, opts.senderPublicKeyHex)

    if (res?.transactionHash) {
      return { ok: true, transactionHash: res.transactionHash }
    }
    if (res?.cancelled) {
      return { ok: false, cancelled: true }
    }
    const rawError = (res as any)?.error ?? (res as any)?.errorData ?? 'Unknown error from wallet SDK'
    const errorMessage = typeof rawError === 'string' ? rawError : JSON.stringify(rawError)
    return { ok: false, cancelled: false, error: errorMessage }
  } catch (err: any) {
    return { ok: false, cancelled: false, error: err?.message || String(err) }
  }
}

/**
 * Build + sign + submit a create-escrow deposit via the connected wallet.
 *
 * Unlike release/refund/dispute (plain `ContractCallBuilder` calls), the
 * escrow contract's `escrow()` entry point needs a `source_purse: URef` to
 * pull the deposit from — and Casper's execution engine strips access
 * rights from any purse URef passed as an external argument to a *stored*
 * contract call (confirmed on testnet: `Mint error: 4` /
 * `InvalidAccessRights`; see skills/web3_development/references/
 * wallet_frontend_gotchas.md). Only *session* code executing under the
 * signer's own account context can legitimately pull from its own main
 * purse via `account::get_main_purse()`. So this builds a `SessionBuilder`
 * transaction around `escrow_funder.wasm` (fetched from the backend, which
 * itself already runs this exact compiled module today via its hosted-key
 * flow) instead of a stored-contract-call — same wasm, now signed by the
 * connected wallet instead of the backend's PEM key.
 */
export async function sendCreateEscrowTx(
  clickRef: ICSPRClickSDK,
  opts: {
    contractHash: string
    receiverHex: string // 64-char hex account hash, no "account-hash-" prefix
    amountMotes: number | string
    serviceHash: string
    ttlSeconds: number
    senderPublicKeyHex: string
    wasmBytes: Uint8Array
  },
): Promise<LiveTxResult> {
  try {
    const args = Args.fromMap({
      contract: CLValue.newCLByteArray(hexToBytes(opts.contractHash)),
      receiver: CLValue.newCLByteArray(hexToBytes(opts.receiverHex)),
      amount: CLValue.newCLUInt512(String(opts.amountMotes)),
      service_hash: CLValue.newCLString(opts.serviceHash),
      ttl: CLValue.newCLUint64(opts.ttlSeconds),
    })

    const tx = new SessionBuilder()
      .from(PublicKey.fromHex(opts.senderPublicKeyHex))
      .wasm(opts.wasmBytes)
      .runtimeArgs(args)
      .chainName(CASPER_CHAIN_NAME)
      .payment(CREATE_ESCROW_PAYMENT_MOTES)
      .build()

    const res = await clickRef.send(tx.toJSON() as object, opts.senderPublicKeyHex)

    if (res?.transactionHash) {
      return { ok: true, transactionHash: res.transactionHash }
    }
    if (res?.cancelled) {
      return { ok: false, cancelled: true }
    }
    const rawError = (res as any)?.error ?? (res as any)?.errorData ?? 'Unknown error from wallet SDK'
    const errorMessage = typeof rawError === 'string' ? rawError : JSON.stringify(rawError)
    return { ok: false, cancelled: false, error: errorMessage }
  } catch (err: any) {
    return { ok: false, cancelled: false, error: err?.message || String(err) }
  }
}

/** Fetch the compiled escrow_funder.wasm session module bytes from the backend. */
export async function fetchEscrowFunderWasm(): Promise<Uint8Array> {
  const res = await fetch('/backend/wasm/escrow_funder')
  if (!res.ok) {
    throw new Error(`Failed to fetch escrow_funder.wasm: HTTP ${res.status}`)
  }
  const buf = await res.arrayBuffer()
  return new Uint8Array(buf)
}
