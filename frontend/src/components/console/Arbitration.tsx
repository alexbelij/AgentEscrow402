import React, { useEffect, useState } from 'react';
import {
  api,
  DEMO_AGENT_SENDER,
  DEMO_AGENT_RECEIVER,
  DisputeEvidence,
  ArbitrationRecommendation,
  ElectArbiterResponse,
  Arbiter,
} from '../../lib/api';
import { randomHex64 } from '../../lib/format';
import { Gavel, Dices, Loader2, CheckCircle, XCircle, UserPlus, Search } from 'lucide-react';
import ConfirmModal from './ConfirmModal';

type Tab = 'analyze' | 'elect' | 'register' | 'lookup';

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'analyze', label: 'AI Dispute Analysis', icon: Gavel },
  { id: 'elect', label: 'VRF Arbiter Election', icon: Dices },
  { id: 'register', label: 'Register Arbiter', icon: UserPlus },
  { id: 'lookup', label: 'Election Lookup', icon: Search },
];

const RECOMMENDATION_COLOR: Record<string, string> = {
  favor_sender: 'text-emerald-400',
  favor_receiver: 'text-sky-400',
  split: 'text-amber-400',
  escalate: 'text-red-400',
};

function makeEvidence(claimant: string, description: string): DisputeEvidence {
  return {
    escrow_id: 'console-demo',
    claimant,
    evidence_type: 'text',
    content_hash: randomHex64(),
    description,
    timestamp: Math.floor(Date.now() / 1000),
  };
}

