/**
 * Shared release/refund/dispute action helper used by every console surface
 * that lets a visitor act on an escrow (Escrows, Contracts, AgentDemo).
 *
 * - Demo mode: unchanged existing behaviour — calls the hosted API, which
 *   signs and submits with its own hosted key (`api.releaseEscrow` etc).
 * - Live mode: builds + signs + submits the transaction in the browser via
 *   the connected wallet (`sendLifecycleTx`), then tells the backend the
 *   resulting `wallet_tx_hash` so it can confirm on-chain state and update
 *   hosted records — the backend does not sign anything in this path.
 */
import { api, type EscrowActionRequest, type TransactionHash, type ApiResponse } from './api'
import { useSigner, useClickRef } from './signer'
import { sendLifecycleTx, type LifecycleEntryPoint } from './liveTx'

export type LifecycleActionResult =
  | { ok: true; deployHash: string }
  | { ok: false; cancelled: true }
  | { ok: false; cancelled: false; error: string }

/**
 * The wallet SDK (`clickRef.send`) and our own hosted-API fetcher both
 * surface raw network failures as the browser's generic, unhelpful
 * `TypeError: Failed to fetch` message with no indication of what to do
 * next. Since nothing on-chain happens until the wallet actually submits
 * the signed transaction, a network hiccup at this stage is always safe to
 * retry — rephrase it so the user knows that instead of just seeing a
 * cryptic error.
 */
function friendlyNetworkError(rawError: string): string {
  if (/failed to fetch|networkerror|load failed/i.test(rawError)) {
    return 'Network hiccup while submitting to your wallet — nothing was signed or sent on-chain. Please try again.'
  }
  return rawError
}

export function useLifecycleAction() {
  const { mode, isLive, activePublicKey } = useSigner()
  const { clickRef } = useClickRef()

  async function run(entryPoint: LifecycleEntryPoint, serviceHash: string, contractHash: string | undefined, reasonHash?: string): Promise<LifecycleActionResult> {
    if (isLive) {
      if (!clickRef || !activePublicKey) {
        return { ok: false, cancelled: false, error: 'Wallet not connected' }
      }
      if (!contractHash) {
        return { ok: false, cancelled: false, error: 'Escrow contract hash unavailable — cannot build a live transaction' }
      }
      const sendResult = await sendLifecycleTx(clickRef, {
        contractHash,
        entryPoint,
        serviceHash,
        senderPublicKeyHex: activePublicKey,
      })
      // Nothing was signed or submitted yet at this point, so a raw network
      // error here is always safe to just retry.
      if (!sendResult.ok) {
        if (sendResult.cancelled) return sendResult
        return { ...sendResult, error: friendlyNetworkError(sendResult.error) }
      }

      const body: EscrowActionRequest & { wallet_tx_hash: string } = {
        service_hash: serviceHash,
        wallet_tx_hash: sendResult.transactionHash,
        ...(reasonHash ? { reason_hash: reasonHash } : {}),
      }
      const confirmRes = await callHostedEndpoint(entryPoint, body)
      if (confirmRes.error) {
        // The wallet already signed and submitted the transaction on-chain
        // by this point — only our backend's confirmation call failed, so
        // don't tell the user "nothing happened" or invite a duplicate
        // signature. Surface the tx hash so they can check it themselves.
        return {
          ok: false,
          cancelled: false,
          error: `Transaction ${sendResult.transactionHash} was submitted to your wallet, but confirming it with our backend failed (${friendlyNetworkError(confirmRes.error)}). Refresh the escrow in a moment before retrying — it may already show as ${entryPoint === 'release' ? 'released' : entryPoint === 'refund' ? 'refunded' : 'disputed'}.`,
        }
      }
      return { ok: true, deployHash: sendResult.transactionHash }
    }

    // Demo mode — unchanged hosted-key path.
    const body: EscrowActionRequest = { service_hash: serviceHash, ...(reasonHash ? { reason_hash: reasonHash } : {}) }
    const res = await callHostedEndpoint(entryPoint, body)
    if (res.error) return { ok: false, cancelled: false, error: friendlyNetworkError(res.error) }
    return { ok: true, deployHash: res.data?.deploy_hash || '' }
  }

  return { run, mode }
}

function callHostedEndpoint(entryPoint: LifecycleEntryPoint, body: EscrowActionRequest): Promise<ApiResponse<TransactionHash>> {
  if (entryPoint === 'release') return api.releaseEscrow(body)
  if (entryPoint === 'refund') return api.refundEscrow(body)
  return api.disputeEscrow(body)
}
