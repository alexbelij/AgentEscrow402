import React, { useState } from 'react';
import {
  api,
  DEMO_AGENT_RECEIVER,
  TokenIdentifier,
  MultiAssetEscrowRequest,
  StreamEscrowRequest,
  StreamStatus,
  TransactionHash,
} from '../../lib/api';
import { randomHex64 } from '../../lib/format';
import { Coins, Waves, KeyRound, Loader2, CheckCircle, XCircle, RefreshCw } from 'lucide-react';

type Tab = 'token' | 'stream' | 'swap';

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'token', label: 'Alt-Token Escrow', icon: Coins },
  { id: 'stream', label: 'Streaming Escrow', icon: Waves },
  { id: 'swap', label: 'Atomic Swap (commit-reveal)', icon: KeyRound },
];

function TokenSelect({ value, onChange }: { value: TokenIdentifier; onChange: (t: TokenIdentifier) => void }) {
  return (
    <div className="grid grid-cols-2 gap-3 mb-4">
      <div>
        <label className="block text-sm font-medium text-gray-300 mb-1">Token type</label>
        <select
          value={value.token_type}
          onChange={(e) => onChange({ token_type: e.target.value as TokenIdentifier['token_type'], contract_hash: value.contract_hash })}
          className="w-full p-3 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] focus:ring-amber-500 focus:border-amber-500 outline-none"
        >
          <option value="cspr">CSPR (native)</option>
          <option value="cep18">CEP-18 (fungible token)</option>
          <option value="cep78">CEP-78 (NFT)</option>
        </select>
      </div>
      {value.token_type !== 'cspr' && (
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1">Contract hash (64 hex)</label>
          <input
            value={value.contract_hash || ''}
            onChange={(e) => onChange({ ...value, contract_hash: e.target.value })}
            placeholder={'c'.repeat(64)}
            className="w-full p-3 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] focus:ring-amber-500 focus:border-amber-500 outline-none font-mono text-sm"
          />
        </div>
      )}
    </div>
  );
}

function ResultPanel({ error, result }: { error: string | null; result: unknown }) {
  if (error) {
    return (
      <div className="text-red-500 bg-red-900/20 border border-red-700 rounded-lg p-3 flex items-center mt-4">
        <XCircle className="h-5 w-5 mr-2 shrink-0" />
        <p className="break-all">{error}</p>
      </div>
    );
  }
  if (result) {
    return (
      <div className="text-emerald-300 bg-emerald-900/20 border border-emerald-700 rounded-lg p-3 mt-4">
        <p className="flex items-center mb-2"><CheckCircle className="h-5 w-5 mr-2" /> Success</p>
        <pre className="text-xs font-mono whitespace-pre-wrap break-all">{JSON.stringify(result, null, 2)}</pre>
      </div>
    );
  }
  return null;
}