export default function Arbitration() {
  const [tab, setTab] = useState<Tab>('analyze');

  // --- AI dispute analysis state ---
  const [disputeId, setDisputeId] = useState(() => randomHex64());
  const [senderClaim, setSenderClaim] = useState('Delivered the agreed-upon dataset on time, receiver has not confirmed.');
  const [receiverClaim, setReceiverClaim] = useState('Dataset was incomplete: missing 3 of the 10 promised files.');
  const [escrowAmount, setEscrowAmount] = useState(5000);
  const [analyzing, setAnalyzing] = useState(false);
  const [confirmAnalyzeOpen, setConfirmAnalyzeOpen] = useState(false);
  const [result, setResult] = useState<ArbitrationRecommendation | null>(null);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [history, setHistory] = useState<ArbitrationRecommendation[]>([]);

  // --- VRF election state ---
  const [electDisputeId, setElectDisputeId] = useState(() => randomHex64());
  const [electing, setElecting] = useState(false);
  const [electionResult, setElectionResult] = useState<ElectArbiterResponse | null>(null);
  const [electError, setElectError] = useState<string | null>(null);
  const [arbiters, setArbiters] = useState<Arbiter[]>([]);

  // --- Register arbiter state ---
  const [regAgent, setRegAgent] = useState('');
  const [regLoading, setRegLoading] = useState(false);
  const [regError, setRegError] = useState<string | null>(null);
  const [regSuccess, setRegSuccess] = useState(false);

  // --- Election lookup state ---
  const [lookupId, setLookupId] = useState('');
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [lookupResult, setLookupResult] = useState<ElectArbiterResponse | null>(null);

  const loadHistory = async () => {
    const res = await api.getArbitrationHistory(10);
    if (res.data) setHistory(res.data);
  };
  const loadArbiters = async () => {
    const res = await api.getArbiters();
    if (res.data) setArbiters(res.data);
  };

  useEffect(() => {
    loadHistory();
    loadArbiters();
  }, []);

  const runAnalysis = async () => {
    setAnalyzing(true);
    setAnalyzeError(null);
    setResult(null);
    const res = await api.analyzeDispute({
      dispute_id: disputeId,
      sender_evidence: [makeEvidence(DEMO_AGENT_SENDER, senderClaim)],
      receiver_evidence: [makeEvidence(DEMO_AGENT_RECEIVER, receiverClaim)],
      escrow_amount: escrowAmount,
    });
    setAnalyzing(false);
    if (res.error) {
      setAnalyzeError(res.error);
      return;
    }
    setResult(res.data);
    await loadHistory();
  };

  const requestAnalysisConfirmation = () => {
    setConfirmAnalyzeOpen(true);
  };

  const confirmAndRunAnalysis = () => {
    setConfirmAnalyzeOpen(false);
    // Fire-and-forget: runAnalysis is async but the UI already reflects
    // the analyzing state via its own setAnalyzing calls.
    void runAnalysis();
  };

  const runElection = async () => {
    setElecting(true);
    setElectError(null);
    setElectionResult(null);
    const res = await api.electVrfArbiter({
      dispute_id: electDisputeId,
      sender: DEMO_AGENT_SENDER,
      receiver: DEMO_AGENT_RECEIVER,
      seed_hash: randomHex64(),
    });
    setElecting(false);
    if (res.error) {
      setElectError(res.error);
      return;
    }
    setElectionResult(res.data);
    await loadArbiters();
  };

  const handleRegister = async () => {
    setRegLoading(true); setRegError(null); setRegSuccess(false);
    try {
      const res = await api.registerArbiter({ agent: regAgent || DEMO_AGENT_SENDER });
      if (res.error) setRegError(res.error);
      else { setRegSuccess(true); await loadArbiters(); }
    } catch (e: any) { setRegError(e.message ?? String(e)); }
    finally { setRegLoading(false); }
  };

  const handleLookup = async () => {
    setLookupLoading(true); setLookupError(null); setLookupResult(null);
    try {
      const res = await api.getElectionResult(lookupId);
      if (res.error) setLookupError(res.error);
      else setLookupResult(res.data ?? null);
    } catch (e: any) { setLookupError(e.message ?? String(e)); }
    finally { setLookupLoading(false); }
  };

  return (
    <div className="space-y-6">

      <div className="flex gap-2 border-b border-[#1e1e2e]">
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                active ? 'border-amber-500 text-amber-400' : 'border-transparent text-gray-400 hover:text-gray-200'
              }`}
            >
              <Icon className="w-4 h-4" />
              {t.label}
            </button>
          );
        })}
      </div>

      {tab === 'analyze' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-[#12121c] border border-[#1e1e2e] rounded-lg p-5">
            <h2 className="text-lg font-semibold text-white mb-4">Submit dispute evidence</h2>
            <label className="block text-sm font-medium text-gray-300 mb-1">Dispute ID</label>
            <div className="flex gap-2 mb-3">
              <input
                value={disputeId}
                onChange={(e) => setDisputeId(e.target.value)}
                className="flex-1 p-3 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] font-mono text-sm"
              />
              <button
                onClick={() => setDisputeId(randomHex64())}
                className="px-3 rounded-md bg-gray-800 border border-[#1e1e2e] text-gray-300 hover:text-white"
                title="Generate new dispute ID"
              >
                ↻
              </button>
            </div>

            <label className="block text-sm font-medium text-gray-300 mb-1">Escrow amount (motes)</label>
            <input
              type="number"
              value={escrowAmount}
              onChange={(e) => setEscrowAmount(Number(e.target.value))}
              className="w-full p-3 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] mb-3"
            />

            <label className="block text-sm font-medium text-gray-300 mb-1">Sender's claim</label>
            <textarea
              value={senderClaim}
              onChange={(e) => setSenderClaim(e.target.value)}
              rows={3}
              className="w-full p-3 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] mb-3"
            />

            <label className="block text-sm font-medium text-gray-300 mb-1">Receiver's claim</label>
            <textarea
              value={receiverClaim}
              onChange={(e) => setReceiverClaim(e.target.value)}
              rows={3}
              className="w-full p-3 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] mb-4"
            />

            <button
              onClick={requestAnalysisConfirmation}
              disabled={analyzing}
              className="w-full h-12 inline-flex items-center justify-center gap-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold disabled:opacity-50"
            >
              {analyzing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Gavel className="w-4 h-4" />}
              Run AI arbitration
            </button>
            <ConfirmModal
              open={confirmAnalyzeOpen}
              title="Run AI arbitration?"
              description="This submits both claims to the AI arbitration model and appends a verdict to the server history. Continue?"
              confirmLabel="Run analysis"
              danger={false}
              onConfirm={confirmAndRunAnalysis}
              onCancel={() => setConfirmAnalyzeOpen(false)}
            />
            {analyzeError && <p className="text-red-400 text-sm mt-2">{analyzeError}</p>}
          </div>

          {/* Results rail: the live result of "Run AI arbitration" always
              renders here, on the right, never stacked below the form. */}
          <div className="space-y-6">
            <div className="bg-[#12121c] border border-[#1e1e2e] rounded-lg p-5 xl:sticky xl:top-24">
              <h2 className="text-lg font-semibold text-white mb-4">Result</h2>
              {result ? (
                <div className="p-4 rounded-lg bg-gray-800/60 border border-[#1e1e2e]">
                  <div className="flex items-center justify-between mb-2">
                    <span className={`text-lg font-bold uppercase ${RECOMMENDATION_COLOR[result.recommendation] || 'text-gray-200'}`}>
                      {result.recommendation.replace('_', ' ')}
                    </span>
                    <span className="text-sm text-gray-400">confidence {(result.confidence * 100).toFixed(0)}%</span>
                  </div>
                  <p className="text-sm text-gray-300 mb-2">{result.reasoning}</p>
                  {result.risk_factors.length > 0 && (
                    <ul className="text-xs text-gray-400 list-disc list-inside mb-2">
                      {result.risk_factors.map((f, i) => (
                        <li key={i}>{f}</li>
                      ))}
                    </ul>
                  )}
                  <div className="flex justify-between text-xs text-gray-500 font-mono">
                    <span>suggested split: {result.suggested_split_pct.toFixed(1)}% to sender</span>
                    <span>provider: {result.provider}</span>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-gray-500 italic border border-dashed border-[#2a2a3a] rounded-lg p-4">
                  The recommendation will appear here after you run an analysis.
                </p>
              )}
            </div>

            <div className="bg-[#12121c] border border-[#1e1e2e] rounded-lg p-5">
              <h2 className="text-lg font-semibold text-white mb-4">Recent verdicts (this server instance)</h2>
              {history.length === 0 && <p className="text-gray-500 text-sm">No arbitration analyses run yet.</p>}
              <div className="space-y-2">
                {history.map((h) => (
                  <div key={h.analysis_hash} className="p-3 rounded-md bg-gray-800/40 border border-[#1e1e2e] text-sm">
                    <div className="flex justify-between">
                      <span className={`font-semibold ${RECOMMENDATION_COLOR[h.recommendation] || 'text-gray-200'}`}>
                        {h.recommendation.replace('_', ' ')}
                      </span>
                      <span className="text-gray-500">{(h.confidence * 100).toFixed(0)}%</span>
                    </div>
                    <p className="text-gray-400 text-xs mt-1 font-mono truncate">{h.dispute_id}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === 'elect' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-[#12121c] border border-[#1e1e2e] rounded-lg p-5">
            <h2 className="text-lg font-semibold text-white mb-4">Elect a neutral arbiter</h2>
            <p className="text-sm text-gray-400 mb-3">
              Picks an arbiter from the registered pool below, excluding the escrow's own sender/receiver, weighted by
              reputation score. Tries the on-chain VRF contract first and falls back to a verifiable local CSPRNG if the
              contract call is unavailable.
            </p>
            <label className="block text-sm font-medium text-gray-300 mb-1">Dispute ID</label>
            <div className="flex gap-2 mb-4">
              <input
                value={electDisputeId}
                onChange={(e) => setElectDisputeId(e.target.value)}
                className="flex-1 p-3 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] font-mono text-sm"
              />
              <button
                onClick={() => setElectDisputeId(randomHex64())}
                className="px-3 rounded-md bg-gray-800 border border-[#1e1e2e] text-gray-300 hover:text-white"
                title="Generate new dispute ID"
              >
                ↻
              </button>
            </div>
            <button
              onClick={runElection}
              disabled={electing}
              className="w-full h-12 inline-flex items-center justify-center gap-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold disabled:opacity-50"
            >
              {electing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Dices className="w-4 h-4" />}
              Elect arbiter
            </button>
            {electError && <p className="text-red-400 text-sm mt-2">{electError}</p>}
          </div>

          {/* Results rail: the elected arbiter always renders here, on the
              right, never stacked below the election form. */}
          <div className="space-y-6">
            <div className="bg-[#12121c] border border-[#1e1e2e] rounded-lg p-5 xl:sticky xl:top-24">
              <h2 className="text-lg font-semibold text-white mb-4">Result</h2>
              {electionResult ? (
                <div className="p-4 rounded-lg bg-gray-800/60 border border-[#1e1e2e] text-sm space-y-1">
                  <div className="flex items-center gap-2 text-emerald-400 font-semibold">
                    <CheckCircle className="w-4 h-4" /> Elected: {electionResult.elected_arbiter.arbiter_id}
                  </div>
                  <p className="text-gray-400">reputation score: {electionResult.elected_arbiter.reputation_score}</p>
                  <p className="text-gray-400">method: {electionResult.method}</p>
                  <p className="text-gray-500 text-xs font-mono break-all">proof: {electionResult.election_proof}</p>
                </div>
              ) : (
                <p className="text-sm text-gray-500 italic border border-dashed border-[#2a2a3a] rounded-lg p-4">
                  The elected arbiter will appear here after you run an election.
                </p>
              )}
            </div>

            <div className="bg-[#12121c] border border-[#1e1e2e] rounded-lg p-5">
              <h2 className="text-lg font-semibold text-white mb-4">Registered arbiter pool</h2>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-400 text-left border-b border-[#1e1e2e]">
                    <th className="pb-2">Agent</th>
                    <th className="pb-2">Score</th>
                    <th className="pb-2">Completed</th>
                  </tr>
                </thead>
                <tbody>
                  {arbiters.map((a) => (
                    <tr key={a.public_key} className="border-b border-[#1e1e2e]/50">
                      <td className="py-2 font-mono text-gray-300 truncate max-w-[160px]">{a.public_key}</td>
                      <td className="py-2 text-gray-300">{a.reputation_score.toFixed(1)}</td>
                      <td className="py-2 text-gray-300">{a.active_elections}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {tab === 'register' && (
        <div className="max-w-xl space-y-4">
          <div className="bg-[#151521] border border-[#1e1e2e] rounded-xl p-6 space-y-4">
            <p className="text-sm text-gray-400">
              Register an agent as an arbiter in the on-chain VRF pool. Registered arbiters are eligible for random election when disputes arise.
            </p>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Agent public key (hex, 64 chars)</label>
              <input className="w-full p-3 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] focus:ring-amber-500 focus:border-amber-500 outline-none font-mono text-sm"
                value={regAgent} onChange={(e) => setRegAgent(e.target.value)} placeholder={DEMO_AGENT_SENDER} />
            </div>
            <button onClick={handleRegister} disabled={regLoading}
              className="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg transition-colors flex items-center disabled:opacity-50 w-full justify-center">
              {regLoading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
              Register as arbiter
            </button>
            {regError && <div className="flex items-center gap-2 text-red-400 text-sm"><XCircle className="h-4 w-4 shrink-0" />{regError}</div>}
            {regSuccess && <div className="flex items-center gap-2 text-emerald-400 text-sm"><CheckCircle className="h-4 w-4 shrink-0" />Arbiter registered successfully</div>}
          </div>
        </div>
      )}

      {tab === 'lookup' && (
        <div className="max-w-xl space-y-4">
          <div className="bg-[#151521] border border-[#1e1e2e] rounded-xl p-6 space-y-4">
            <p className="text-sm text-gray-400">
              Look up the result of a past VRF arbiter election by dispute ID.
            </p>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Dispute ID</label>
              <input className="w-full p-3 rounded-md bg-gray-800 text-gray-50 border border-[#1e1e2e] focus:ring-amber-500 focus:border-amber-500 outline-none font-mono text-sm"
                value={lookupId} onChange={(e) => setLookupId(e.target.value)} placeholder={'a'.repeat(64)} />
            </div>
            <button onClick={handleLookup} disabled={lookupLoading || !lookupId}
              className="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg transition-colors flex items-center disabled:opacity-50 w-full justify-center">
              {lookupLoading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
              Look up election
            </button>
            {lookupError && <div className="flex items-center gap-2 text-red-400 text-sm"><XCircle className="h-4 w-4 shrink-0" />{lookupError}</div>}
            {lookupResult && (
              <div className="bg-[#12121c] border border-[#1e1e2e] rounded-lg p-4">
                <pre className="text-xs text-gray-300 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(lookupResult, null, 2)}</pre>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
