/**
 * CSPR.click SDK integration.
 *
 * Provides a React context (`ClickProvider` / `useClickRef`) around the
 * CSPR.click Web SDK (https://docs.cspr.click), which is the officially
 * documented way to connect a real Casper Wallet (or Ledger / MetaMask
 * Snap) from the browser and request a live signature + submission for a
 * transaction.
 *
 * This is intentionally separate from `wallet.ts` (the honest demo-signer
 * used by default in the console): connecting here means the visitor's own
 * wallet extension will pop up and they sign with their own key. Nothing is
 * auto-connected or simulated in this file.
 */
import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { CONTENT_MODE, WALLET_KEYS } from '@make-software/csprclick-core-types'
import type { AccountType, CsprClickInitOptions, ICSPRClickSDK } from '@make-software/csprclick-core-types'
import type { ClickUIOptions } from '@make-software/csprclick-core-types/clickui'

declare global {
  interface Window {
    clickUIOptions: ClickUIOptions
    clickSDKOptions: CsprClickInitOptions
    csprclick?: ICSPRClickSDK
  }
}

// Public demo appId until a dedicated one is registered at console.cspr.build.
// Analytics/rate-limiting only — does not affect signing correctness.
const CSPRCLICK_APP_ID = (import.meta.env.VITE_CSPRCLICK_APP_ID as string | undefined) || 'csprclick-template'

window.clickUIOptions = {
  uiContainer: 'csprclick-ui',
  rootAppElement: '#root',
  showTopBar: false, // AE402 has its own Navbar; we render our own connect button
  defaultTheme: 'dark',
  accountMenuItems: ['AccountCardMenuItem', 'CopyHashMenuItem'],
}

window.clickSDKOptions = {
  appName: 'AgentEscrow402',
  appId: CSPRCLICK_APP_ID,
  providers: [WALLET_KEYS.CASPER_WALLET, WALLET_KEYS.LEDGER, WALLET_KEYS.METAMASK_SNAP],
  contentMode: CONTENT_MODE.IFRAME,
}

type ClickContextState = {
  publicKey: string | undefined
  provider: string | undefined
  clickRef: ICSPRClickSDK | undefined
  ready: boolean
}

type AccountChangedEvent = { account?: AccountType }

const ClickContext = createContext<ClickContextState | undefined>(undefined)

export const ClickProvider = ({ children }: { children: ReactNode }) => {
  const [connectedAccount, setConnectedAccount] = useState<AccountType | undefined>()
  const [clickRef, setClickRef] = useState<ICSPRClickSDK | undefined>()
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const checkActiveAccount = async (ref: ICSPRClickSDK) => {
      try {
        const account = await ref.getActiveAccountAsync({ withBalance: false })
        setConnectedAccount(account?.public_key ? account : undefined)
      } catch (error) {
        console.error('CSPR.click: failed to get active account', error)
        setConnectedAccount(undefined)
      }
    }

    const handleAccountChanged = (event: AccountChangedEvent) => {
      setConnectedAccount(event.account?.public_key ? event.account : undefined)
    }

    const handleSdkLoaded = () => {
      const ref = window.csprclick
      if (!ref) return
      setClickRef(ref)
      setReady(true)
      ref.on('csprclick:signed_in', handleAccountChanged)
      ref.on('csprclick:switched_account', handleAccountChanged)
      ref.on('csprclick:unsolicited_account_change', handleAccountChanged)
      ref.on('csprclick:signed_out', () => setConnectedAccount(undefined))
      ref.on('csprclick:disconnected', () => setConnectedAccount(undefined))
      checkActiveAccount(ref)
    }

    window.addEventListener('csprclick:loaded', handleSdkLoaded)
    if (window.csprclick) handleSdkLoaded()

    if (!document.querySelector('script#csprclick-client')) {
      const script = document.createElement('script')
      script.src = 'https://cdn.cspr.click/ui/v2.1.0/csprclick-client-2.1.0.js'
      script.id = 'csprclick-client'
      script.async = true
      document.head.appendChild(script)
    }

    return () => window.removeEventListener('csprclick:loaded', handleSdkLoaded)
  }, [])

  return (
    <ClickContext.Provider
      value={{ publicKey: connectedAccount?.public_key, provider: connectedAccount?.provider, clickRef, ready }}
    >
      {children}
    </ClickContext.Provider>
  )
}

export const useClickRef = (): ClickContextState => {
  const ctx = useContext(ClickContext)
  if (!ctx) throw new Error('useClickRef must be used within a ClickProvider')
  return ctx
}
