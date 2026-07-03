import React from 'react';
import { CheckCircle2, ShieldCheck, Unplug, WalletCards } from 'lucide-react';
import { connectWallet, detectCasperWallet, disconnectWallet, shortKey, useHostedDemoIdentity, type WalletState } from '../../lib/wallet';

const WalletStatus: React.FC = () => {
  const [state, setState] = React.useState<WalletState>(() => useHostedDemoIdentity());
  const [busy, setBusy] = React.useState(false);
  const providerDetected = detectCasperWallet();

  const handleConnect = async () => {
    setBusy(true);
    try {
      const next = await connectWallet();
      setState(next.connected ? next : useHostedDemoIdentity());
    } finally {
      setBusy(false);
    }
  };

  const handleDemo = () => setState(useHostedDemoIdentity());
  const handleDisconnect = () => setState(disconnectWallet());

  const mode = state.connected && !state.simulated ? 'Casper Wallet connected' : 'Hosted demo x402 signer';
  const description = state.connected && !state.simulated
    ? 'Wallet is visible for account inspection. Write actions still require a compatible x402 Ed25519 signature path; API results show live backend transaction hashes.'
    : 'Hosted console writes use an explicitly labelled demo X-Payment header; backend rejects it unless the demo marker and sender match. Production SDK/agent calls use real Ed25519 x402 signatures.';

  return (
    <div className="border-t border-ae-border/70 bg-[#0d0d14]/95">
      <div className="ae-section py-2.5 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between text-xs">
        <div className="flex items-start gap-2 text-gray-300">
          {state.connected && !state.simulated ? <WalletCards className="h-4 w-4 text-green-400 mt-0.5" /> : <ShieldCheck className="h-4 w-4 text-amber-400 mt-0.5" />}
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-gray-100">{mode}</span>
              <span className={`rounded-full px-2 py-0.5 ${providerDetected ? 'bg-green-500/10 text-green-300 border border-green-500/30' : 'bg-amber-500/10 text-amber-200 border border-amber-500/30'}`}>
                {providerDetected ? 'Casper extension detected' : 'Casper extension not detected'}
              </span>
              {state.publicKey && <span className="font-mono text-gray-500">{shortKey(state.publicKey)}</span>}
            </div>
            <p className="mt-0.5 text-gray-500 max-w-4xl">{description}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={handleConnect}
            disabled={busy || !providerDetected}
            className="inline-flex items-center gap-1.5 rounded-lg border border-ae-border px-3 py-1.5 text-gray-200 hover:border-ae-accent disabled:opacity-45 disabled:cursor-not-allowed"
          >
            <CheckCircle2 className="h-3.5 w-3.5" /> {busy ? 'Connecting…' : 'Connect wallet'}
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
