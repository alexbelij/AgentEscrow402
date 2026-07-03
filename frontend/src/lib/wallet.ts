/**
 * Casper Wallet detection for the console.
 *
 * Important: the hosted browser console still sends the labelled demo x402
 * header for write actions unless an integration provides a compatible Ed25519
 * x402 signer. This module is intentionally honest: no silent "simulated
 * wallet connection" is returned from connectWallet().
 */

const DEMO_PUBLIC_KEY = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
const DEMO_ACCOUNT_HASH = 'hosted-console-demo-identity'

export interface WalletState {
  connected: boolean
  publicKey: string | null
  accountHash: string | null
  simulated: boolean
  providerDetected: boolean
}

interface CasperWalletApi {
  requestConnection: () => Promise<boolean>
  getActivePublicKey: () => Promise<string>
  signMessage?: (message: string, publicKey?: string) => Promise<string>
}

export function detectCasperWallet(): boolean {
  return typeof window !== 'undefined' && !!(window as unknown as Record<string, unknown>).CasperWalletProvider
}

export async function connectWallet(): Promise<WalletState> {
  const providerDetected = detectCasperWallet()
  if (!providerDetected) {
    return { connected: false, publicKey: null, accountHash: null, simulated: false, providerDetected }
  }

  const providerFactory = (window as unknown as Record<string, unknown>).CasperWalletProvider as () => CasperWalletApi
  const wallet = providerFactory()
  const ok = await wallet.requestConnection()
  if (!ok) return { connected: false, publicKey: null, accountHash: null, simulated: false, providerDetected }
  const publicKey = await wallet.getActivePublicKey()
  return {
    connected: true,
    publicKey,
    accountHash: null,
    simulated: false,
    providerDetected,
  }
}

export function useHostedDemoIdentity(): WalletState {
  return {
    connected: true,
    publicKey: DEMO_PUBLIC_KEY,
    accountHash: DEMO_ACCOUNT_HASH,
    simulated: true,
    providerDetected: detectCasperWallet(),
  }
}

export function disconnectWallet(): WalletState {
  return { connected: false, publicKey: null, accountHash: null, simulated: false, providerDetected: detectCasperWallet() }
}

export function shortKey(key: string): string {
  if (key.length <= 18) return key
  return key.slice(0, 10) + '…' + key.slice(-8)
}
