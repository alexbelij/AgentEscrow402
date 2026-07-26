import { useCallback, useMemo, useState } from 'react'
import { Activity, AlertTriangle, CheckCircle2 } from 'lucide-react'

/**
 * Regime-shift widget (H.1) — live view of the CUSUM chart running
 * against a chosen escrow-flow signal. All math happens server-side in
 * `server/regime_shift.py`; the widget is a thin visual over the
 * `/risk/regime-shift/cusum` endpoint.
 *
 * The judge can paste a comma/whitespace-separated series into the
 * textarea, adjust the k/h controls, and immediately see whether the
 * stream has shifted mean, with a synthetic S_hi/S_lo bar trace.
 */

const API = (import.meta as any).env?.VITE_API_URL ?? ''

type CusumResp = {
  alarm?: boolean
  direction?: string
  first_alarm_index?: number | null
  s_hi?: number[]
  s_lo?: number[]
  // The existing endpoint has multiple response shapes across versions
  // — we accept anything with a truthy `alarm` boolean and derive the
  // rest.
  [k: string]: any
}

function parseSeries(text: string): number[] {
  return text
    .split(/[\s,;]+/)
    .map((t) => t.trim())
    .filter((t) => t.length > 0)
    .map((t) => Number(t))
    .filter((n) => Number.isFinite(n))
}

