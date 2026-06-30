import { useState, useEffect, useCallback, useRef } from 'react'
import { RefreshCw, Filter, ChevronLeft, ChevronRight, Wallet, Send, CheckCircle, AlertTriangle, RotateCcw, Zap, ExternalLink, Copy, X } from 'lucide-react'

const API = import.meta.env.VITE_API_URL || 'https://agentescrow402-api.onrender.com'
const CONTRACT_HASH = '5dd33e8e79789d386832a80c39006002383fa44dd76ba677cae3279f3a134451'
const CSPR_LIVE = 'https://testnet.cspr.live'

interface Stats {
  total: number
  pending: number
  released: number
  disputed: number
  volume: number
  db: string
  insurance_fee_bps?: number
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

interface Agent {
  address: string
  role: string
  total_escrows: number
  total_volume: number
}

type StatusFilter = 'all' | 'pending' | 'released' | 'disputed' | 'refunded'
type TabView = 'escrows' | 'agents' | 'operations'

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  released: 'bg-green-500/10 text-green-400 border-green-500/20',
  disputed: 'bg-red-500/10 text-red-400 border-red-500/20',
  refunded: 'bg-gray-500/10 text-gray-400 border-gray-500/20',
}

const STATUS_ICONS: Record<string, string> = {
  pending: '⏳',
  released: '✅',
  disputed: '⚠️',
  refunded: '↩️',
}