const AdvancedEscrow: React.FC = () => {
  const [tab, setTab] = useState<Tab>('token');

  // --- Alt-token escrow state ---
  const [tokenReceiver, setTokenReceiver] = useState(DEMO_AGENT_RECEIVER);
  const [tokenAmount, setTokenAmount] = useState('1000000000');
  const [tokenServiceHash, setTokenServiceHash] = useState(randomHex64());
  const [tokenIdentifier, setTokenIdentifier] = useState<TokenIdentifier>({ token_type: 'cspr' });
  const [tokenTtl, setTokenTtl] = useState('300');
  const [tokenLoading, setTokenLoading] = useState(false);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [tokenResult, setTokenResult] = useState<TransactionHash | null>(null);

  // --- Streaming escrow state ---
  const [streamReceiver, setStreamReceiver] = useState(DEMO_AGENT_RECEIVER);
  const [streamAmount, setStreamAmount] = useState('1000000000');
  const [streamServiceHash, setStreamServiceHash] = useState(randomHex64());
  const [streamToken, setStreamToken] = useState<TokenIdentifier>({ token_type: 'cspr' });
  const [streamDurationSeconds, setStreamDurationSeconds] = useState('3600');
  const [streamLoading, setStreamLoading] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [streamResult, setStreamResult] = useState<TransactionHash | null>(null);
  const [streamStatusHash, setStreamStatusHash] = useState('');
  const [streamStatus, setStreamStatus] = useState<StreamStatus | null>(null);
  const [streamStatusLoading, setStreamStatusLoading] = useState(false);
  const [streamStatusError, setStreamStatusError] = useState<string | null>(null);

  // --- Atomic swap (commit-reveal) state ---
  const [swapServiceHash, setSwapServiceHash] = useState('');
  const [swapPreimage, setSwapPreimage] = useState('my-secret-preimage');
  const [swapCommitLoading, setSwapCommitLoading] = useState(false);
  const [swapCommitError, setSwapCommitError] = useState<string | null>(null);
  const [swapCommitResult, setSwapCommitResult] = useState<TransactionHash | null>(null);
  const [swapRevealLoading, setSwapRevealLoading] = useState(false);
  const [swapRevealError, setSwapRevealError] = useState<string | null>(null);
  const [swapRevealResult, setSwapRevealResult] = useState<TransactionHash | null>(null);

  const sha256Hex = async (text: string) => {
    const data = new TextEncoder().encode(text);
    const digest = await crypto.subtle.digest('SHA-256', data);
    return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('');
  };

  const handleCreateTokenEscrow = async () => {
    setTokenLoading(true);
    setTokenError(null);
    setTokenResult(null);
    try {
      const req: MultiAssetEscrowRequest = {
        receiver: tokenReceiver,
        amount: Number(tokenAmount),
        token: tokenIdentifier,
        service_hash: tokenServiceHash,
        ttl: Number(tokenTtl),
      };
      const res = await api.createMultiAssetEscrow(req);
      if (res.error) throw new Error(res.error);
      setTokenResult(res.data || null);
    } catch (err) {
      setTokenError(err instanceof Error ? err.message : 'Failed to create escrow.');
    } finally {
      setTokenLoading(false);
    }
  };

  const handleCreateStreamEscrow = async () => {
    setStreamLoading(true);
    setStreamError(null);
    setStreamResult(null);
    try {
      const now = Math.floor(Date.now() / 1000);
      const req: StreamEscrowRequest = {
        receiver: streamReceiver,
        amount: Number(streamAmount),
        token: streamToken,
        service_hash: streamServiceHash,
        start_time: now,
        end_time: now + Number(streamDurationSeconds),
      };
      const res = await api.createStreamEscrow(req);
      if (res.error) throw new Error(res.error);
      setStreamResult(res.data || null);
      setStreamStatusHash(streamServiceHash);
    } catch (err) {
      setStreamError(err instanceof Error ? err.message : 'Failed to create streaming escrow.');
    } finally {
      setStreamLoading(false);
    }
  };

  const handleFetchStreamStatus = async (hashOverride?: string) => {
    const hash = hashOverride || streamStatusHash;
    if (!hash) return;
    setStreamStatusLoading(true);
    setStreamStatusError(null);
    try {
      const res = await api.getStreamStatus(hash);
      if (res.error) throw new Error(res.error);
      setStreamStatus(res.data || null);
    } catch (err) {
      setStreamStatusError(err instanceof Error ? err.message : 'Failed to fetch stream status.');
    } finally {
      setStreamStatusLoading(false);
    }
  };

  const handleCommit = async () => {
    setSwapCommitLoading(true);
    setSwapCommitError(null);
    setSwapCommitResult(null);
    try {
      const commitHash = await sha256Hex(swapPreimage);
      const res = await api.commitAtomicSwap({ service_hash: swapServiceHash, commit_hash: commitHash });
      if (res.error) throw new Error(res.error);
      setSwapCommitResult(res.data || null);
    } catch (err) {
      setSwapCommitError(err instanceof Error ? err.message : 'Commit failed.');
    } finally {
      setSwapCommitLoading(false);
    }
  };

  const handleReveal = async () => {
    setSwapRevealLoading(true);
    setSwapRevealError(null);
    setSwapRevealResult(null);
    try {
      const res = await api.revealAtomicSwap({ service_hash: swapServiceHash, preimage: swapPreimage });
      if (res.error) throw new Error(res.error);
      setSwapRevealResult(res.data || null);
    } catch (err) {
      setSwapRevealError(err instanceof Error ? err.message : 'Reveal failed.');
    } finally {
      setSwapRevealLoading(false);
    }
  };

  const inputCls = 'w-full p-3 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] focus:ring-amber-500 focus:border-amber-500 outline-none';
  const labelCls = 'block text-sm font-medium text-gray-300 mb-1';
  const btnCls = 'px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg transition-colors flex items-center disabled:opacity-50';

  return (
    <div className="space-y-6">
      <div className="flex gap-2 border-b border-[#1e1e2e] pb-3 overflow-x-auto">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${
              tab === id ? 'bg-amber-600 text-white' : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
            }`}
          >
            <Icon className="h-4 w-4 mr-2" /> {label}
          </button>
        ))}
      </div>

      {tab === 'token' && (
        <div className="bg-[#151521] border border-[#1e1e2e] rounded-xl p-6 max-w-2xl">
          <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3 text-sm text-blue-100 mb-4">
            Escrows a single token per escrow, selectable as native CSPR, a CEP-18 fungible token, or a CEP-78 NFT
            (endpoint is named "multi-asset" but does not combine several assets in one escrow). CEP-18/CEP-78 transfers
            are currently simulated on the backend (no real on-chain call yet) — the response's deploy hash is a
            placeholder, exactly like the rest of this hosted demo console.
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
            <div>
              <label className={labelCls}>Receiver account hash</label>
              <input className={`${inputCls} font-mono text-sm`} value={tokenReceiver} onChange={(e) => setTokenReceiver(e.target.value)} />
            </div>
            <div>
              <label className={labelCls}>Amount (motes / token units)</label>
              <input className={inputCls} type="number" value={tokenAmount} onChange={(e) => setTokenAmount(e.target.value)} />
            </div>
          </div>
          <TokenSelect value={tokenIdentifier} onChange={setTokenIdentifier} />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
            <div>
              <label className={labelCls}>Service hash</label>
              <div className="flex gap-2">
                <input className={`${inputCls} font-mono text-sm`} value={tokenServiceHash} onChange={(e) => setTokenServiceHash(e.target.value)} />
                <button type="button" onClick={() => setTokenServiceHash(randomHex64())} className="px-3 rounded-md bg-gray-800 border border-[#1e1e2e] hover:bg-gray-700">
                  <RefreshCw className="h-4 w-4" />
                </button>
              </div>
            </div>
            <div>
              <label className={labelCls}>TTL (seconds)</label>
              <input className={inputCls} type="number" value={tokenTtl} onChange={(e) => setTokenTtl(e.target.value)} />
            </div>
          </div>
          <button onClick={handleCreateTokenEscrow} disabled={tokenLoading} className={btnCls}>
            {tokenLoading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
            Create escrow
          </button>
          <ResultPanel error={tokenError} result={tokenResult} />
        </div>
      )}

      {tab === 'stream' && (
        <div className="bg-[#151521] border border-[#1e1e2e] rounded-xl p-6 max-w-2xl">
          <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3 text-sm text-blue-100 mb-4">
            Deposits the full amount up front, then releases it to the receiver linearly between a start and end
            timestamp. Streamed/remaining amounts are computed live from elapsed time — read them from the status card
            below. Same simulated-transfer caveat as the alt-token escrow applies to CEP-18/CEP-78 tokens.
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
            <div>
              <label className={labelCls}>Receiver account hash</label>
              <input className={`${inputCls} font-mono text-sm`} value={streamReceiver} onChange={(e) => setStreamReceiver(e.target.value)} />
            </div>
            <div>
              <label className={labelCls}>Total amount</label>
              <input className={inputCls} type="number" value={streamAmount} onChange={(e) => setStreamAmount(e.target.value)} />
            </div>
          </div>
          <TokenSelect value={streamToken} onChange={setStreamToken} />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
            <div>
              <label className={labelCls}>Service hash</label>
              <div className="flex gap-2">
                <input className={`${inputCls} font-mono text-sm`} value={streamServiceHash} onChange={(e) => setStreamServiceHash(e.target.value)} />
                <button type="button" onClick={() => setStreamServiceHash(randomHex64())} className="px-3 rounded-md bg-gray-800 border border-[#1e1e2e] hover:bg-gray-700">
                  <RefreshCw className="h-4 w-4" />
                </button>
              </div>
            </div>
            <div>
              <label className={labelCls}>Duration (seconds, from now)</label>
              <input className={inputCls} type="number" value={streamDurationSeconds} onChange={(e) => setStreamDurationSeconds(e.target.value)} />
            </div>
          </div>
          <button onClick={handleCreateStreamEscrow} disabled={streamLoading} className={btnCls}>
            {streamLoading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
            Create streaming escrow
          </button>
          <ResultPanel error={streamError} result={streamResult} />

          <div className="mt-8 pt-6 border-t border-[#1e1e2e]">
            <h4 className="text-lg font-semibold text-gray-200 mb-3">Check stream status</h4>
            <div className="flex gap-2 mb-3">
              <input
                className={`${inputCls} font-mono text-sm`}
                placeholder="service_hash"
                value={streamStatusHash}
                onChange={(e) => setStreamStatusHash(e.target.value)}
              />
              <button
                onClick={() => handleFetchStreamStatus()}
                disabled={streamStatusLoading || !streamStatusHash}
                className={btnCls}
              >
                {streamStatusLoading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
                Refresh
              </button>
            </div>
            {streamStatusError && <ResultPanel error={streamStatusError} result={null} />}
            {streamStatus && (
              <div className="bg-gray-800 border border-[#1e1e2e] rounded-lg p-4 space-y-2 text-sm text-gray-200">
                <div className="flex justify-between"><span>Status</span><span className="font-mono">{streamStatus.status}</span></div>
                <div className="flex justify-between"><span>Streamed</span><span className="font-mono">{streamStatus.streamed_amount} / {streamStatus.total_amount}</span></div>
                <div className="flex justify-between"><span>Remaining</span><span className="font-mono">{streamStatus.remaining_amount}</span></div>
                <div className="w-full bg-gray-700 rounded-full h-2 mt-2">
                  <div
                    className="bg-amber-500 h-2 rounded-full"
                    style={{ width: `${Math.min(100, (streamStatus.streamed_amount / Math.max(1, streamStatus.total_amount)) * 100)}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {tab === 'swap' && (
        <div className="bg-[#151521] border border-[#1e1e2e] rounded-xl p-6 max-w-2xl">
          <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3 text-sm text-blue-100 mb-4">
            This is a commit-reveal hash-lock on an <span className="font-mono">existing</span> escrow, not a two-party
            asset-for-asset swap: the escrow's sender commits <span className="font-mono">sha256(secret)</span>, then
            the escrow's receiver later reveals the secret to release the escrow. Create the escrow first (Alt-Token
            Escrow tab or Escrows page), then paste its service_hash here.
          </div>
          <div className="mb-4">
            <label className={labelCls}>Service hash of an existing escrow</label>
            <input className={`${inputCls} font-mono text-sm`} value={swapServiceHash} onChange={(e) => setSwapServiceHash(e.target.value)} placeholder={'a'.repeat(64)} />
          </div>
          <div className="mb-4">
            <label className={labelCls}>Secret preimage</label>
            <input className={inputCls} value={swapPreimage} onChange={(e) => setSwapPreimage(e.target.value)} />
          </div>
          <div className="flex gap-3">
            <div className="flex-1">
              <button onClick={handleCommit} disabled={swapCommitLoading || !swapServiceHash} className={`${btnCls} w-full justify-center`}>
                {swapCommitLoading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
                1. Commit (as sender)
              </button>
              <ResultPanel error={swapCommitError} result={swapCommitResult} />
            </div>
            <div className="flex-1">
              <button onClick={handleReveal} disabled={swapRevealLoading || !swapServiceHash} className={`${btnCls} w-full justify-center`}>
                {swapRevealLoading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
                2. Reveal (as receiver)
              </button>
              <ResultPanel error={swapRevealError} result={swapRevealResult} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdvancedEscrow;
