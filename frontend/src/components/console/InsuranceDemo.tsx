import { useMemo, useState } from 'react'
import { Shield, Sparkles, AlertTriangle, Scale } from 'lucide-react'

// Small inline badge — F.1 SourceBadge component will subsume this once
// PR #88 merges; kept local here so this page has no cross-branch dep.
function SourceBadge({ source, note }: { source: string; note?: string }) {
  const color =
    source === 'real'
      ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
      : source === 'sim'
        ? 'bg-blue-500/20 text-blue-300 border-blue-500/40'
        : 'bg-slate-500/20 text-slate-400 border-slate-500/40'
  return (
    <span
      className={`inline-flex items-center gap-1 text-[10px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded border ${color}`}
      title={note}
    >
      {source}
    </span>
  )
}

/**
 * Insurance / Dispute / Reputation showcase (batch E).
 *
 * Three interactive panels stacked as one page:
 *   1. Reputation-priced premium calculator  → POST /pricing/insurance-fee
 *   2. Deterministic dispute rubric preview  → POST /dispute/rubric
 *   3. Advisory narrative surface (rubric.narrative)
 *
 * All numbers are pure functions of the inputs — same request always
 * returns the same fee, same verdict. Judge can compare the returned
 * `narrative` against the deterministic `reasons` array to confirm the
 * text is advisory, not evidence.
 */

// Requests go through the Vercel proxy (/backend/*), matching src/lib/api.ts's
// BASE_URL. VITE_API_URL is never set in production, so this previously
// resolved to '' and hit the SPA's own domain (405 / HTML-not-JSON) instead
// of the real backend.
const API = (import.meta as any).env?.VITE_API_URL ?? '/backend'

type PricingResp = {
  escrow_amount_motes: number
  reputation: number
  fee_motes: number
  base_fee_motes: number
  adjusted_fee_motes: number
  tier: string
  multiplier: number
}

type RubricReason = { signal: string; delta: number; note: string }
type RubricResp = {
  score: number
  label: string
  needs_arbiter_panel: boolean
  reasons: RubricReason[]
  narrative: string
}

function fmtCspr(motes: number): string {
  return (motes / 1e9).toFixed(6) + ' CSPR'
}

function TierChip({ tier }: { tier: string }) {
  const color =
    tier === 'high_risk'
      ? 'bg-red-500/20 text-red-300 border-red-500/40'
      : tier === 'medium_risk'
        ? 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40'
        : tier === 'low_risk'
          ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
          : 'bg-slate-500/20 text-slate-300 border-slate-500/40'
  return (
    <span className={`inline-flex px-2 py-0.5 text-xs rounded border ${color}`}>
      {tier}
    </span>
  )
}

function LabelChip({ label }: { label: string }) {
  const color =
    label === 'claimant'
      ? 'bg-blue-500/20 text-blue-200 border-blue-500/40'
      : label === 'respondent'
        ? 'bg-orange-500/20 text-orange-200 border-orange-500/40'
        : 'bg-slate-500/20 text-slate-300 border-slate-500/40'
  return (
    <span className={`inline-flex px-2 py-0.5 text-xs rounded border ${color}`}>
      {label.toUpperCase()}
    </span>
  )
}