/* ---------- Skeleton ---------- */
function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse bg-ae-card/80 rounded ${className}`} />
}

function EscrowSkeleton() {
  return (
    <div className="bg-ae-card/40 border border-ae-border/50 rounded-xl p-4">
      <div className="flex items-start justify-between gap-4 mb-3">
        <div className="flex-1 min-w-0">
          <Skeleton className="h-3 w-48 mb-2" />
          <Skeleton className="h-4 w-72" />
        </div>
        <Skeleton className="h-5 w-16 rounded" />
      </div>
      <div className="flex items-center gap-6">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-3 w-14" />
      </div>
    </div>
  )
}

function StatsSkeleton() {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-8">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="bg-ae-card/60 border border-ae-border rounded-xl p-4">
          <Skeleton className="h-2.5 w-16 mb-2" />
          <Skeleton className="h-7 w-12" />
        </div>
      ))}
    </div>
  )
}

/* ---------- Wallet Connection ---------- */
function useWallet() {
  const [connected, setConnected] = useState(false)
  const [publicKey, setPublicKey] = useState<string | null>(null)
  const [connecting, setConnecting] = useState(false)

  const connect = useCallback(async () => {
    setConnecting(true)
    try {
      // Check for Casper Wallet / Signer
      const w = (window as any)
      if (w.CasperWalletProvider) {
        const provider = w.CasperWalletProvider()
        const ok = await provider.requestConnection()
        if (ok) {
          const key = await provider.getActivePublicKey()
          setPublicKey(key)
          setConnected(true)
        }
      } else if (w.casperlabsHelper) {
        // Legacy Casper Signer
        await w.casperlabsHelper.requestConnection()
        const key = await w.casperlabsHelper.getActivePublicKey()
        setPublicKey(key)
        setConnected(true)
      } else {
        // Demo mode — generate a mock key for demo
        const mockKey = '0202' + Array.from({ length: 64 }, () => Math.floor(Math.random() * 16).toString(16)).join('')
        setPublicKey(mockKey)
        setConnected(true)
      }
    } catch (err) {
      console.error('Wallet connection failed:', err)
      // Fallback to demo mode
      const mockKey = '0202' + Array.from({ length: 64 }, () => Math.floor(Math.random() * 16).toString(16)).join('')
      setPublicKey(mockKey)
      setConnected(true)
    } finally {
      setConnecting(false)
    }
  }, [])

  const disconnect = useCallback(() => {
    setConnected(false)
    setPublicKey(null)
  }, [])

  return { connected, publicKey, connecting, connect, disconnect }
}

/* ---------- Create Escrow Modal ---------- */
function CreateEscrowModal({ onClose, onSubmit, senderKey }: {
  onClose: () => void
  onSubmit: (data: { receiver: string; amount: number; ttl: number }) => void
  senderKey: string
}) {
  const [receiver, setReceiver] = useState('')
  const [amount, setAmount] = useState('')
  const [ttl, setTtl] = useState('3600')
  const [estimate, setEstimate] = useState<{ net_amount: number; insurance_fee: number; fee_pct: string } | null>(null)

  useEffect(() => {
    const amt = parseInt(amount)
    if (amt > 0) {
      fetch(`${API}/estimate?amount=${amt}`)
        .then(r => r.json())
        .then(d => setEstimate(d))
        .catch(() => setEstimate(null))
    } else {
      setEstimate(null)
    }
  }, [amount])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit({ receiver, amount: parseInt(amount), ttl: parseInt(ttl) })
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-ae-card border border-ae-border rounded-2xl p-6 max-w-md w-full" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-lg font-bold text-white">Create Escrow</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-white"><X size={20} /></button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Sender (you)</label>
            <div className="text-xs font-mono text-ae-accent bg-ae-bg/60 rounded-lg p-2.5 truncate">{senderKey}</div>
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">Receiver Public Key</label>
            <input
              type="text"
              value={receiver}
              onChange={e => setReceiver(e.target.value)}
              placeholder="0202..."
              required
              className="w-full bg-ae-bg/60 border border-ae-border rounded-lg px-3 py-2.5 text-sm text-white font-mono placeholder:text-gray-600 focus:border-ae-accent focus:outline-none"
            />
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">Amount (CSPR)</label>
            <input
              type="number"
              value={amount}
              onChange={e => setAmount(e.target.value)}
              placeholder="10000"
              min="1"
              required
              className="w-full bg-ae-bg/60 border border-ae-border rounded-lg px-3 py-2.5 text-sm text-white font-mono placeholder:text-gray-600 focus:border-ae-accent focus:outline-none"
            />
            {estimate && (
              <div className="flex items-center gap-3 mt-2 text-[11px]">
                <span className="text-gray-500">Net: <span className="text-green-400 font-mono">{estimate.net_amount.toLocaleString()}</span></span>
                <span className="text-gray-500">Fee: <span className="text-yellow-400 font-mono">{estimate.insurance_fee.toLocaleString()}</span> ({estimate.fee_pct})</span>
              </div>
            )}
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">TTL (seconds)</label>
            <select
              value={ttl}
              onChange={e => setTtl(e.target.value)}
              className="w-full bg-ae-bg/60 border border-ae-border rounded-lg px-3 py-2.5 text-sm text-white focus:border-ae-accent focus:outline-none"
            >
              <option value="1800">30 minutes</option>
              <option value="3600">1 hour</option>
              <option value="7200">2 hours</option>
              <option value="86400">24 hours</option>
              <option value="604800">7 days</option>
            </select>
          </div>

          <button
            type="submit"
            className="w-full py-3 rounded-xl bg-ae-accent text-white font-semibold hover:bg-ae-accent-bright transition-colors flex items-center justify-center gap-2"
          >
            <Send size={16} /> Create Escrow
          </button>
        </form>
      </div>
    </div>
  )
}

/* ---------- Action Modal ---------- */
function ActionModal({ action, escrow, onClose, onConfirm }: {
  action: 'release' | 'dispute' | 'refund'
  escrow: Escrow
  onClose: () => void
  onConfirm: () => void
}) {
  const config = {
    release: { title: 'Release Funds', desc: 'Release escrowed funds to the receiver. This action is final.', color: 'bg-green-600 hover:bg-green-500', icon: <CheckCircle size={16} /> },
    dispute: { title: 'Open Dispute', desc: 'Flag this escrow as disputed. An arbiter will review.', color: 'bg-red-600 hover:bg-red-500', icon: <AlertTriangle size={16} /> },
    refund: { title: 'Refund Sender', desc: 'Return funds to the original sender.', color: 'bg-gray-600 hover:bg-gray-500', icon: <RotateCcw size={16} /> },
  }[action]

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-ae-card border border-ae-border rounded-2xl p-6 max-w-sm w-full" onClick={e => e.stopPropagation()}>
        <h3 className="text-lg font-bold text-white mb-2">{config.title}</h3>
        <p className="text-sm text-gray-400 mb-4">{config.desc}</p>

        <div className="bg-ae-bg/60 rounded-lg p-3 mb-5 text-xs">
          <div className="flex justify-between mb-1">
            <span className="text-gray-500">Hash</span>
            <span className="text-gray-300 font-mono truncate max-w-[180px]">{escrow.service_hash}</span>
          </div>
          <div className="flex justify-between mb-1">
            <span className="text-gray-500">Amount</span>
            <span className="text-white font-mono font-bold">{escrow.amount.toLocaleString()} CSPR</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">Status</span>
            <span className={STATUS_STYLES[escrow.status]?.includes('yellow') ? 'text-yellow-400' : 'text-gray-300'}>{escrow.status}</span>
          </div>
        </div>

        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 py-2.5 rounded-xl border border-ae-border text-gray-400 hover:text-white transition-colors">Cancel</button>
          <button onClick={onConfirm} className={`flex-1 py-2.5 rounded-xl text-white font-semibold transition-colors flex items-center justify-center gap-2 ${config.color}`}>
            {config.icon} {config.title}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ---------- Toast ---------- */
function Toast({ message, type, onClose }: { message: string; type: 'success' | 'error' | 'info'; onClose: () => void }) {
  useEffect(() => {
    const t = setTimeout(onClose, 4000)
    return () => clearTimeout(t)
  }, [onClose])

  const colors = {
    success: 'bg-green-500/10 border-green-500/30 text-green-400',
    error: 'bg-red-500/10 border-red-500/30 text-red-400',
    info: 'bg-ae-accent/10 border-ae-accent/30 text-ae-accent',
  }

  return (
    <div className={`fixed top-20 right-4 z-50 px-4 py-3 rounded-xl border ${colors[type]} text-sm animate-fade-in-down shadow-lg max-w-sm`}>
      {message}
    </div>
  )
}

/* ---------- Main Dashboard ---------- */
export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [escrows, setEscrows] = useState<Escrow[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [statsLoading, setStatsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<TabView>('escrows')
  const [showCreate, setShowCreate] = useState(false)
  const [actionModal, setActionModal] = useState<{ action: 'release' | 'dispute' | 'refund'; escrow: Escrow } | null>(null)
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const limit = 5

  const wallet = useWallet()

  const fetchStats = useCallback(async () => {
    setStatsLoading(true)
    try {
      const r = await fetch(`${API}/stats`)
      if (r.ok) setStats(await r.json())
    } catch { /* */ } finally {
      setStatsLoading(false)
    }
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

  const fetchAgents = useCallback(async () => {
    try {
      const r = await fetch(`${API}/agents`)
      if (r.ok) {
        const data = await r.json()
        setAgents(data.agents || [])
      }
    } catch { /* */ }
  }, [])

  useEffect(() => { fetchStats() }, [fetchStats])
  useEffect(() => { fetchEscrows() }, [fetchEscrows])
  useEffect(() => { if (tab === 'agents') fetchAgents() }, [tab, fetchAgents])

  const totalPages = Math.max(1, Math.ceil(total / limit))

  const formatAge = (ts: number) => {
    const diff = Math.floor(Date.now() / 1000) - ts
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  }

  const copyHash = (hash: string) => {
    navigator.clipboard.writeText(hash)
    setCopied(hash)
    setTimeout(() => setCopied(null), 2000)
  }

  const handleCreateEscrow = async (data: { receiver: string; amount: number; ttl: number }) => {
    if (!wallet.publicKey) return
    try {
      const r = await fetch(`${API}/escrows`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sender: wallet.publicKey, ...data }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const result = await r.json()
      setToast({ message: `Escrow created: ${result.service_hash?.slice(0, 12)}...`, type: 'success' })
      setShowCreate(false)
      fetchEscrows()
      fetchStats()
    } catch (err) {
      setToast({ message: `Failed: ${err instanceof Error ? err.message : 'Unknown error'}`, type: 'error' })
    }
  }

  const handleAction = async (action: string, serviceHash: string) => {
    try {
      const r = await fetch(`${API}/escrows/${serviceHash}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ caller: wallet.publicKey }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setToast({ message: `Escrow ${action}d`, type: 'success' })
      setActionModal(null)
      fetchEscrows()
      fetchStats()
    } catch (err) {
      setToast({ message: `Action failed: ${err instanceof Error ? err.message : 'Unknown'}`, type: 'error' })
    }
  }

  const feePct = stats?.insurance_fee_bps ? (stats.insurance_fee_bps / 100).toFixed(1) : '2.0'

  return (
    <div className="min-h-[calc(100vh-3.5rem)]">
      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
      {showCreate && wallet.publicKey && (
        <CreateEscrowModal onClose={() => setShowCreate(false)} onSubmit={handleCreateEscrow} senderKey={wallet.publicKey} />
      )}
      {actionModal && (
        <ActionModal
          action={actionModal.action}
          escrow={actionModal.escrow}
          onClose={() => setActionModal(null)}
          onConfirm={() => handleAction(actionModal.action, actionModal.escrow.service_hash)}
        />
      )}

      {/* Dashboard header bar */}
      <div className="border-b border-ae-border/40 bg-ae-bg/80 backdrop-blur">
        <div className="ae-section flex items-center justify-between h-12">
          <div className="flex items-center gap-4">
            <h1 className="text-white font-bold text-sm flex items-center gap-2">
              <Zap size={14} className="text-ae-accent" /> Escrow Dashboard
            </h1>
            <a
              href={`${CSPR_LIVE}/contract/${CONTRACT_HASH}`}
              target="_blank"
              rel="noreferrer"
              className="hidden sm:flex items-center gap-1 text-[10px] text-gray-600 hover:text-ae-accent transition-colors font-mono"
            >
              {CONTRACT_HASH.slice(0, 8)}...{CONTRACT_HASH.slice(-6)} <ExternalLink size={9} />
            </a>
          </div>

          <div className="flex items-center gap-3">
            <button onClick={() => { fetchStats(); fetchEscrows() }} className="text-gray-500 hover:text-white transition-colors p-1">
              <RefreshCw size={14} />
            </button>
            {wallet.connected ? (
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-500/10 border border-green-500/20">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                  <span className="text-[11px] text-green-400 font-mono">{wallet.publicKey?.slice(0, 8)}...{wallet.publicKey?.slice(-4)}</span>
                </div>
                <button onClick={wallet.disconnect} className="text-xs text-gray-500 hover:text-red-400 transition-colors">×</button>
              </div>
            ) : (
              <button
                onClick={wallet.connect}
                disabled={wallet.connecting}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-ae-accent text-white text-xs font-semibold hover:bg-ae-accent-bright transition-colors disabled:opacity-50"
              >
                <Wallet size={13} /> {wallet.connecting ? 'Connecting...' : 'Connect Wallet'}
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="ae-section py-6">
        {/* Stats cards */}
        {statsLoading ? <StatsSkeleton /> : stats && (
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-6">
            {[
              { label: 'Total Escrows', val: stats.total, color: 'text-white', icon: '📦' },
              { label: 'Pending', val: stats.pending, color: 'text-yellow-400', icon: '⏳' },
              { label: 'Released', val: stats.released, color: 'text-green-400', icon: '✅' },
              { label: 'Disputed', val: stats.disputed, color: 'text-red-400', icon: '⚠️' },
              { label: 'Volume', val: `${(stats.volume / 1000).toFixed(1)}K`, color: 'text-ae-accent', icon: '💰' },
            ].map((s, i) => (
              <div key={i} className="bg-ae-card/60 border border-ae-border rounded-xl p-4 hover:border-ae-border/80 transition-colors">
                <div className="flex items-center gap-1.5 mb-1">
                  <span className="text-xs">{s.icon}</span>
                  <span className="text-[10px] text-gray-500 uppercase tracking-wider">{s.label}</span>
                </div>
                <div className={`text-2xl font-bold font-mono ${s.color}`}>{s.val}</div>
              </div>
            ))}
          </div>
        )}

        {/* Tab bar + actions */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-1 bg-ae-card/40 rounded-lg p-0.5">
            {(['escrows', 'agents', 'operations'] as TabView[]).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-1.5 rounded-md text-xs font-medium transition-all ${
                  tab === t ? 'bg-ae-accent text-white' : 'text-gray-500 hover:text-gray-300'
                }`}
              >
                {t === 'escrows' ? 'Escrows' : t === 'agents' ? 'Agents' : 'Operations'}
              </button>
            ))}
          </div>

          {tab === 'escrows' && wallet.connected && (
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-ae-accent text-white text-xs font-semibold hover:bg-ae-accent-bright transition-colors"
            >
              <Send size={12} /> New Escrow
            </button>
          )}
        </div>

        {/* ========== ESCROWS TAB ========== */}
        {tab === 'escrows' && (
          <>
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
              <span className="ml-auto text-[10px] text-gray-600 font-mono">
                Insurance: {feePct}%
              </span>
            </div>

            {error && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 mb-4 text-red-400 text-sm">
                {error}
              </div>
            )}

            {/* Escrow list with skeleton */}
            <div className="space-y-2 mb-6">
              {loading ? (
                Array.from({ length: 3 }).map((_, i) => <EscrowSkeleton key={i} />)
              ) : escrows.length === 0 ? (
                <div className="text-center py-16 text-gray-600">No escrows found</div>
              ) : (
                escrows.map(esc => (
                  <div key={esc.service_hash} className="bg-ae-card/40 border border-ae-border/50 rounded-xl p-4 hover:border-ae-border transition-colors group">
                    <div className="flex items-start justify-between gap-4 mb-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs text-gray-500 font-mono truncate">{esc.service_hash}</span>
                          <button
                            onClick={() => copyHash(esc.service_hash)}
                            className="text-gray-600 hover:text-ae-accent transition-colors opacity-0 group-hover:opacity-100"
                          >
                            <Copy size={10} />
                          </button>
                          {copied === esc.service_hash && <span className="text-[9px] text-ae-accent">Copied!</span>}
                        </div>
                        <div className="flex items-center gap-2 text-sm">
                          <span className="text-gray-400 font-mono text-xs truncate max-w-[120px] sm:max-w-[180px]">{esc.sender}</span>
                          <span className="text-gray-600">→</span>
                          <span className="text-gray-400 font-mono text-xs truncate max-w-[120px] sm:max-w-[180px]">{esc.receiver}</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase border ${STATUS_STYLES[esc.status] || ''}`}>
                          {STATUS_ICONS[esc.status]} {esc.status}
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-5 text-xs text-gray-500">
                        <span><span className="text-white font-mono font-bold">{esc.amount.toLocaleString()}</span> CSPR</span>
                        <span>TTL: {esc.ttl >= 86400 ? `${Math.floor(esc.ttl / 86400)}d` : esc.ttl >= 3600 ? `${Math.floor(esc.ttl / 3600)}h` : `${Math.floor(esc.ttl / 60)}m`}</span>
                        <span>{formatAge(esc.created_at)}</span>
                        {esc.deploy_hash && (
                          <a
                            href={`${CSPR_LIVE}/deploy/${esc.deploy_hash}`}
                            target="_blank"
                            rel="noreferrer"
                            className="text-ae-accent hover:text-ae-accent-bright flex items-center gap-0.5"
                          >
                            On-chain <ExternalLink size={9} />
                          </a>
                        )}
                      </div>

                      {/* Action buttons for pending escrows */}
                      {wallet.connected && esc.status === 'pending' && (
                        <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={() => setActionModal({ action: 'release', escrow: esc })}
                            className="px-2 py-1 rounded-md bg-green-500/10 text-green-400 text-[10px] font-medium hover:bg-green-500/20 transition-colors flex items-center gap-1"
                          >
                            <CheckCircle size={10} /> Release
                          </button>
                          <button
                            onClick={() => setActionModal({ action: 'dispute', escrow: esc })}
                            className="px-2 py-1 rounded-md bg-red-500/10 text-red-400 text-[10px] font-medium hover:bg-red-500/20 transition-colors flex items-center gap-1"
                          >
                            <AlertTriangle size={10} /> Dispute
                          </button>
                          <button
                            onClick={() => setActionModal({ action: 'refund', escrow: esc })}
                            className="px-2 py-1 rounded-md bg-gray-500/10 text-gray-400 text-[10px] font-medium hover:bg-gray-500/20 transition-colors flex items-center gap-1"
                          >
                            <RotateCcw size={10} /> Refund
                          </button>
                        </div>
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
                <span className="text-xs text-gray-500 font-mono">{page} / {totalPages}</span>
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="p-2 rounded-lg bg-ae-card/40 border border-ae-border/40 text-gray-500 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  <ChevronRight size={16} />
                </button>
              </div>
            )}
          </>
        )}

        {/* ========== AGENTS TAB ========== */}
        {tab === 'agents' && (
          <div className="space-y-2">
            {agents.length === 0 ? (
              <div className="text-center py-16 text-gray-600">Loading agents...</div>
            ) : agents.map((agent, i) => (
              <div key={agent.address} className="bg-ae-card/40 border border-ae-border/50 rounded-xl p-4 flex items-center justify-between hover:border-ae-border transition-colors">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-ae-accent/10 flex items-center justify-center text-ae-accent font-bold text-xs">
                    #{i + 1}
                  </div>
                  <div>
                    <div className="text-xs font-mono text-gray-300 truncate max-w-[200px] sm:max-w-[300px]">{agent.address}</div>
                    <div className="text-[10px] text-gray-500 capitalize">{agent.role}</div>
                  </div>
                </div>
                <div className="flex items-center gap-6 text-xs">
                  <div className="text-center">
                    <div className="font-mono font-bold text-white">{agent.total_escrows}</div>
                    <div className="text-[9px] text-gray-600">escrows</div>
                  </div>
                  <div className="text-center">
                    <div className="font-mono font-bold text-ae-accent">{(agent.total_volume / 1000).toFixed(1)}K</div>
                    <div className="text-[9px] text-gray-600">volume</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ========== OPERATIONS TAB ========== */}
        {tab === 'operations' && (
          <div className="space-y-4">
            {!wallet.connected ? (
              <div className="text-center py-16">
                <Wallet size={40} className="text-gray-600 mx-auto mb-4" />
                <p className="text-gray-500 mb-4">Connect your wallet to interact with escrows</p>
                <button
                  onClick={wallet.connect}
                  className="px-6 py-2.5 rounded-xl bg-ae-accent text-white font-semibold hover:bg-ae-accent-bright transition-colors"
                >
                  Connect Wallet
                </button>
              </div>
            ) : (
              <>
                <div className="bg-ae-card/60 border border-ae-border rounded-xl p-5">
                  <h3 className="text-sm font-bold text-white mb-3 flex items-center gap-2"><Send size={14} className="text-ae-accent" /> Quick Actions</h3>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <button
                      onClick={() => setShowCreate(true)}
                      className="p-4 rounded-xl bg-ae-accent/10 border border-ae-accent/20 hover:border-ae-accent/40 transition-colors text-left"
                    >
                      <Send size={20} className="text-ae-accent mb-2" />
                      <div className="text-sm font-semibold text-white">Create Escrow</div>
                      <div className="text-[11px] text-gray-500 mt-1">Lock CSPR in a new escrow contract</div>
                    </button>
                    <a
                      href={`${CSPR_LIVE}/contract/${CONTRACT_HASH}`}
                      target="_blank"
                      rel="noreferrer"
                      className="p-4 rounded-xl bg-ae-card/60 border border-ae-border hover:border-ae-border/80 transition-colors text-left"
                    >
                      <ExternalLink size={20} className="text-gray-400 mb-2" />
                      <div className="text-sm font-semibold text-white">View Contract</div>
                      <div className="text-[11px] text-gray-500 mt-1">Inspect on Casper testnet explorer</div>
                    </a>
                    <div className="p-4 rounded-xl bg-ae-card/60 border border-ae-border">
                      <Zap size={20} className="text-yellow-400 mb-2" />
                      <div className="text-sm font-semibold text-white">Insurance Pool</div>
                      <div className="text-[11px] text-gray-500 mt-1">{feePct}% fee on every escrow for dispute resolution</div>
                    </div>
                  </div>
                </div>

                <div className="bg-ae-card/60 border border-ae-border rounded-xl p-5">
                  <h3 className="text-sm font-bold text-white mb-3">Connected Account</h3>
                  <div className="space-y-2 text-xs">
                    <div className="flex justify-between">
                      <span className="text-gray-500">Public Key</span>
                      <span className="text-gray-300 font-mono text-[11px] truncate max-w-[280px]">{wallet.publicKey}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">Network</span>
                      <span className="text-yellow-400">Casper Testnet</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">Contract</span>
                      <a href={`${CSPR_LIVE}/contract/${CONTRACT_HASH}`} target="_blank" rel="noreferrer" className="text-ae-accent font-mono text-[11px] hover:text-ae-accent-bright">
                        {CONTRACT_HASH.slice(0, 12)}...
                      </a>
                    </div>
                  </div>
                </div>

                <div className="bg-ae-card/60 border border-ae-border rounded-xl p-5">
                  <h3 className="text-sm font-bold text-white mb-3">Escrow Workflow</h3>
                  <div className="flex items-center gap-2 text-[11px] flex-wrap">
                    {[
                      { step: '1', label: 'Create', desc: 'Lock funds' },
                      { step: '2', label: 'Pending', desc: 'Service delivered' },
                      { step: '3', label: 'Release / Dispute', desc: 'Resolve' },
                    ].map((s, i) => (
                      <div key={i} className="flex items-center gap-2">
                        {i > 0 && <span className="text-gray-600">→</span>}
                        <div className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-ae-bg/60 border border-ae-border/40">
                          <span className="w-5 h-5 rounded-full bg-ae-accent/20 text-ae-accent flex items-center justify-center text-[10px] font-bold">{s.step}</span>
                          <div>
                            <div className="font-semibold text-white">{s.label}</div>
                            <div className="text-gray-500 text-[9px]">{s.desc}</div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* DB status */}
        {stats && (
          <div className="mt-6 text-center">
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
