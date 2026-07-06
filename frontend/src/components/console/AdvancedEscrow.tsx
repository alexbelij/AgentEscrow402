import React, { useState } from 'react';
import {
  api,
  DEMO_AGENT_RECEIVER,
  TEST_CEP18_CONTRACT_HASH,
  TokenIdentifier,
  MultiAssetEscrowRequest,
  StreamEscrowRequest,
  StreamStatus,
  TransactionHash,
} from '../../lib/api';
import { randomHex64 } from '../../lib/format';
import { Coins, Waves, KeyRound, Loader2, CheckCircle, XCircle, RefreshCw } from 'lucide-react';
import { useSigner } from '../../lib/signer';
import { useCep18PermitDeposit } from '../../lib/useCep18PermitDeposit';

type Tab = 'token' | 'stream' | 'swap';

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'token', label: 'Alt-Token Escrow', icon: Coins },
  { id: 'stream', label: 'Streaming Escrow', icon: Waves },
  { id: 'swap', label: 'Atomic Swap (commit-reveal)', icon: KeyRound },
];

function TokenSelect({ value, onChange }: { value: TokenIdentifier; onChange: (t: TokenIdentifier) => void }) {
  return (
    <div className="space-y-3 mb-4">
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
          <div className="flex items-center justify-between gap-2 mb-1">
            <label className="block text-sm font-medium text-gray-300">Contract hash (64 hex)</label>
            {value.token_type === 'cep18' && (
              <button
                type="button"
                onClick={() => onChange({ ...value, contract_hash: TEST_CEP18_CONTRACT_HASH })}
                title="Fill in this project's own AETUSD test token, deployed on casper-test"
                className="shrink-0 px-2.5 py-1 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-md text-xs whitespace-nowrap"
              >
                Use test AETUSD
              </button>
            )}
          </div>
          <input
            value={value.contract_hash || ''}
            onChange={(e) => onChange({ ...value, contract_hash: e.target.value })}
            placeholder={'c'.repeat(64)}
            className="w-full p-3 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] focus:ring-amber-500 focus:border-amber-500 outline-none font-mono text-sm"
          />
          {value.token_type === 'cep18' && (
            <p className="text-xs text-gray-500 mt-1">
              No CEP-18 token of your own on testnet? Click "Use test AETUSD" to use this project's
              own test token (contract hash <code>{TEST_CEP18_CONTRACT_HASH.slice(0, 10)}...</code>).
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function ResultPanel({ error, result, placeholder }: { error: string | null; result: unknown; placeholder?: string }) {
  if (error) {
    return (
      <div className="text-red-500 bg-red-900/20 border border-red-700 rounded-lg p-3 flex items-center">
        <XCircle className="h-5 w-5 mr-2 shrink-0" />
        <p className="break-all">{error}</p>
      </div>
    );
  }
  if (result) {
    return (
      <div className="text-emerald-300 bg-emerald-900/20 border border-emerald-700 rounded-lg p-3">
        <p className="flex items-center mb-2"><CheckCircle className="h-5 w-5 mr-2" /> Success</p>
        <pre className="text-xs font-mono whitespace-pre-wrap break-all">{JSON.stringify(result, null, 2)}</pre>
      </div>
    );
  }
  return (
    <div className="text-sm text-gray-500 border border-dashed border-[#2a2a3a] rounded-lg p-4 italic">
      {placeholder || 'The response for this action will appear here.'}
    </div>
  );
}

/** Right-hand results rail: keeps every action's response visually anchored to
 * the same side of the panel instead of stacking under the form, so long forms
 * don't push the result out of view. */
function ResultRail({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-[#151521] border border-[#1e1e2e] rounded-xl p-6 xl:sticky xl:top-24 h-fit space-y-4">
      <h4 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">{title}</h4>
      {children}
    </div>
  );
}

const AdvancedEscrow: React.FC = () => {
  const [tab, setTab] = useState<Tab>('token');

  // --- Alt-token escrow state ---
  const [tokenReceiver, setTokenReceiver] = useState(DEMO_AGENT_RECEIVER);
  const [tokenAmount, setTokenAmount] = useState('1000000000');
  const [tokenServiceHash, setTokenServiceHash] = useState(randomHex64());
  const [tokenIdentifier, setTokenIdentifier] = useState<TokenIdentifier>({ token_type: 'cspr' });
  const [tokenTtl, setTokenTtl] = useState('3600');
  const [tokenLoading, setTokenLoading] = useState(false);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [tokenResult, setTokenResult] = useState<TransactionHash | null>(null);
  const { isLive, activePublicKey } = useSigner();
  const { run: runPermitDeposit } = useCep18PermitDeposit();
  // Casper's algorithm tag is the public key's own first hex byte:
  // 01 = ed25519, 02 = secp256k1. The gasless permit path also signs a
  // genuine x402 payment header (see cep18Permit.ts), and the backend's
  // x402 verifier only supports Ed25519 today -- secp256k1 wallets (e.g.
  // most default Casper Wallet/Ledger accounts) can't use this path yet.
  const isEd25519Wallet = !!activePublicKey && activePublicKey.slice(0, 2).toLowerCase() === '01';
  // Live-wallet CEP-18 escrows default to the real gasless-permit path
  // (funds move from the connected wallet's own balance) when possible;
  // users can opt back into the demo custodial path if they don't have
  // real AETUSD, and secp256k1 wallets fall back to it automatically.
  const [useGaslessPermit, setUseGaslessPermit] = useState(true);

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
      if (isLive && tokenIdentifier.token_type === 'cep18' && useGaslessPermit && isEd25519Wallet) {
        // Real live-wallet path: the connected wallet only signs an
        // off-chain permit message (no tx, no gas) -- the backend relayer
        // submits permit()+transfer_from() on-chain, moving funds out of
        // the wallet's own real balance. See useCep18PermitDeposit.
        const result = await runPermitDeposit(req);
        if (!result.ok) {
          if (result.cancelled) {
            setTokenError('Cancelled in wallet.');
            return;
          }
          throw new Error(result.error);
        }
        setTokenResult(result.result);
        return;
      }
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
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 items-start">
          <div className="bg-[#151521] border border-[#1e1e2e] rounded-xl p-6">
            <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3 text-sm text-blue-100 mb-4">
              Escrows a single token per escrow, selectable as native CSPR, a CEP-18 fungible token, or a CEP-78 NFT
              (endpoint is named "multi-asset" but does not combine several assets in one escrow). CEP-18 and CEP-78
              transfers are both real on-chain calls against deployed testnet token/NFT contracts.
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
            {isLive && tokenIdentifier.token_type === 'cep18' && (
              isEd25519Wallet ? (
                <label className="flex items-start gap-2 mb-4 text-sm text-gray-300 bg-emerald-500/10 border border-emerald-500/30 rounded-md p-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={useGaslessPermit}
                    onChange={(e) => setUseGaslessPermit(e.target.checked)}
                    className="mt-1"
                  />
                  <span>
                    <strong className="text-emerald-300">Gasless wallet permit</strong> — sign an off-chain message only
                    (no transaction, no gas); funds move from your own connected wallet's real CEP-18 balance via a
                    relayer-submitted <code>permit()</code>+<code>transfer_from()</code>. Uncheck to use the demo
                    custodial balance instead.
                  </span>
                </label>
              ) : (
                <div className="flex items-start gap-2 mb-4 text-sm text-gray-400 bg-gray-800/60 border border-[#1e1e2e] rounded-md p-3">
                  <span>
                    <strong className="text-gray-300">Gasless wallet permit unavailable</strong> for this wallet —
                    it uses a secp256k1 key, and the gasless path currently signs an Ed25519-only payment header.
                    Falling back to the demo custodial balance for this CEP-18 escrow.
                  </span>
                </div>
              )
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
              <div>
                <label className={labelCls}>Service hash</label>
                <div className="flex gap-2">
                  <input className={`${inputCls} font-mono text-sm`} value={tokenServiceHash} onChange={(e) => setTokenServiceHash(e.target.value)} />
                  <button type="button" onClick={() => setTokenServiceHash(randomHex64())} aria-label="Generate new service hash" title="Generate new service hash" className="px-3 rounded-md bg-gray-800 border border-[#1e1e2e] hover:bg-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ae-accent-bright">
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
          </div>
          <ResultRail title="Result">
            <ResultPanel error={tokenError} result={tokenResult} />
          </ResultRail>
        </div>
      )}

      {tab === 'stream' && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 items-start">
          <div className="bg-[#151521] border border-[#1e1e2e] rounded-xl p-6">
            <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3 text-sm text-blue-100 mb-4">
              Deposits the full amount up front, then releases it to the receiver linearly between a start and end
              timestamp. Streamed/remaining amounts are computed live from elapsed time — read them from the status
              card on the right. Same as the alt-token escrow: CEP-18 and CEP-78 transfers are both real on-chain calls.
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
                  <button type="button" onClick={() => setStreamServiceHash(randomHex64())} aria-label="Generate new service hash" title="Generate new service hash" className="px-3 rounded-md bg-gray-800 border border-[#1e1e2e] hover:bg-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ae-accent-bright">
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

            <div className="mt-8 pt-6 border-t border-[#1e1e2e]">
              <h4 className="text-lg font-semibold text-gray-200 mb-3">Check stream status</h4>
              <div className="flex gap-2">
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
            </div>
          </div>
          <ResultRail title="Result">
            <ResultPanel error={streamError} result={streamResult} />
            <div className="pt-4 border-t border-[#1e1e2e]">
              <h5 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Stream status</h5>
              {streamStatusError && <ResultPanel error={streamStatusError} result={null} />}
              {!streamStatusError && streamStatus && (
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
              {!streamStatusError && !streamStatus && (
                <p className="text-sm text-gray-500 italic">No status fetched yet.</p>
              )}
            </div>
          </ResultRail>
        </div>
      )}

      {tab === 'swap' && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 items-start">
          <div className="bg-[#151521] border border-[#1e1e2e] rounded-xl p-6">
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
              <button onClick={handleCommit} disabled={swapCommitLoading || !swapServiceHash} className={`${btnCls} flex-1 justify-center`}>
                {swapCommitLoading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
                1. Commit (as sender)
              </button>
              <button onClick={handleReveal} disabled={swapRevealLoading || !swapServiceHash} className={`${btnCls} flex-1 justify-center`}>
                {swapRevealLoading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
                2. Reveal (as receiver)
              </button>
            </div>
          </div>
          <ResultRail title="Result">
            <div>
              <h5 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">1. Commit</h5>
              <ResultPanel error={swapCommitError} result={swapCommitResult} />
            </div>
            <div className="pt-4 border-t border-[#1e1e2e]">
              <h5 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">2. Reveal</h5>
              <ResultPanel error={swapRevealError} result={swapRevealResult} />
            </div>
          </ResultRail>
        </div>
      )}
    </div>
  );
};

export default AdvancedEscrow;
