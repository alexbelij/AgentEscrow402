import { useState, useEffect, useCallback } from 'react'
import { ArrowLeft, RefreshCw, Filter, ChevronLeft, ChevronRight } from 'lucide-react'

const API = import.meta.env.VITE_API_URL || 'https://agentescrow402-api.onrender.com'

interface Stats {
  total: number
  pending: number
  released: number
  disputed: number
  volume: number
  db: string
}

interface Escrow {
  service_hash: string
  sender: string
  receiver: string
  amount: number
  status: string
  ttl: number
  created_at: number
  deploy_hash: string | null
}

type StatusFilter = 'all' | 'pending' | 'released' | 'disputed' | 'refunded'

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  released: 'bg-green-500/10 text-green-400 border-green-500/20',
  disputed: 'bg-red-500/10 text-red-400 border-red-500/20',
  refunded: 'bg-gray-500/10 text-gray-400 border-gray-500/20',
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [escrows, setEscrows] = useState<Escrow[]>([])
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const limit = 5

  const fetchStats = useCallback(async () => {
    try {
      const r = await fetch(`${API}/stats`)
      if (r.ok) setStats(await r.json())
    } catch { /* */ }
  }, [])

  const fetchEscrows = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ limit: String(limit), offset: String((page - 1) * limit) })
      if (filter !== 'all') params.set('status', filter)
      const r = await fetch(`${API}/escrows?${params}`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json()
      setEscrows(data.escrows || [])
      setTotal(data.total || data.escrows?.length || 0)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [filter, page])

  useEffect(() => { fetchStats() }, [fetchStats])
  useEffect(() => { fetchEscrows() }, [fetchEscrows])

  const totalPages = Math.max(1, Math.ceil(total / limit))

  const formatAge = (ts: number) => {
    const diff = Math.floor(Date.now() / 1000) - ts
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  }

  return (
    <div className="min-h-screen bg-ae-bg">
      {/* Header */}
      <div className="border-b border-ae-border/40 bg-ae-bg/90 backdrop-blur sticky top-0 z-30">
        <div className="ae-section flex items-center justify-between h-14">
          <div className="flex items-center gap-3">
            <a href="/" className="text-gray-500 hover:text-white transition-colors">
              <ArrowLeft size={18} />
            </a>
            <img src="/images/logo.webp" alt="AE402" className="h-5 w-auto" />
            <h1 className="text-white font-bold text-sm">Escrow Dashboard</h1>
          </div>
          <button onClick={() => { fetchStats(); fetchEscrows() }} className="text-gray-500 hover:text-white transition-colors">
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      <div className="ae-section py-8">
        {/* Stats cards */}
        {stats && (
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-8">
            {[
              { label: 'Total Escrows', val: stats.total, color: 'text-white' },
              { label: 'Pending', val: stats.pending, color: 'text-yellow-400' },
              { label: 'Released', val: stats.released, color: 'text-green-400' },
              { label: 'Disputed', val: stats.disputed, color: 'text-red-400' },
              { label: 'Volume', val: `${(stats.volume / 1000).toFixed(1)}K`, color: 'text-ae-accent' },
            ].map((s, i) => (
              <div key={i} className="bg-ae-card/60 border border-ae-border rounded-xl p-4">
                <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">{s.label}</div>
                <div className={`text-2xl font-bold font-mono ${s.color}`}>{s.val}</div>
              </div>
            ))}
          </div>
        )}

        {/* Filter bar */}
        <div className="flex items-center gap-2 mb-4">
          <Filter size={14} className="text-gray-500" />
          {(['all', 'pending', 'released', 'disputed', 'refunded'] as StatusFilter[]).map(f => (
            <button
              key={f}
              onClick={() => { setFilter(f); setPage(1) }}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-all ${
                filter === f
                  ? 'bg-ae-accent text-white'
                  : 'bg-ae-card/40 text-gray-500 hover:text-gray-300 border border-ae-border/40'
              }`}
            >
              {f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 mb-4 text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Escrow list */}
        <div className="space-y-2 mb-6">
          {loading && escrows.length === 0 ? (
            <div className="text-center py-16 text-gray-600">Loading escrows...</div>
          ) : escrows.length === 0 ? (
            <div className="text-center py-16 text-gray-600">No escrows found</div>
          ) : (
            escrows.map(esc => (
              <div key={esc.service_hash} className="bg-ae-card/40 border border-ae-border/50 rounded-xl p-4 hover:border-ae-border transition-colors">
                <div className="flex items-start justify-between gap-4 mb-3">
                  <div className="flex-1 min-w-0">
                    <div className="text-xs text-gray-500 font-mono truncate mb-1">{esc.service_hash}</div>
                    <div className="flex items-center gap-2 text-sm">
                      <span className="text-gray-300 font-mono">{esc.sender}</span>
                      <span className="text-gray-600">→</span>
                      <span className="text-gray-300 font-mono">{esc.receiver}</span>
                    </div>
                  </div>
                  <span className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase border ${STATUS_STYLES[esc.status] || ''}`}>
                    {esc.status}
                  </span>
                </div>
                <div className="flex items-center gap-6 text-xs text-gray-500">
                  <span><span className="text-white font-mono font-bold">{esc.amount.toLocaleString()}</span> CSPR</span>
                  <span>TTL: {esc.ttl}s</span>
                  <span>{formatAge(esc.created_at)}</span>
                  {esc.deploy_hash && (
                    <a
                      href={`https://testnet.cspr.live/deploy/${esc.deploy_hash}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-ae-accent hover:text-ae-accent-bright"
                    >
                      On-chain ↗
                    </a>
                  )}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="p-2 rounded-lg bg-ae-card/40 border border-ae-border/40 text-gray-500 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ChevronLeft size={16} />
            </button>
            <span className="text-xs text-gray-500 font-mono">
              {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="p-2 rounded-lg bg-ae-card/40 border border-ae-border/40 text-gray-500 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        )}

        {/* DB status */}
        {stats && (
          <div className="mt-8 text-center">
            <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[10px] ${
              stats.db === 'connected' ? 'bg-green-500/10 text-green-400' : 'bg-yellow-500/10 text-yellow-400'
            }`}>
              <span className={`w-1.5 h-1.5 rounded-full ${stats.db === 'connected' ? 'bg-green-400' : 'bg-yellow-400'} animate-pulse`} />
              DB: {stats.db}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
