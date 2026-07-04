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
  CLValue,
  ContractCallBuilder,
  PublicKey,
} from 'casper-js-sdk'
import type { ICSPRClickSDK } from '@make-software/csprclick-core-types'

export const CASPER_CHAIN_NAME = 'casper-test'
export const LIFECYCLE_PAYMENT_MOTES = 5_000_000_000 // matches lifecycle.mjs

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
    const tx = new ContractCallBuilder()
      .byHash(opts.contractHash)
      .entryPoint(opts.entryPoint)
      .runtimeArgs(Args.fromMap({ service_hash: CLValue.newCLString(opts.serviceHash) }))
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
