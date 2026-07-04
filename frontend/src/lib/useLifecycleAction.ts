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
      if (!sendResult.ok) return sendResult

      const body: EscrowActionRequest & { wallet_tx_hash: string } = {
        service_hash: serviceHash,
        wallet_tx_hash: sendResult.transactionHash,
        ...(reasonHash ? { reason_hash: reasonHash } : {}),
      }
      const confirmRes = await callHostedEndpoint(entryPoint, body)
      if (confirmRes.error) return { ok: false, cancelled: false, error: confirmRes.error }
      return { ok: true, deployHash: sendResult.transactionHash }
    }

    // Demo mode — unchanged hosted-key path.
    const body: EscrowActionRequest = { service_hash: serviceHash, ...(reasonHash ? { reason_hash: reasonHash } : {}) }
    const res = await callHostedEndpoint(entryPoint, body)
    if (res.error) return { ok: false, cancelled: false, error: res.error }
    return { ok: true, deployHash: res.data?.deploy_hash || '' }
  }

  return { run, mode }
}

function callHostedEndpoint(entryPoint: LifecycleEntryPoint, body: EscrowActionRequest): Promise<ApiResponse<TransactionHash>> {
  if (entryPoint === 'release') return api.releaseEscrow(body)
  if (entryPoint === 'refund') return api.refundEscrow(body)
  return api.disputeEscrow(body)
}