/** ----------------------------- Premium panel ----------------------------- */
function PremiumCalculator() {
  const [amount, setAmount] = useState(1_000_000_000)
  const [rep, setRep] = useState(65)
  const [resp, setResp] = useState<PricingResp | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function quote() {
    setErr(null)
    setLoading(true)
    try {
      const r = await fetch(`${API}/pricing/insurance-fee`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ escrow_amount_motes: amount, reputation: rep }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const j = (await r.json()) as PricingResp
      setResp(j)
    } catch (e: any) {
      setErr(e?.message ?? 'network error')
    } finally {
      setLoading(false)
    }
  }

  const pct = useMemo(() => {
    if (!resp) return null
    return (resp.fee_motes / resp.escrow_amount_motes) * 100
  }, [resp])

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
      <header className="flex items-center gap-2 mb-4">
        <Sparkles className="w-5 h-5 text-emerald-300" />
        <h3 className="font-semibold text-slate-100">Reputation-priced premium</h3>
        <SourceBadge source="fixture" note="pure function of inputs" />
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <label className="block">
          <span className="text-xs text-slate-400">Escrow amount (motes)</span>
          <input
            type="number"
            min={1}
            className="mt-1 w-full rounded bg-slate-950 border border-slate-800 px-3 py-2 text-slate-200"
            value={amount}
            onChange={(e) => setAmount(Number(e.target.value))}
          />
          <span className="text-xs text-slate-500 mt-1 block">
            ≈ {fmtCspr(amount)}
          </span>
        </label>

        <label className="block">
          <span className="text-xs text-slate-400">Agent reputation (0–100)</span>
          <input
            type="range"
            min={0}
            max={100}
            value={rep}
            onChange={(e) => setRep(Number(e.target.value))}
            className="mt-2 w-full"
          />
          <span className="text-xs text-slate-500 mt-1 block">score = {rep}</span>
        </label>
      </div>

      <button
        onClick={quote}
        disabled={loading}
        className="mt-4 px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-sm disabled:opacity-50"
      >
        {loading ? 'Quoting…' : 'Quote premium'}
      </button>
      {err && <div className="mt-3 text-sm text-red-400">✗ {err}</div>}

      {resp && (
        <div className="mt-4 rounded-lg border border-slate-800 bg-slate-950/60 p-4">
          <div className="flex items-center gap-3 mb-2">
            <span className="text-slate-200 font-mono">Fee: {fmtCspr(resp.fee_motes)}</span>
            <TierChip tier={resp.tier} />
            <span className="text-xs text-slate-500">
              multiplier ×{resp.multiplier}
              {pct !== null && ` · ${pct.toFixed(3)}% of escrow`}
            </span>
          </div>
          <div className="text-xs text-slate-500 grid grid-cols-2 gap-x-4 gap-y-1">
            <div>base_fee</div>
            <div className="font-mono text-slate-400 text-right">{fmtCspr(resp.base_fee_motes)}</div>
            <div>adjusted_fee</div>
            <div className="font-mono text-slate-400 text-right">
              {fmtCspr(resp.adjusted_fee_motes)}
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

/** ------------------------------ Rubric panel ----------------------------- */
function DisputeRubricPreview() {
  const [claimRep, setClaimRep] = useState(75)
  const [respRep, setRespRep] = useState(35)
  const [claimEv, setClaimEv] = useState(3)
  const [respEv, setRespEv] = useState(1)
  const [claimPrior, setClaimPrior] = useState(0)
  const [respPrior, setRespPrior] = useState(2)
  const [prov, setProv] = useState(true)
  const [replay, setReplay] = useState(false)
  const [amount] = useState(500_000_000)
  const [resp, setResp] = useState<RubricResp | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function preview() {
    setErr(null)
    setLoading(true)
    try {
      const r = await fetch(`${API}/dispute/rubric`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          escrow_amount_motes: amount,
          time_to_dispute_seconds: 3600,
          claimant_reputation: claimRep,
          respondent_reputation: respRep,
          claimant_evidence_count: claimEv,
          respondent_evidence_count: respEv,
          claimant_prior_disputes: claimPrior,
          respondent_prior_disputes: respPrior,
          evidence_provenance_verified: prov,
          x402_replay_flagged: replay,
        }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const j = (await r.json()) as RubricResp
      setResp(j)
    } catch (e: any) {
      setErr(e?.message ?? 'network error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
      <header className="flex items-center gap-2 mb-4">
        <Scale className="w-5 h-5 text-blue-300" />
        <h3 className="font-semibold text-slate-100">Deterministic dispute rubric</h3>
        <SourceBadge source="fixture" note="binding decision goes to arbiter panel" />
      </header>

      <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
        <label>
          <span className="text-xs text-slate-400">Claimant reputation</span>
          <input
            type="number"
            min={0}
            max={100}
            className="mt-1 w-full rounded bg-slate-950 border border-slate-800 px-2 py-1 text-slate-200"
            value={claimRep}
            onChange={(e) => setClaimRep(Number(e.target.value))}
          />
        </label>
        <label>
          <span className="text-xs text-slate-400">Respondent reputation</span>
          <input
            type="number"
            min={0}
            max={100}
            className="mt-1 w-full rounded bg-slate-950 border border-slate-800 px-2 py-1 text-slate-200"
            value={respRep}
            onChange={(e) => setRespRep(Number(e.target.value))}
          />
        </label>
        <label>
          <span className="text-xs text-slate-400">Claimant evidence</span>
          <input
            type="number"
            min={0}
            className="mt-1 w-full rounded bg-slate-950 border border-slate-800 px-2 py-1 text-slate-200"
            value={claimEv}
            onChange={(e) => setClaimEv(Number(e.target.value))}
          />
        </label>
        <label>
          <span className="text-xs text-slate-400">Respondent evidence</span>
          <input
            type="number"
            min={0}
            className="mt-1 w-full rounded bg-slate-950 border border-slate-800 px-2 py-1 text-slate-200"
            value={respEv}
            onChange={(e) => setRespEv(Number(e.target.value))}
          />
        </label>
        <label>
          <span className="text-xs text-slate-400">Claimant prior disputes</span>
          <input
            type="number"
            min={0}
            className="mt-1 w-full rounded bg-slate-950 border border-slate-800 px-2 py-1 text-slate-200"
            value={claimPrior}
            onChange={(e) => setClaimPrior(Number(e.target.value))}
          />
        </label>
        <label>
          <span className="text-xs text-slate-400">Respondent prior disputes</span>
          <input
            type="number"
            min={0}
            className="mt-1 w-full rounded bg-slate-950 border border-slate-800 px-2 py-1 text-slate-200"
            value={respPrior}
            onChange={(e) => setRespPrior(Number(e.target.value))}
          />
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={prov}
            onChange={(e) => setProv(e.target.checked)}
          />
          <span className="text-slate-300">Provenance verified</span>
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={replay}
            onChange={(e) => setReplay(e.target.checked)}
          />
          <span className="text-slate-300">X402 replay flagged</span>
        </label>
      </div>

      <button
        onClick={preview}
        disabled={loading}
        className="mt-4 px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm disabled:opacity-50"
      >
        {loading ? 'Scoring…' : 'Preview verdict'}
      </button>
      {err && <div className="mt-3 text-sm text-red-400">✗ {err}</div>}

      {resp && (
        <div className="mt-4 rounded-lg border border-slate-800 bg-slate-950/60 p-4">
          <div className="flex items-center gap-3 mb-3">
            <span className="text-slate-200 font-mono">score {resp.score >= 0 ? '+' : ''}{resp.score}</span>
            <LabelChip label={resp.label} />
            {resp.needs_arbiter_panel && (
              <span className="inline-flex items-center gap-1 text-xs text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded px-2 py-0.5">
                <AlertTriangle className="w-3 h-3" /> arbiter panel required
              </span>
            )}
          </div>
          <div className="mb-3">
            <h4 className="text-xs text-slate-400 uppercase tracking-wider mb-1">
              Reasons (deterministic)
            </h4>
            <ul className="text-sm text-slate-300 space-y-1">
              {resp.reasons.map((r, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="font-mono text-slate-500 w-16 text-right">
                    {r.delta >= 0 ? '+' : ''}
                    {r.delta}
                  </span>
                  <span className="font-mono text-slate-400 w-40">{r.signal}</span>
                  <span className="text-slate-400 flex-1">{r.note}</span>
                </li>
              ))}
              {!resp.reasons.length && (
                <li className="text-slate-500 italic">
                  no rubric signals fired — panel required
                </li>
              )}
            </ul>
          </div>
          <div className="border-t border-slate-800 pt-3 text-xs text-slate-500">
            <div className="mb-1">Advisory narrative (not evidence):</div>
            <pre className="whitespace-pre-wrap text-slate-400 text-xs">{resp.narrative}</pre>
          </div>
        </div>
      )}
    </section>
  )
}

export function InsuranceDemo() {
  return (
    <div className="space-y-6">
      <header className="flex items-start gap-3">
        <Shield className="w-6 h-6 text-emerald-300 mt-1" />
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Insurance × Dispute × Reputation</h1>
          <p className="text-sm text-slate-400 mt-1 max-w-2xl">
            Live showcase of the three pricing surfaces judges care about.
            Every fee and score below is a pure function of the inputs —
            no LLM, no randomness, no I/O.
          </p>
        </div>
      </header>

      <div className="rounded-lg border border-slate-800 bg-slate-900/30 p-4 text-sm text-slate-400">
        <p>
          <strong className="text-slate-200">What this page proves.</strong>{' '}
          Reputation prices the premium (E.3). A deterministic rubric previews
          the dispute verdict (E.2) with an ordered list of contributing signals
          — the arbiter panel still holds the binding decision. Same inputs
          always yield the same numbers.
        </p>
      </div>

      <PremiumCalculator />
      <DisputeRubricPreview />
    </div>
  )
}

export default InsuranceDemo
