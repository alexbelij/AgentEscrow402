import React from 'react';
import { CheckCircle2, ShieldCheck, Unplug, WalletCards } from 'lucide-react';
import { useClickRef } from '../../lib/click';
import { disconnectWallet, shortKey, useHostedDemoIdentity, type WalletState } from '../../lib/wallet';

/**
 * Two explicit, clearly-labelled identity modes for the console:
 *
 * 1. "Demo signer" (default) — a hosted, honest, clearly-labelled demo
 *    identity for fast walkthroughs with no wallet extension required.
 * 2. "Connect wallet" — a REAL Casper Wallet / Ledger / MetaMask Snap
 *    session via the official CSPR.click SDK. The visitor signs with their
 *    own key and their own wallet popup; nothing is simulated.
 *
 * These are never blended: exactly one is active, and the badge below
 * always reflects which one.
 */
const WalletStatus: React.FC = () => {
  const { clickRef, publicKey: livePublicKey, ready } = useClickRef();
  const [demoState, setDemoState] = React.useState<WalletState>(() => useHostedDemoIdentity());
  const [mode, setMode] = React.useState<'demo' | 'live'>('demo');

  const connected = mode === 'live' && !!livePublicKey;
  const activePublicKey = mode === 'live' ? livePublicKey : demoState.publicKey;

  const handleConnect = () => {
    setMode('live');
    clickRef?.signIn();
  };

  const handleDemo = () => {
    setMode('demo');
    setDemoState(useHostedDemoIdentity());
  };

  const handleDisconnect = () => {
    if (mode === 'live') clickRef?.signOut();
    setMode('demo');
    setDemoState(disconnectWallet());
  };

  const label = connected ? 'Casper Wallet connected (live signing)' : 'Hosted demo signer';
  const description = connected
    ? 'Real wallet session via CSPR.click. Write actions in the console below are signed by your own key and submitted to Casper testnet — you will see a wallet popup to approve each one.'
    : 'Hosted console writes use an explicitly labelled demo identity so you can try every flow with zero setup. Switch to "Connect wallet" to sign real testnet transactions with your own Casper Wallet.';

  return (
    <div className="border-t border-ae-border/70 bg-[#0d0d14]/95">
      <div className="ae-section py-2.5 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between text-xs">
        <div className="flex items-start gap-2 text-gray-300">
          {connected ? <WalletCards className="h-4 w-4 text-green-400 mt-0.5" /> : <ShieldCheck className="h-4 w-4 text-amber-400 mt-0.5" />}
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-gray-100">{label}</span>
              <span className={`rounded-full px-2 py-0.5 border ${connected ? 'bg-green-500/10 text-green-300 border-green-500/30' : 'bg-amber-500/10 text-amber-200 border-amber-500/30'}`}>
                {connected ? 'Live · your key' : 'Demo · not your key'}
              </span>
              {activePublicKey && <span className="font-mono text-gray-500">{shortKey(activePublicKey)}</span>}
            </div>
            <p className="mt-0.5 text-gray-500 max-w-4xl">{description}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={handleConnect}
            disabled={!ready}
            className="inline-flex items-center gap-1.5 rounded-lg border border-ae-border px-3 py-1.5 text-gray-200 hover:border-ae-accent disabled:opacity-45 disabled:cursor-not-allowed"
          >
            <CheckCircle2 className="h-3.5 w-3.5" /> {ready ? 'Connect wallet' : 'Loading wallet SDK…'}
          </button>
          <button type="button" onClick={handleDemo} className="rounded-lg border border-ae-border px-3 py-1.5 text-gray-300 hover:border-ae-accent">
            Demo signer
          </button>
          <button type="button" onClick={handleDisconnect} className="inline-flex items-center gap-1 rounded-lg border border-transparent px-2 py-1.5 text-gray-500 hover:text-gray-200">
            <Unplug className="h-3.5 w-3.5" /> Disconnect
          </button>
        </div>
      </div>
    </div>
  );
};

export default WalletStatus;
