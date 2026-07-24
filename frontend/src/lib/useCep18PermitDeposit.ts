/**
 * Gasless CEP-18 permit deposit hook for live-wallet Alt-Token Escrow
 * creation (see cep18Permit.ts + server/multi_asset.py PermitProof).
 *
 * Flow: fetch the owner's current on-chain permit nonce -> build the
 * canonical permit message -> sign it with the connected wallet (no tx, no
 * gas) -> sign a genuine x402 payment header with the same wallet (so the
 * backend's recorded escrow `sender` really is this wallet, not a demo
 * identity) -> POST /escrow/multi-asset with both. The backend then
 * submits (and pays gas for) `permit()` + `transfer_from()` on-chain,
 * moving real funds out of the owner's own balance -- see
 * Cep18Adapter.transfer_to_escrow.
 */
import { api, type MultiAssetEscrowRequest, type TransactionHash } from './api'
import { useSigner, useClickRef } from './signer'
import { buildPermitMessage, signPermitMessage, buildLiveXPaymentHeader } from './cep18Permit'
import { PublicKey } from 'casper-js-sdk'
import { useRole } from './role'

export type Cep18PermitDepositResult =
  | { ok: true; result: TransactionHash }
  | { ok: false; cancelled: true }
  | { ok: false; cancelled: false; error: string }

export function useCep18PermitDeposit() {
  const { isLive, activePublicKey } = useSigner()
  const { clickRef } = useClickRef()
  const { isObserver, blockedReason } = useRole()

  async function run(req: Omit<MultiAssetEscrowRequest, 'permit'>): Promise<Cep18PermitDepositResult> {
    if (isObserver) {
      return { ok: false, cancelled: false, error: blockedReason }
    }
    if (!isLive || !clickRef || !activePublicKey) {
      return { ok: false, cancelled: false, error: 'Wallet not connected' }
    }
    if (!req.token.contract_hash) {
      return { ok: false, cancelled: false, error: 'CEP-18 contract hash required' }
    }
    const ownerAccountHash = PublicKey.fromHex(activePublicKey).accountHash().toPrefixedString().replace('account-hash-', '')

    const nonceRes = await api.getCep18PermitNonce(req.token.contract_hash, ownerAccountHash)
    if (nonceRes.error || !nonceRes.data) {
      return { ok: false, cancelled: false, error: nonceRes.error || 'Could not fetch permit nonce' }
    }
    const { nonce, spender_account_hash: spenderAccountHash } = nonceRes.data

    const deadline = Date.now() + 30 * 60 * 1000 // 30 minutes
    const message = buildPermitMessage(activePublicKey, spenderAccountHash, req.amount, deadline, nonce)
    const sigResult = await signPermitMessage(clickRef, activePublicKey, message)
    if (!sigResult.ok) {
      if (sigResult.cancelled) return { ok: false, cancelled: true }
      return { ok: false, cancelled: false, error: sigResult.error }
    }

    const headerResult = await buildLiveXPaymentHeader(
      clickRef,
      activePublicKey,
      req.service_hash,
      req.amount,
      'POST',
      '/escrow/multi-asset',
    )
    if (!headerResult.ok) {
      if (headerResult.cancelled) return { ok: false, cancelled: true }
      return { ok: false, cancelled: false, error: headerResult.error || 'Failed to sign payment header' }
    }

    const fullReq: MultiAssetEscrowRequest = {
      ...req,
      permit: { owner_account_hash: ownerAccountHash, deadline, signature: sigResult.signatureHex },
    }
    const res = await api.createMultiAssetEscrowLive(fullReq, headerResult.header)
    if (res.error || !res.data) {
      return { ok: false, cancelled: false, error: res.error || 'Failed to create escrow' }
    }
    return { ok: true, result: res.data }
  }

  return { run, isLive }
}
