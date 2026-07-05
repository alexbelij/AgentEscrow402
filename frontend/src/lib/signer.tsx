/**
 * Shared "who is signing write actions right now" state for the whole
 * console, so every escrow-action UI (Escrows, Contracts, Sandbox,
 * AgentDemo) agrees with the WalletStatus bar on demo vs. live mode instead
 * of each component tracking its own local copy.
 *
 * Two explicit modes, never blended (see WalletStatus.tsx doc comment):
 *  - 'demo': hosted, clearly-labelled demo identity, backend signs with its
 *    own hosted key. Default, zero setup.
 *  - 'live': a real CSPR.click wallet session. The connected wallet's own
 *    public key is used as sender/caller, and write actions are built +
 *    signed + submitted in the browser via `clickRef.send()` — the backend
 *    only verifies on-chain state afterwards (see `lib/liveTx.ts`).
 */
import { createContext, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useClickRef } from './click'
import { disconnectWallet, useHostedDemoIdentity, type WalletState } from './wallet'

export type SignerMode = 'demo' | 'live'

type SignerContextState = {
  mode: SignerMode
  isLive: boolean
  activePublicKey: string | undefined
  ready: boolean
  connect: () => void
  useDemo: () => void
  disconnect: () => void
}

const SignerContext = createContext<SignerContextState | undefined>(undefined)

export const SignerProvider = ({ children }: { children: ReactNode }) => {
  const { clickRef, publicKey: livePublicKey, ready } = useClickRef()
  const [demoState, setDemoState] = useState<WalletState>(() => useHostedDemoIdentity())
  const [mode, setMode] = useState<SignerMode>('demo')

  const isLive = mode === 'live' && !!livePublicKey
  const activePublicKey = isLive ? livePublicKey : demoState.publicKey || undefined

  const value = useMemo<SignerContextState>(
    () => ({
      mode,
      isLive,
      activePublicKey,
      ready,
      connect: () => {
        setMode('live')
        // If a CSPR.click session is already alive (e.g. the visitor switched
        // to the demo signer and back without disconnecting), just switch
        // the active mode back to it instead of popping the wallet-select
        // dialog again for an already-connected account.
        if (!livePublicKey) clickRef?.signIn()
      },
      useDemo: () => {
        setMode('demo')
        setDemoState(useHostedDemoIdentity())
      },
      disconnect: () => {
        if (mode === 'live') clickRef?.signOut()
        setMode('demo')
        setDemoState(disconnectWallet())
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mode, isLive, activePublicKey, ready, clickRef],
  )

  return <SignerContext.Provider value={value}>{children}</SignerContext.Provider>
}

export function useSigner(): SignerContextState {
  const ctx = useContext(SignerContext)
  if (!ctx) throw new Error('useSigner() must be used within <SignerProvider>')
  return ctx
}

/** Re-exported so components that need the raw CSPR.click ref for send() can get it in one import. */
export { useClickRef } from './click'
