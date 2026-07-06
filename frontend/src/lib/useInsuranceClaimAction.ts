/**
 * Insurance-pool `claim()` action helper — mirrors `useLifecycleAction.ts`
 * exactly (same demo-vs-live split), but for the insurance pool contract
 * instead of the escrow contract.
 *
 * - Demo mode: unchanged existing behaviour — calls `api.claimInsurance`,
 *   which the hosted backend records as a simulated pool payout.
 * - Live mode: builds + signs + submits a real `claim()` call in the
 *   browser via the connected wallet (`sendInsuranceClaimTx` — no
 *   session-wasm needed since `claim()` takes no purse argument), then
 *   tells the backend the resulting `wallet_tx_hash` + the wallet's own
 *   account hash so it can confirm the on-chain payout and update hosted
 *   records. The backend never signs or holds funds in this path.
 */
import { api, type ClaimInsuranceRequest, type TransactionHash, type ApiResponse } from './api'
import { useSigner, useClickRef } from './signer'
import { sendInsuranceClaimTx } from './liveTx'
import { PublicKey } from 'casper-js-sdk'

export type InsuranceClaimActionResult =
  | { ok: true; deployHash: string }
  | { ok: false; cancelled: true }
  | { ok: false; cancelled: false; error: string }

function friendlyNetworkError(rawError: string): string {
  if (/failed to fetch|networkerror|load failed/i.test(rawError)) {
    return 'Network hiccup while submitting to your wallet — nothing was signed or sent on-chain. Please try again.'
  }
  return rawError
}

export function useInsuranceClaimAction() {
  const { isLive, activePublicKey } = useSigner()
  const { clickRef } = useClickRef()

  async function run(
    escrowHash: string,
    reason: string,
    amountMotes: number | string,
    insuranceContractHash: string | undefined,
  ): Promise<InsuranceClaimActionResult> {
    if (isLive) {
      if (!clickRef || !activePublicKey) {
        return { ok: false, cancelled: false, error: 'Wallet not connected' }
      }
      if (!insuranceContractHash) {
        return { ok: false, cancelled: false, error: 'Insurance contract hash unavailable — cannot build a live transaction' }
      }
      const sendResult = await sendInsuranceClaimTx(clickRef, {
        insuranceContractHash,
        escrowId: escrowHash,
        amountMotes,
        evidence: reason,
        senderPublicKeyHex: activePublicKey,
      })
      if (!sendResult.ok) {
        if (sendResult.cancelled) return sendResult
        return { ...sendResult, error: friendlyNetworkError(sendResult.error) }
      }

      const claimantAccountHash = PublicKey.fromHex(activePublicKey).accountHash().toPrefixedString()
      const body: ClaimInsuranceRequest = {
        escrow_hash: escrowHash,
        reason,
        wallet_tx_hash: sendResult.transactionHash,
        sender_public_key_hex: activePublicKey,
        claimant_account_hash: claimantAccountHash,
      }
      const confirmRes = await api.claimInsurance(body)
      if (confirmRes.error) {
        return {
          ok: false,
          cancelled: false,
          error: `Transaction ${sendResult.transactionHash} was submitted to your wallet, but confirming it with our backend failed (${friendlyNetworkError(confirmRes.error)}). Refresh the pool stats in a moment before retrying — the claim may already have paid out.`,
        }
      }
      return { ok: true, deployHash: sendResult.transactionHash }
    }

    // Demo mode — unchanged hosted-key path.
    const res: ApiResponse<TransactionHash> = await api.claimInsurance({ escrow_hash: escrowHash, reason })
    if (res.error) return { ok: false, cancelled: false, error: friendlyNetworkError(res.error) }
    return { ok: true, deployHash: res.data?.deploy_hash || '' }
  }

  return { run, isLive }
}
