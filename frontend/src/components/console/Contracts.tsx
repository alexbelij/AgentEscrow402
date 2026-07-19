import React, { useEffect, useState } from 'react';
import { api, DEMO_AGENT_RECEIVER, DEMO_AGENT_SENDER } from '../../lib/api';
import { csprToMotes, randomHex64 } from '../../lib/format';
import { Cpu, Loader2, Play, RefreshCw, Shield, Shuffle, WalletCards, BadgeCheck, Coins, Layers, Dices } from 'lucide-react';
import CopyButton from './CopyButton';

// Fallback only — used if the backend /contracts call fails (e.g. offline
// dev build). The source of truth is the backend Config (env-overridable),
// so a contract redeploy no longer requires a frontend code change.
const CATEGORY_ICONS: Record<string, React.ElementType> = {
  core: Shield,
  identity: BadgeCheck,
  'multi-asset': Layers,
  token: Coins,
};

const FALLBACK_CONTRACTS = [
  {
    name: 'Core Escrow',
    hash: '612cead2226329fafec492042fd96a999df06d1e88c476913a167f44d3ddd9ec',
    role: 'Full escrow lifecycle: create → release / refund / dispute → 3-of-5 arbiter resolve, with release-cap guard and emergency freeze.',
    category: 'core',
  },
  {
    name: 'Escrow Manager',
    hash: 'bfa8c02cb3ab0f9d7bf03335f324973675200a597162e1e5fa4cb5a77dff675d',
    role: 'Batch escrow orchestration: create, release and cancel multiple escrows in a single deploy.',
    category: 'core',
  },
  {
    name: 'Insurance Pool',
    hash: 'ead90738d19ad7fcc88c9e079e12d8cf6d4fd09ddd3daafe565bf4fe4b95fff4',
    role: 'Collects insurance premiums on escrow creation, manages claim payouts for disputed escrows.',
    category: 'core',
  },
  {
    name: 'VRF Arbiter',
    hash: '78ae28702deeb2eadec573d95b870f68b928a82a3566e292ff33a9ae2c779c93',
    role: 'On-chain verifiable random arbiter election with staked purses; API falls back to local CSPRNG when unavailable.',
    category: 'core',
  },
  {
    name: 'Agent Identity Registry',
    hash: '1f29271d986818254d42e5551dd8fbb2e2b7f7295bdfcd6558639584ad311cae',
    role: 'DID-style agent registration with on-chain staking, reputation tracking and capability delegation.',
    category: 'identity',
  },
  {
    name: 'MultiAssetEscrow',
    hash: '52db09a146158ba2a07b5da07587046985ce8ca3be094fca9ad63cb6b9ecd12a',
    role: 'Contract-custody escrow for CEP-18 fungible tokens: approve → create → release/refund/dispute/resolve, all on-chain.',
    category: 'multi-asset',
  },
  {
    name: 'AEMAT (test token)',
    hash: '8ba7df6fd9a12c71de903a915717537eeff4f04adf33f4ed8abf16c254e300a5',
    role: 'CEP-18 fungible test token for multi-asset escrow demos (custody-compatible, uses get_immediate_caller).',
    category: 'token',
  },
  {
    name: 'AETNFT (test NFT)',
    hash: 'c2dee0f1f40c3dae3f3106f70d69b8768d7426758b43040673f68e271f2bf70a',
    role: 'CEP-78 enhanced NFT collection for multi-asset escrow NFT demos (Transferable, Public minting, Ordinal IDs).',
    category: 'token',
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
  const [contractsList, setContractsList] = useState<{ name: string; hash: string; role: string; category?: string }[]>(FALLBACK_CONTRACTS);

  useEffect(() => {
    api.getContracts().then((res) => {
      if (res.data && res.data.length > 0) setContractsList(res.data);
    }).catch(() => {
      // Keep fallback list — backend unreachable
    });
  }, []);

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
      <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-4 text-sm text-amber-100">
        This playground calls the deployed backend against the current testnet contract configuration. Write calls include the demo x402 identity header from the frontend;
        production calls should use wallet/agent-signed payment headers. Results below are raw live API responses, not screenshots or mock cards.
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {contractsList.map((contract) => (
          <div key={contract.hash} className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-lg font-semibold text-gray-50">{contract.name}</p>
                <p className="text-sm text-gray-400 mt-1">{contract.role}</p>
              </div>
              {(() => { const Icon = CATEGORY_ICONS[contract.category || ''] || Cpu; return <Icon className="h-6 w-6 text-amber-500 shrink-0" />; })()}
            </div>
            <div className="flex items-start gap-2 mt-4">
              <p className="font-mono text-sm text-gray-300 break-all">{contract.hash}</p>
              <CopyButton text={contract.hash} className="shrink-0 mt-0.5" />
            </div>
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
          <div>
            <h3 className="text-xl font-semibold text-gray-50">Escrow playground settings</h3>
            <p className="text-sm text-gray-400 mt-1">Create a fresh escrow first. Terminal states disable invalid actions so the console does not ask the API to dispute/refund a released escrow.</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <label className="space-y-2 md:col-span-2">
              <span className="text-sm text-gray-400">Receiver</span>
              <textarea value={DEMO_AGENT_RECEIVER} readOnly className="w-full h-24 p-3 bg-[#0d0d14] border border-[#1e1e2e] rounded-lg text-gray-300 font-mono text-xs" />
            </label>
            <label className="space-y-2">
              <span className="text-sm text-gray-400">Amount (CSPR)</span>
              <input value={amountCspr} onChange={(e) => setAmountCspr(e.target.value)} className="w-full h-12 px-3 bg-[#0d0d14] border border-[#1e1e2e] rounded-lg text-gray-100 focus:ring-2 focus:ring-amber-500 outline-none" />
              <span className="text-xs text-gray-500">Converted to {amountMotes.toLocaleString()} motes.</span>
            </label>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-gray-400">Service hash (escrow ID)</span>
              <button
                onClick={() => { setServiceHash(randomHex64()); setResult(null); setError(null); setEscrowStatus(null); }}
                className="inline-flex items-center px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-200 text-xs shrink-0"
                title="Generate a new random service hash for a fresh escrow"
              >
                <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Fresh escrow
              </button>
            </div>
            <input value={serviceHash} onChange={(e) => { setServiceHash(e.target.value); setEscrowStatus(null); }} className="w-full h-12 px-3 bg-[#0d0d14] border border-[#1e1e2e] rounded-lg text-gray-100 font-mono text-sm focus:ring-2 focus:ring-amber-500 outline-none" />
          </div>

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
