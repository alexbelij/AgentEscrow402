import React, { useState } from 'react';
import { api, DEMO_AGENT_RECEIVER, DEMO_AGENT_SENDER } from '../../lib/api';
import { csprToMotes, randomHex64 } from '../../lib/format';
import { Cpu, Loader2, Play, RefreshCw, Shield, Shuffle, WalletCards } from 'lucide-react';

const CONTRACTS = [
  {
    name: 'Core Escrow',
    hash: '5d5c7551f9289b4679f798f3a90d7cfce7bfb10d0dd729186b16b48b5a7a1467',
    role: 'Create/release/refund/dispute escrow lifecycle exposed by the API.',
  },
  {
    name: 'Escrow Manager',
    hash: 'bfa8c02cb3ab0f9d7bf03335f324973675200a597162e1e5fa4cb5a77dff675d',
    role: 'Manager/orchestration contract used for deployed demo flows.',
  },
  {
    name: 'Insurance Pool',
    hash: 'e36b958dc3ec27f8af6ad7e81f56c5ff5d06ad1a102e155259b60b6ab9f51f61',
    role: 'Insurance premium/deposit/claim accounting for risky agent work.',
  },
  {
    name: 'VRF Arbiter',
    hash: '5d65bedf67aeb8dc41426787da6a59735206728ce04c668f2a493b7b53392f7f',
    role: 'On-chain random arbiter election target; API falls back to verifiable local CSPRNG when chain query is unavailable.',
  },
];

const short = (value: string) => `${value.slice(0, 12)}…${value.slice(-10)}`;