export function RegimeShiftWidget() {
  const [text, setText] = useState(
    '0.1 -0.2 0.1 -0.1 0.2 -0.1 0.1 0.2 1.4 1.6 1.8 2.0 2.1 2.3 2.2 2.4',
  )
  const [mu, setMu] = useState(0)
  const [sigma, setSigma] = useState(1)
  const [k, setK] = useState(0.5)
  const [h, setH] = useState(3)
  const [resp, setResp] = useState<CusumResp | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const samples = useMemo(() => parseSeries(text), [text])

  const analyse = useCallback(async () => {
    setErr(null)
    setLoading(true)
    try {
      const r = await fetch(`${API}/risk/regime-shift/cusum`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          values: samples,
          mu0: mu,
          sigma,
          cusum_k: k,
          cusum_h: h,
        }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const j = (await r.json()) as CusumResp
      setResp(j)
    } catch (e: any) {
      setErr(e?.message ?? 'network error')
    } finally {
      setLoading(false)
    }
  }, [samples, mu, sigma, k, h])

  // The endpoint returns { n_samples, first_alarm_idx, first_alarm_direction,
  // results: [{s_upper, s_lower, alarm_upper, alarm_lower, direction}] }.
  const alarm =
    resp?.first_alarm_idx != null || Boolean((resp as any)?.alarm)
  const results = ((resp as any)?.results ?? []) as Array<{
    s_pos?: number
    s_neg?: number
    s_upper?: number
    s_lower?: number
  }>
  const trace = results.map((r) => r.s_pos ?? r.s_upper ?? 0)
  const traceLo = results.map((r) => r.s_neg ?? r.s_lower ?? 0)
  const firstAlarmIdx =
    (resp as any)?.first_alarm_idx ?? resp?.first_alarm_index ?? null
  const direction =
    (resp as any)?.first_alarm_direction ?? resp?.direction ?? 'shift'
  const maxAbs = Math.max(
    1,
    ...trace.map((v) => Math.abs(v)),
    ...traceLo.map((v) => Math.abs(v)),
  )

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
      <header className="flex items-center gap-2 mb-4">
        <Activity className="w-5 h-5 text-fuchsia-300" />
        <h3 className="font-semibold text-slate-100">
          Regime-shift detector (CUSUM)
        </h3>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-sm">
        <label>
          <span className="text-xs text-slate-400">μ (target mean)</span>
          <input
            type="number"
            step="0.1"
            className="mt-1 w-full rounded bg-slate-950 border border-slate-800 px-2 py-1 text-slate-200"
            value={mu}
            onChange={(e) => setMu(Number(e.target.value))}
          />
        </label>
        <label>
          <span className="text-xs text-slate-400">σ (std-dev)</span>
          <input
            type="number"
            step="0.1"
            className="mt-1 w-full rounded bg-slate-950 border border-slate-800 px-2 py-1 text-slate-200"
            value={sigma}
            onChange={(e) => setSigma(Number(e.target.value))}
          />
        </label>
        <label>
          <span className="text-xs text-slate-400">k (slack)</span>
          <input
            type="number"
            step="0.1"
            className="mt-1 w-full rounded bg-slate-950 border border-slate-800 px-2 py-1 text-slate-200"
            value={k}
            onChange={(e) => setK(Number(e.target.value))}
          />
        </label>
        <label>
          <span className="text-xs text-slate-400">h (threshold)</span>
          <input
            type="number"
            step="0.1"
            className="mt-1 w-full rounded bg-slate-950 border border-slate-800 px-2 py-1 text-slate-200"
            value={h}
            onChange={(e) => setH(Number(e.target.value))}
          />
        </label>
      </div>

      <label className="block mt-4">
        <span className="text-xs text-slate-400">Sample stream (whitespace or comma separated)</span>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={2}
          className="mt-1 w-full font-mono text-xs rounded bg-slate-950 border border-slate-800 px-3 py-2 text-slate-200"
        />
        <span className="text-xs text-slate-500 mt-1 block">
          {samples.length} samples parsed
        </span>
      </label>

      <button
        onClick={analyse}
        disabled={loading || samples.length === 0}
        className="mt-3 px-4 py-2 rounded bg-fuchsia-600 hover:bg-fuchsia-500 text-white text-sm disabled:opacity-50"
      >
        {loading ? 'Detecting…' : 'Run CUSUM'}
      </button>
      {err && <div className="mt-2 text-sm text-red-400">✗ {err}</div>}

      {resp && (
        <div className="mt-4 rounded-lg border border-slate-800 bg-slate-950/60 p-4">
          <div className="flex items-center gap-3 mb-3">
            {alarm ? (
              <span className="inline-flex items-center gap-1 text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded px-2 py-1">
                <AlertTriangle className="w-4 h-4" /> ALARM · {direction}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-sm text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded px-2 py-1">
                <CheckCircle2 className="w-4 h-4" /> in control
              </span>
            )}
            {firstAlarmIdx != null && (
              <span className="text-xs text-slate-500">
                first crossing @ index {firstAlarmIdx}
              </span>
            )}
          </div>

          {trace.length > 0 && (
            <div>
              <div className="text-xs text-slate-400 uppercase tracking-wider mb-1">
                S_hi trace (positive-shift accumulator)
              </div>
              <div className="flex items-end gap-[1px] h-16 bg-slate-950/40 border border-slate-800 rounded px-1 py-1">
                {trace.map((v, i) => (
                  <div
                    key={i}
                    className="flex-1 bg-fuchsia-500/60"
                    style={{ height: `${(Math.abs(v) / maxAbs) * 100}%` }}
                    title={`S_hi[${i}] = ${v.toFixed(3)}`}
                  />
                ))}
              </div>

              <div className="text-xs text-slate-400 uppercase tracking-wider mt-3 mb-1">
                S_lo trace (negative-shift accumulator)
              </div>
              <div className="flex items-end gap-[1px] h-16 bg-slate-950/40 border border-slate-800 rounded px-1 py-1">
                {traceLo.map((v, i) => (
                  <div
                    key={i}
                    className="flex-1 bg-blue-500/60"
                    style={{ height: `${(Math.abs(v) / maxAbs) * 100}%` }}
                    title={`S_lo[${i}] = ${v.toFixed(3)}`}
                  />
                ))}
              </div>
            </div>
          )}

          <details className="mt-3 text-xs text-slate-500">
            <summary className="cursor-pointer hover:text-slate-300">
              Raw response
            </summary>
            <pre className="mt-2 font-mono whitespace-pre-wrap">
              {JSON.stringify(resp, null, 2)}
            </pre>
          </details>
        </div>
      )}
    </section>
  )
}

export default RegimeShiftWidget
