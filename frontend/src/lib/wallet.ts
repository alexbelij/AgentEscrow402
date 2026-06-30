/**
 * Casper Wallet integration with simulated fallback.
 *
 * If the Casper Wallet browser extension is detected, uses it.
 * Otherwise provides a demo account for testing.
 */

const DEMO_PUBLIC_KEY = '02022840bf49e6db972efad68bb731ef8621dde1c59457cd2b670a116d6ff97cd94c'
const DEMO_ACCOUNT_HASH = '74c96cd0073c4c973b70e7925adca8a4ba58ffcb9737304631381b82695007a8'

export interface WalletState {
  connected: boolean
  publicKey: string | null
  accountHash: string | null
  simulated: boolean
}

export function detectCasperWallet(): boolean {
  return typeof window !== 'undefined' && !!(window as Record<string, unknown>).CasperWalletProvider
}

export async function connectWallet(): Promise<WalletState> {
  if (detectCasperWallet()) {
    try {
      const provider = (window as Record<string, unknown>).CasperWalletProvider as () => {
        requestConnection: () => Promise<boolean>
        getActivePublicKey: () => Promise<string>
      }
      const wallet = provider()
      const ok = await wallet.requestConnection()
      if (ok) {
        const pubKey = await wallet.getActivePublicKey()
        return {
          connected: true,
          publicKey: pubKey,
          accountHash: pubKey.slice(0, 64),
          simulated: false,
        }
      }
    } catch {
      // fall through to simulation
    }
  }

  return {
    connected: true,
    publicKey: DEMO_PUBLIC_KEY,
    accountHash: DEMO_ACCOUNT_HASH,
    simulated: true,
  }
}

export function disconnectWallet(): WalletState {
  return { connected: false, publicKey: null, accountHash: null, simulated: false }
}

export function shortKey(key: string): string {
  if (key.length <= 16) return key
  return key.slice(0, 8) + '...' + key.slice(-6)
}