const Contracts: React.FC = () => {
  const [serviceHash, setServiceHash] = useState(randomHex64());
  const [amountCspr, setAmountCspr] = useState('100');
  const [result, setResult] = useState<any>(null);
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [escrowStatus, setEscrowStatus] = useState<string | null>(null);

  const run = async (label: string, fn: () => Promise<any>) => {
    setLoadingAction(label);
    setError(null);
    setResult(null);
    try {
      const res = await fn();
      if (res.error) throw new Error(res.error);
      setResult({ action: label, response: res.data });
      if (label === 'Create escrow') {
        if (res.data?.service_hash) setServiceHash(res.data.service_hash);
        setEscrowStatus(res.data?.status || 'pending');
      }
      if (label === 'Release') setEscrowStatus('released');
      if (label === 'Refund') setEscrowStatus('refunded');
      if (label === 'Dispute') setEscrowStatus('disputed');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingAction(null);
    }
  };

  const amountMotes = csprToMotes(Number(amountCspr || '0'));
  const terminalStatus = escrowStatus === 'released' || escrowStatus === 'refunded' || escrowStatus === 'disputed';
  const canMutate = !!escrowStatus && !terminalStatus;

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-3xl font-bold text-gray-50">Contracts & Playground</h2>
        <p className="text-gray-400 mt-2">Live Casper testnet contract hashes plus API-backed tools for escrow, VRF and service hash generation.</p>
      </div>

      <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-4 text-sm text-amber-100">
        This playground calls the deployed backend against the current testnet contract configuration. Write calls include the demo x402 identity header from the frontend;
        production calls should use wallet/agent-signed payment headers. Results below are raw live API responses, not screenshots or mock cards.
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {CONTRACTS.map((contract) => (
          <div key={contract.hash} className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-lg font-semibold text-gray-50">{contract.name}</p>
                <p className="text-sm text-gray-400 mt-1">{contract.role}</p>
              </div>
              <Cpu className="h-6 w-6 text-amber-500 shrink-0" />
            </div>
            <p className="font-mono text-sm text-gray-300 mt-4 break-all">{contract.hash}</p>
            <a
              href={`https://testnet.cspr.live/search/${contract.hash}`}
              target="_blank"
              rel="noreferrer"
              className="inline-block mt-3 text-sm text-amber-400 hover:text-amber-300"
            >
              Search on CSPR.live →
            </a>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 items-start">
        <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 space-y-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-xl font-semibold text-gray-50">Escrow playground settings</h3>
              <p className="text-sm text-gray-400 mt-1">Create a fresh escrow first. Terminal states disable invalid actions so the console does not ask the API to dispute/refund a released escrow.</p>
            </div>
            <button
              onClick={() => { setServiceHash(randomHex64()); setResult(null); setError(null); setEscrowStatus(null); }}
              className="inline-flex items-center px-3 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-200 text-sm"
            >
              <RefreshCw className="h-4 w-4 mr-2" /> Fresh escrow
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label className="space-y-2">
              <span className="text-sm text-gray-400">Receiver</span>
              <textarea value={DEMO_AGENT_RECEIVER} readOnly className="w-full h-24 p-3 bg-[#0d0d14] border border-[#1e1e2e] rounded-lg text-gray-300 font-mono text-xs" />
            </label>
            <label className="space-y-2">
              <span className="text-sm text-gray-400">Amount (CSPR)</span>
              <input value={amountCspr} onChange={(e) => setAmountCspr(e.target.value)} className="w-full h-12 px-3 bg-[#0d0d14] border border-[#1e1e2e] rounded-lg text-gray-100 focus:ring-2 focus:ring-amber-500 outline-none" />
              <span className="text-xs text-gray-500">Converted to {amountMotes.toLocaleString()} motes.</span>
            </label>
          </div>

          <label className="space-y-2 block">
            <span className="text-sm text-gray-400">Service hash (escrow ID)</span>
            <input value={serviceHash} onChange={(e) => { setServiceHash(e.target.value); setEscrowStatus(null); }} className="w-full h-12 px-3 bg-[#0d0d14] border border-[#1e1e2e] rounded-lg text-gray-100 font-mono text-sm focus:ring-2 focus:ring-amber-500 outline-none" />
          </label>

          <div className="rounded-lg border border-[#1e1e2e] bg-[#0d0d14] p-3 text-sm text-gray-300">
            Current playground state: <span className="font-mono text-amber-300">{escrowStatus || 'fresh hash — create escrow first'}</span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <PlayButton label="Create escrow" icon={WalletCards} loading={loadingAction} onClick={() => run('Create escrow', () => api.createEscrow({ receiver: DEMO_AGENT_RECEIVER, amount: amountMotes, service_hash: serviceHash, ttl: 300 }))} />
            <PlayButton label="Release" icon={Play} loading={loadingAction} disabled={!canMutate} onClick={() => run('Release', () => api.releaseEscrow({ service_hash: serviceHash }))} />
            <PlayButton label="Refund" icon={RefreshCw} loading={loadingAction} disabled={!canMutate} onClick={() => run('Refund', () => api.refundEscrow({ service_hash: serviceHash }))} />
            <PlayButton label="Dispute" icon={Shield} loading={loadingAction} disabled={!canMutate} onClick={() => run('Dispute', () => api.disputeEscrow({ service_hash: serviceHash, reason_hash: randomHex64() }))} />
          </div>

          {!canMutate && escrowStatus && (
            <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-3 text-sm text-amber-100">
              This escrow is already <span className="font-mono">{escrowStatus}</span>. Use “Fresh escrow” to start another lifecycle instead of sending an invalid action.
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2">
            <button onClick={() => run('Compute service hash', () => api.computeServiceHash({ sender: DEMO_AGENT_SENDER, receiver: DEMO_AGENT_RECEIVER, amount: amountMotes, nonce: serviceHash.slice(0, 12) }))} disabled={!!loadingAction} className="h-12 inline-flex items-center justify-center rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-100 disabled:opacity-50">
              {loadingAction === 'Compute service hash' ? <Loader2 className="h-5 w-5 mr-2 animate-spin" /> : <Cpu className="h-5 w-5 mr-2" />} Compute hash
            </button>
            <button onClick={() => run('VRF election', () => api.electVrfArbiter({ dispute_id: `contract-console-${Date.now()}`, sender: DEMO_AGENT_SENDER, receiver: DEMO_AGENT_RECEIVER, seed_hash: randomHex64() }))} disabled={!!loadingAction} className="h-12 inline-flex items-center justify-center rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold disabled:opacity-50">
              {loadingAction === 'VRF election' ? <Loader2 className="h-5 w-5 mr-2 animate-spin" /> : <Shuffle className="h-5 w-5 mr-2" />} Run VRF election
            </button>
          </div>
        </div>

        <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 space-y-4 xl:sticky xl:top-32">
          <h3 className="text-xl font-semibold text-gray-50">Playground result</h3>
          <p className="text-sm text-gray-400">Responses stay beside the controls, so you do not need to scroll down and back up after every action.</p>
          {loadingAction && <div className="flex items-center text-amber-300"><Loader2 className="h-5 w-5 mr-2 animate-spin" /> Running {loadingAction}…</div>}
          {error ? (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-200">{error}</div>
          ) : result ? (
            <pre className="bg-[#0d0d14] border border-[#1e1e2e] rounded-lg p-4 text-sm text-gray-300 overflow-x-auto max-h-[560px]">{JSON.stringify(result, null, 2)}</pre>
          ) : (
            <div className="bg-[#0d0d14] border border-[#1e1e2e] rounded-lg p-4 text-gray-500 text-sm">Run an action to see the live API response here.</div>
          )}
          <div className="text-xs text-gray-500">VRF reports <span className="font-mono">onchain_vrf</span> when chain data is available, otherwise <span className="font-mono">local_csprng</span> with proof.</div>
        </div>
      </div>


    </div>
  );
};

const PlayButton: React.FC<{ label: string; icon: React.ElementType; loading: string | null; onClick: () => void; disabled?: boolean }> = ({ label, icon: Icon, loading, onClick, disabled }) => (
  <button
    onClick={onClick}
    disabled={!!loading || disabled}
    className="h-12 inline-flex items-center justify-center rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-100 font-semibold disabled:opacity-50"
  >
    {loading === label ? <Loader2 className="h-5 w-5 mr-2 animate-spin" /> : <Icon className="h-5 w-5 mr-2" />}
    {label}
  </button>
);

export default Contracts;
