/**
 * Create-escrow action helper for the live console's `/escrows` page,
 * mirroring `useLifecycleAction`'s demo/live split:
 *
 * - Demo mode: unchanged — `api.createEscrow` sends the demo `X-Payment`
 *   header, backend signs+submits with its own hosted key.
 * - Live mode: the deposit must actually come from the connected wallet's
 *   own purse. A plain `ContractCallBuilder` call (like release/refund/
 *   dispute use) can't do this — Casper strips access rights from a purse
 *   URef passed as an external contract-call argument (see
 *   `sendCreateEscrowTx` doc comment in `liveTx.ts`). So this fetches the
 *   compiled `escrow_funder.wasm` session module from the backend, builds a
 *   `SessionBuilder` transaction around it, and has the connected wallet
 *   sign + submit it directly via `clickRef.send()`. The backend is then
 *   told the resulting `wallet_tx_hash` (+ the wallet's own public key as
 *   `sender_public_key_hex`) and only polls on-chain state to confirm
 *   before creating hosted records — it never signs or submits anything in
 *   this path.
 */
import { api, type CreateEscrowRequest, type TransactionHash, type ApiResponse } from './api'
import { useSigner, useClickRef } from './signer'
import { sendCreateEscrowTx, fetchEscrowFunderWasm } from './liveTx'

export type CreateEscrowActionResult =
  | { ok: true; deployHash: string }
  | { ok: false; cancelled: true }
  | { ok: false; cancelled: false; error: string }

function friendlyNetworkError(rawError: string): string {
  if (/failed to fetch|networkerror|load failed/i.test(rawError)) {
    return 'Network hiccup while submitting to your wallet — nothing was signed or sent on-chain. Please try again.'
  }
  return rawError
}

export function useCreateEscrowAction() {
  const { isLive, activePublicKey } = useSigner()
  const { clickRef } = useClickRef()

  async function run(
    formData: CreateEscrowRequest,
    contractHash: string | undefined,
    netAmountMotes: number,
  ): Promise<CreateEscrowActionResult> {
    if (isLive) {
      if (!clickRef || !activePublicKey) {
        return { ok: false, cancelled: false, error: 'Wallet not connected' }
      }
      if (!contractHash) {
        return { ok: false, cancelled: false, error: 'Escrow contract hash unavailable — cannot build a live transaction' }
      }

      let wasmBytes: Uint8Array
      try {
        wasmBytes = await fetchEscrowFunderWasm()
      } catch (err: any) {
        return { ok: false, cancelled: false, error: friendlyNetworkError(err?.message || String(err)) }
      }

      const sendResult = await sendCreateEscrowTx(clickRef, {
        contractHash,
        receiverHex: formData.receiver,
        // Deposit the fee-adjusted net amount on-chain — matches what the
        // backend will record locally (see _apply_insurance_fee in app.py)
        // and what the hosted-key flow itself deposits.
        amountMotes: netAmountMotes,
        serviceHash: formData.service_hash,
        ttlSeconds: formData.ttl || 300,
        senderPublicKeyHex: activePublicKey,
        wasmBytes,
      })
      if (!sendResult.ok) {
        if (sendResult.cancelled) return sendResult
        return { ...sendResult, error: friendlyNetworkError(sendResult.error) }
      }

      const confirmRes = await api.createEscrow({
        ...formData,
        wallet_tx_hash: sendResult.transactionHash,
        sender_public_key_hex: activePublicKey,
      })
      if (confirmRes.error) {
        return {
          ok: false,
          cancelled: false,
          error: `Transaction ${sendResult.transactionHash} was submitted to your wallet, but confirming it with our backend failed (${friendlyNetworkError(confirmRes.error)}). Refresh the escrows list in a moment before retrying — the escrow may already exist on-chain.`,
        }
      }
      return { ok: true, deployHash: sendResult.transactionHash }
    }

    // Demo mode — unchanged hosted-key path.
    const res = await api.createEscrow(formData)
    if (res.error) return { ok: false, cancelled: false, error: friendlyNetworkError(res.error) }
    return { ok: true, deployHash: res.data?.deploy_hash || '' }
  }

  return { run }
}
