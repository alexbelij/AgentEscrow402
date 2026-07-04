import React, { useEffect, useRef, useState } from 'react';
import { Info, ShieldCheck, Unplug, WalletCards } from 'lucide-react';
import { shortKey } from '../../lib/wallet';
import { useSigner } from '../../lib/signer';

/**
 * Two explicit, clearly-labelled identity modes for the console:
 *
 * 1. "Demo signer" (default) — a hosted, honest, clearly-labelled demo
 *    identity for fast walkthroughs with no wallet extension required.
 * 2. "Connect wallet" — a REAL Casper Wallet / Ledger / MetaMask Snap
 *    session via the official CSPR.click SDK. The visitor signs with their
 *    own key and their own wallet popup; nothing is simulated.
 *
 * These are never blended: exactly one is active, and every escrow-action
 * component reads the same shared `useSigner()` state as this bar.
 *
 * UI: a segmented toggle communicates the active mode via button styling
 * alone (no separate "Demo · not your key" badge, no redundant address shown
 * twice) — the active button itself displays the connected address. Long
 * explanatory copy lives behind an (i) tooltip instead of always-on text.
 */
const WalletStatus: React.FC = () => {
  const { mode, isLive, activePublicKey, ready, connect, useDemo, disconnect } = useSigner();
  const [showInfo, setShowInfo] = useState(false);
  const infoRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showInfo) return;
    const onClickOutside = (e: MouseEvent) => {
      if (infoRef.current && !infoRef.current.contains(e.target as Node)) setShowInfo(false);
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, [showInfo]);

  const label = isLive ? 'Casper Wallet connected (live signing)' : 'Hosted demo signer';
  const description = isLive
    ? 'Real wallet session via CSPR.click. Write actions in the console below are built and signed by your own key in the browser and submitted to Casper testnet directly — you will see a wallet popup to approve each one. Only works for escrows where your connected account is the sender/receiver, since the contract itself enforces that on-chain.'
    : 'Hosted console writes use an explicitly labelled demo identity so you can try every flow with zero setup. Switch to "Connect wallet" to sign real testnet transactions with your own Casper Wallet.';

  const demoAddress = mode === 'demo' ? activePublicKey : undefined;
  const liveAddress = isLive ? activePublicKey : undefined;

  return (
    <div className="border-t border-ae-border/70 bg-[#0d0d14]/95">
      <div className="w-full px-4 sm:px-6 lg:px-8 py-2.5 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between text-xs">
        <div className="flex items-start gap-2 text-gray-300">
          {mode === 'demo' && (
            <>
              {isLive ? null : <ShieldCheck className="h-4 w-4 text-amber-400 mt-0.5" />}
              <span className="font-semibold text-gray-100">{label}</span>
            </>
          )}
          {isLive && <WalletCards className="h-4 w-4 text-green-400 mt-0.5" />}
          {isLive && <span className="font-semibold text-gray-100">{label}</span>}
          <div className="relative" ref={infoRef}>
            <button
              type="button"
              onClick={() => setShowInfo((v) => !v)}
              aria-expanded={showInfo}
              aria-label="What does this identity mode mean?"
              className="rounded-full p-0.5 text-gray-500 hover:text-gray-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ae-accent-bright"
            >
              <Info className="h-3.5 w-3.5" />
            </button>
            {showInfo && (
              <div
                role="tooltip"
                className="absolute z-50 top-full mt-2 left-0 w-72 sm:w-96 rounded-lg border border-ae-border bg-ae-card p-3 text-xs text-gray-300 shadow-xl leading-relaxed"
              >
                {description}
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {/* Segmented toggle — active option shows its own connected address
              instead of a generic label, and carries the "connected" style. */}
          <div className="inline-flex rounded-lg border border-ae-border p-0.5 bg-ae-bg/60">
            <button
              type="button"
              onClick={useDemo}
              aria-pressed={mode === 'demo'}
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 font-mono transition-colors ${
                mode === 'demo'
                  ? 'bg-amber-500/15 text-amber-200 border border-amber-500/40'
                  : 'text-gray-400 hover:text-gray-200 border border-transparent'
              }`}
            >
              {demoAddress ? shortKey(demoAddress) : 'Demo signer'}
            </button>
            <button
              type="button"
              onClick={connect}
              disabled={!ready}
              aria-pressed={isLive}
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 font-mono transition-colors disabled:opacity-45 disabled:cursor-not-allowed ${
                isLive
                  ? 'bg-green-500/15 text-green-300 border border-green-500/40'
                  : 'text-gray-400 hover:text-gray-200 border border-transparent'
              }`}
            >
              {liveAddress ? shortKey(liveAddress) : ready ? 'Connect wallet' : 'Loading wallet SDK…'}
            </button>
          </div>
          {isLive && (
            <button
              type="button"
              onClick={disconnect}
              className="inline-flex items-center gap-1 rounded-lg border border-transparent px-2 py-1.5 text-gray-500 hover:text-gray-200"
            >
              <Unplug className="h-3.5 w-3.5" /> Disconnect
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default WalletStatus;
