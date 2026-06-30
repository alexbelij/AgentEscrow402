import { useState, useEffect, useCallback } from 'react'
import {
  RefreshCw, Filter, ChevronLeft, ChevronRight, Wallet, Send, CheckCircle,
  AlertTriangle, RotateCcw, Zap, ExternalLink, Copy, X, Package, Clock,
  DollarSign, Info, Shield, Users, ArrowRight, ChevronDown, ChevronUp,
  Activity, TrendingUp, Lock, Unlock, FileText
} from 'lucide-react'

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
  agent: string
  address: string
  role: string
  score: number
  completed: number
  disputed: number
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

const STATUS_ICON: Record<string, typeof Clock> = {
  pending: Clock,
  released: CheckCircle,
  disputed: AlertTriangle,
  refunded: RotateCcw,
}

const TAB_INFO: Record<TabView, { title: string; desc: string }> = {
  escrows: {
    title: 'Active Escrows',
    desc: 'All escrow transactions between AI agents. Filter by status, view on-chain deploys, and manage pending escrows with release/dispute/refund actions.',
  },
  agents: {
    title: 'Agent Leaderboard',
    desc: 'Registered agents ranked by transaction volume. Click any agent to see their public key, role, and escrow history on the Casper testnet explorer.',
  },
  operations: {
    title: 'Quick Operations',
    desc: 'Create new escrows, view contract details, and understand the full escrow lifecycle. Connect your wallet to interact with the contract.',
  },
}

/* ---------- Skeleton ---------- */
function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse bg-ae-card/80 rounded ${className}`} />
}

function EscrowSkeleton() {
  return (
    <div className="bg-ae-card/40 border border-ae-border/50 rounded-xl p-5">
      <div className="flex items-start justify-between gap-4 mb-3">
        <div className="flex-1 min-w-0">
          <Skeleton className="h-4 w-48 mb-2" />
          <Skeleton className="h-4 w-72" />
        </div>
        <Skeleton className="h-6 w-20 rounded" />
      </div>
      <div className="flex items-center gap-6">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-4 w-16" />
      </div>
    </div>
  )
}

function StatsSkeleton() {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-8">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="bg-ae-card/60 border border-ae-border rounded-xl p-5">
          <Skeleton className="h-3 w-20 mb-3" />
          <Skeleton className="h-8 w-14" />
        </div>
      ))}
    </div>
  )
}

/* ---------- Tooltip ---------- */
function Tip({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <span className="relative inline-flex">
      <button onClick={() => setOpen(!open)} className="text-gray-600 hover:text-ae-accent transition-colors ml-1">
        <Info size={14} />
      </button>
      {open && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 rounded-lg bg-gray-900 border border-ae-border text-[13px] text-gray-300 w-64 z-50 shadow-xl">
          {text}
          <div className="absolute top-full left-1/2 -translate-x-1/2 w-2 h-2 bg-gray-900 border-r border-b border-ae-border rotate-45 -mt-1" />
        </div>
      )}
    </span>
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
        await w.casperlabsHelper.requestConnection()
        const key = await w.casperlabsHelper.getActivePublicKey()
        setPublicKey(key)
        setConnected(true)
      } else {
        const mockKey = '0202' + Array.from({ length: 64 }, () => Math.floor(Math.random() * 16).toString(16)).join('')
        setPublicKey(mockKey)
        setConnected(true)
      }
    } catch {
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
            <label className="text-sm text-gray-500 block mb-1">Sender (you)</label>
            <div className="text-sm font-mono text-ae-accent bg-ae-bg/60 rounded-lg p-3 truncate">{senderKey}</div>
          </div>

          <div>
            <label className="text-sm text-gray-500 block mb-1">Receiver Public Key</label>
            <input
              type="text"
              value={receiver}
              onChange={e => setReceiver(e.target.value)}
              placeholder="0202..."
              required
              className="w-full bg-ae-bg/60 border border-ae-border rounded-lg px-3 py-3 text-sm text-white font-mono placeholder:text-gray-600 focus:border-ae-accent focus:outline-none"
            />
          </div>

          <div>
            <label className="text-sm text-gray-500 block mb-1">Amount (CSPR)</label>
            <input
              type="number"
              value={amount}
              onChange={e => setAmount(e.target.value)}
              placeholder="10000"
              min="1"
              required
              className="w-full bg-ae-bg/60 border border-ae-border rounded-lg px-3 py-3 text-sm text-white font-mono placeholder:text-gray-600 focus:border-ae-accent focus:outline-none"
            />
            {estimate && (
              <div className="flex items-center gap-4 mt-2 text-sm">
                <span className="text-gray-500">Net: <span className="text-green-400 font-mono">{estimate.net_amount.toLocaleString()}</span></span>
                <span className="text-gray-500">Fee: <span className="text-yellow-400 font-mono">{estimate.insurance_fee.toLocaleString()}</span> ({estimate.fee_pct})</span>
              </div>
            )}
          </div>

          <div>
            <label className="text-sm text-gray-500 block mb-1">TTL (time to live)</label>
            <select
              value={ttl}
              onChange={e => setTtl(e.target.value)}
              className="w-full bg-ae-bg/60 border border-ae-border rounded-lg px-3 py-3 text-sm text-white focus:border-ae-accent focus:outline-none"
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
            className="w-full py-3 rounded-xl bg-ae-accent text-white font-semibold hover:bg-ae-accent-bright transition-colors flex items-center justify-center gap-2 text-sm"
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
    release: { title: 'Release Funds', desc: 'Release escrowed funds to the receiver. This action is final and cannot be reversed.', color: 'bg-green-600 hover:bg-green-500', icon: <Unlock size={16} /> },
    dispute: { title: 'Open Dispute', desc: 'Flag this escrow as disputed. An arbiter will review the case and decide the outcome.', color: 'bg-red-600 hover:bg-red-500', icon: <AlertTriangle size={16} /> },
    refund: { title: 'Refund Sender', desc: 'Return the full amount to the original sender. Insurance fee is non-refundable.', color: 'bg-gray-600 hover:bg-gray-500', icon: <RotateCcw size={16} /> },
  }[action]

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-ae-card border border-ae-border rounded-2xl p-6 max-w-sm w-full" onClick={e => e.stopPropagation()}>
        <h3 className="text-lg font-bold text-white mb-2">{config.title}</h3>
        <p className="text-sm text-gray-400 mb-4">{config.desc}</p>

        <div className="bg-ae-bg/60 rounded-lg p-4 mb-5 text-sm space-y-2">
          <div className="flex justify-between">
            <span className="text-gray-500">Hash</span>
            <span className="text-gray-300 font-mono truncate max-w-[180px]">{escrow.service_hash}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">Amount</span>
            <span className="text-white font-mono font-bold">{escrow.amount.toLocaleString()} CSPR</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">Status</span>
            <span className="text-gray-300">{escrow.status}</span>
          </div>
        </div>

        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 py-3 rounded-xl border border-ae-border text-gray-400 hover:text-white transition-colors text-sm">Cancel</button>
          <button onClick={onConfirm} className={`flex-1 py-3 rounded-xl text-white font-semibold transition-colors flex items-center justify-center gap-2 text-sm ${config.color}`}>
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
  const icons = { success: <CheckCircle size={16} />, error: <AlertTriangle size={16} />, info: <Info size={16} /> }

  return (
    <div className={`fixed top-20 right-4 z-50 px-4 py-3 rounded-xl border ${colors[type]} text-sm animate-fade-in-down shadow-lg max-w-sm flex items-center gap-2`}>
      {icons[type]} {message}
    </div>
  )
}

/* ---------- Agent Detail Panel ---------- */
function AgentDetail({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  return (
    <div className="bg-ae-card/60 border border-ae-accent/20 rounded-xl p-5 mt-2 animate-fade-in-down">
      <div className="flex items-center justify-between mb-4">
        <h4 className="text-sm font-bold text-white flex items-center gap-2">
          <Users size={14} className="text-ae-accent" /> Agent Details
        </h4>
        <button onClick={onClose} className="text-gray-600 hover:text-white"><ChevronUp size={16} /></button>
      </div>
      <div className="grid sm:grid-cols-2 gap-4 text-sm">
        <div>
          <p className="text-gray-500 mb-1">Public Key</p>
          <p className="font-mono text-gray-300 text-sm break-all">{agent.address}</p>
        </div>
        <div>
          <p className="text-gray-500 mb-1">Role</p>
          <p className="text-white capitalize font-semibold">{agent.role}</p>
          <p className="text-gray-600 text-sm mt-1">
            {agent.role === 'sender' ? 'Initiates escrow payments to service providers' :
             agent.role === 'receiver' ? 'Receives escrowed funds after service delivery' :
             'Participates in escrow transactions'}
          </p>
        </div>
        <div>
          <p className="text-gray-500 mb-1">Total Escrows</p>
          <p className="text-white font-mono font-bold text-lg">{agent.total_escrows}</p>
        </div>
        <div>
          <p className="text-gray-500 mb-1">Total Volume</p>
          <p className="text-ae-accent font-mono font-bold text-lg">{agent.total_volume.toLocaleString()} CSPR</p>
        </div>
      </div>
      <div className="mt-4 flex gap-2">
        <a
          href={`${CSPR_LIVE}/account/${agent.address}`}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-ae-accent/10 text-ae-accent text-sm hover:bg-ae-accent/20 transition-colors"
        >
          <ExternalLink size={14} /> View on Explorer
        </a>
      </div>
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
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null)
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
        const raw = data.agents || []
        setAgents(raw.map((a: any) => ({
          ...a,
          address: a.agent || a.address || '',
          total_escrows: a.completed ?? a.total_escrows ?? 0,
          total_volume: a.total_volume ?? (a.completed || 0) * 10000,
          score: a.score ?? 50,
        })))
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
      setToast({ message: `Escrow ${action}d successfully`, type: 'success' })
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
        <div className="ae-section flex items-center justify-between h-14">
          <div className="flex items-center gap-4">
            <h1 className="text-white font-bold text-sm flex items-center gap-2">
              <Activity size={14} className="text-ae-accent" /> Escrow Dashboard
            </h1>
            <a
              href={`${CSPR_LIVE}/contract/${CONTRACT_HASH}`}
              target="_blank"
              rel="noreferrer"
              className="hidden sm:flex items-center gap-1 text-sm text-gray-600 hover:text-ae-accent transition-colors font-mono"
            >
              {CONTRACT_HASH.slice(0, 8)}...{CONTRACT_HASH.slice(-6)} <ExternalLink size={10} />
            </a>
          </div>

          <div className="flex items-center gap-3">
            <button onClick={() => { fetchStats(); fetchEscrows() }} className="text-gray-500 hover:text-white transition-colors p-1.5" title="Refresh data">
              <RefreshCw size={14} />
            </button>
            {wallet.connected ? (
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-green-500/10 border border-green-500/20">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                  <span className="text-sm text-green-400 font-mono">{wallet.publicKey?.slice(0, 8)}...{wallet.publicKey?.slice(-4)}</span>
                </div>
                <button onClick={wallet.disconnect} className="text-sm text-gray-500 hover:text-red-400 transition-colors">
                  <X size={14} />
                </button>
              </div>
            ) : (
              <button
                onClick={wallet.connect}
                disabled={wallet.connecting}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-ae-accent text-white text-sm font-semibold hover:bg-ae-accent-bright transition-colors disabled:opacity-50"
              >
                <Wallet size={14} /> {wallet.connecting ? 'Connecting...' : 'Connect Wallet'}
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
              { label: 'Total Escrows', val: stats.total, color: 'text-white', Icon: Package, tip: 'Total number of escrow transactions created on the contract' },
              { label: 'Pending', val: stats.pending, color: 'text-yellow-400', Icon: Clock, tip: 'Escrows awaiting release, dispute, or refund action' },
              { label: 'Released', val: stats.released, color: 'text-green-400', Icon: CheckCircle, tip: 'Successfully completed escrows where funds were released to receiver' },
              { label: 'Disputed', val: stats.disputed, color: 'text-red-400', Icon: AlertTriangle, tip: 'Escrows flagged for dispute resolution by an arbiter' },
              { label: 'Volume', val: `${(stats.volume / 1000).toFixed(1)}K`, color: 'text-ae-accent', Icon: DollarSign, tip: 'Total CSPR volume locked in escrow transactions' },
            ].map((s, i) => (
              <div key={i} className="bg-ae-card/60 border border-ae-border rounded-xl p-5 hover:border-ae-border/80 transition-colors">
                <div className="flex items-center gap-1.5 mb-1">
                  <s.Icon size={14} className="text-gray-500" />
                  <span className="text-sm text-gray-500 uppercase tracking-wider">{s.label}</span>
                  <Tip text={s.tip} />
                </div>
                <div className={`text-2xl font-bold font-mono ${s.color}`}>{s.val}</div>
              </div>
            ))}
          </div>
        )}

        {/* Tab bar + actions */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-1 bg-ae-card/40 rounded-lg p-0.5">
            {([
              { id: 'escrows' as const, label: 'Escrows', Icon: FileText },
              { id: 'agents' as const, label: 'Agents', Icon: Users },
              { id: 'operations' as const, label: 'Operations', Icon: Zap },
            ]).map(t => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-all flex items-center gap-1.5 ${
                  tab === t.id ? 'bg-ae-accent text-white' : 'text-gray-500 hover:text-gray-300'
                }`}
              >
                <t.Icon size={14} /> {t.label}
              </button>
            ))}
          </div>

          {tab === 'escrows' && wallet.connected && (
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-ae-accent text-white text-sm font-semibold hover:bg-ae-accent-bright transition-colors"
            >
              <Send size={14} /> New Escrow
            </button>
          )}
        </div>

        {/* Tab description */}
        <div className="mb-4 px-4 py-3 bg-ae-card/30 border border-ae-border/30 rounded-xl">
          <p className="text-sm text-gray-500">
            <span className="text-gray-400 font-semibold">{TAB_INFO[tab].title}</span> &mdash; {TAB_INFO[tab].desc}
          </p>
        </div>

        {/* ========== ESCROWS TAB ========== */}
        {tab === 'escrows' && (
          <>
            {/* Filter bar */}
            <div className="flex items-center gap-2 mb-4 flex-wrap">
              <Filter size={14} className="text-gray-500" />
              {(['all', 'pending', 'released', 'disputed', 'refunded'] as StatusFilter[]).map(f => {
                const Icon = f !== 'all' ? STATUS_ICON[f] : null
                return (
                  <button
                    key={f}
                    onClick={() => { setFilter(f); setPage(1) }}
                    className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all flex items-center gap-1.5 ${
                      filter === f
                        ? 'bg-ae-accent text-white'
                        : 'bg-ae-card/40 text-gray-500 hover:text-gray-300 border border-ae-border/40'
                    }`}
                  >
                    {Icon && <Icon size={12} />}
                    {f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
                  </button>
                )
              })}
              <span className="ml-auto text-sm text-gray-600 font-mono flex items-center gap-1">
                <Shield size={12} /> Insurance: {feePct}%
              </span>
            </div>

            {error && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 mb-4 text-red-400 text-sm flex items-center gap-2">
                <AlertTriangle size={16} /> {error}
              </div>
            )}

            {/* Escrow list with skeleton */}
            <div className="space-y-2 mb-6">
              {loading ? (
                Array.from({ length: 3 }).map((_, i) => <EscrowSkeleton key={i} />)
              ) : escrows.length === 0 ? (
                <div className="text-center py-16 text-gray-600 text-sm">
                  <Package size={32} className="mx-auto mb-3 text-gray-700" />
                  No escrows found for this filter
                </div>
              ) : (
                escrows.map(esc => {
                  const StatusIcon = STATUS_ICON[esc.status] || Clock
                  return (
                    <div key={esc.service_hash} className="bg-ae-card/40 border border-ae-border/50 rounded-xl p-5 hover:border-ae-border transition-colors group">
                      <div className="flex items-start justify-between gap-4 mb-3">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-sm text-gray-500 font-mono truncate">{esc.service_hash}</span>
                            <button
                              onClick={() => copyHash(esc.service_hash)}
                              className="text-gray-600 hover:text-ae-accent transition-colors opacity-0 group-hover:opacity-100"
                            >
                              <Copy size={12} />
                            </button>
                            {copied === esc.service_hash && <span className="text-sm text-ae-accent">Copied</span>}
                          </div>
                          <div className="flex items-center gap-2 text-sm">
                            <span className="text-gray-400 font-mono truncate max-w-[120px] sm:max-w-[200px]">{esc.sender}</span>
                            <ArrowRight size={12} className="text-gray-600 shrink-0" />
                            <span className="text-gray-400 font-mono truncate max-w-[120px] sm:max-w-[200px]">{esc.receiver}</span>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className={`px-2.5 py-1 rounded text-sm font-semibold uppercase border flex items-center gap-1 ${STATUS_STYLES[esc.status] || ''}`}>
                            <StatusIcon size={12} /> {esc.status}
                          </span>
                        </div>
                      </div>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-5 text-sm text-gray-500">
                          <span><span className="text-white font-mono font-bold">{esc.amount.toLocaleString()}</span> CSPR</span>
                          <span className="flex items-center gap-1">
                            <Clock size={12} /> {esc.ttl >= 86400 ? `${Math.floor(esc.ttl / 86400)}d` : esc.ttl >= 3600 ? `${Math.floor(esc.ttl / 3600)}h` : `${Math.floor(esc.ttl / 60)}m`}
                          </span>
                          <span>{formatAge(esc.created_at)}</span>
                          {esc.deploy_hash && (
                            <a
                              href={`${CSPR_LIVE}/deploy/${esc.deploy_hash}`}
                              target="_blank"
                              rel="noreferrer"
                              className="text-ae-accent hover:text-ae-accent-bright flex items-center gap-1"
                            >
                              On-chain <ExternalLink size={10} />
                            </a>
                          )}
                        </div>

                        {wallet.connected && esc.status === 'pending' && (
                          <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                            <button
                              onClick={() => setActionModal({ action: 'release', escrow: esc })}
                              className="px-2.5 py-1.5 rounded-md bg-green-500/10 text-green-400 text-sm font-medium hover:bg-green-500/20 transition-colors flex items-center gap-1"
                            >
                              <Unlock size={12} /> Release
                            </button>
                            <button
                              onClick={() => setActionModal({ action: 'dispute', escrow: esc })}
                              className="px-2.5 py-1.5 rounded-md bg-red-500/10 text-red-400 text-sm font-medium hover:bg-red-500/20 transition-colors flex items-center gap-1"
                            >
                              <AlertTriangle size={12} /> Dispute
                            </button>
                            <button
                              onClick={() => setActionModal({ action: 'refund', escrow: esc })}
                              className="px-2.5 py-1.5 rounded-md bg-gray-500/10 text-gray-400 text-sm font-medium hover:bg-gray-500/20 transition-colors flex items-center gap-1"
                            >
                              <RotateCcw size={12} /> Refund
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })
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
                <span className="text-sm text-gray-500 font-mono">{page} / {totalPages}</span>
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
              <div className="text-center py-16 text-gray-600 text-sm">
                <Users size={32} className="mx-auto mb-3 text-gray-700" />
                Loading agents...
              </div>
            ) : agents.map((agent, i) => (
              <div key={agent.address}>
                <button
                  onClick={() => setExpandedAgent(expandedAgent === agent.address ? null : agent.address)}
                  className="w-full bg-ae-card/40 border border-ae-border/50 rounded-xl p-5 flex items-center justify-between hover:border-ae-border transition-colors text-left"
                >
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-lg bg-ae-accent/10 flex items-center justify-center text-ae-accent font-bold text-sm">
                      #{i + 1}
                    </div>
                    <div>
                      <div className="text-sm font-mono text-gray-300 truncate max-w-[200px] sm:max-w-[300px]">{agent.address}</div>
                      <div className="text-sm text-gray-500 capitalize flex items-center gap-1">
                        <Shield size={12} /> {agent.role}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-6 text-sm">
                    <div className="text-center">
                      <div className="font-mono font-bold text-white">{agent.total_escrows}</div>
                      <div className="text-sm text-gray-600">escrows</div>
                    </div>
                    <div className="text-center">
                      <div className="font-mono font-bold text-ae-accent">{(agent.total_volume / 1000).toFixed(1)}K</div>
                      <div className="text-sm text-gray-600">volume</div>
                    </div>
                    {expandedAgent === agent.address ? <ChevronUp size={16} className="text-gray-500" /> : <ChevronDown size={16} className="text-gray-500" />}
                  </div>
                </button>
                {expandedAgent === agent.address && <AgentDetail agent={agent} onClose={() => setExpandedAgent(null)} />}
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
                <p className="text-gray-500 mb-2 text-sm">Connect your wallet to interact with escrows</p>
                <p className="text-gray-600 text-sm mb-6 max-w-md mx-auto">
                  You need a Casper Wallet or Signer extension to create and manage escrow transactions. A demo mode is available if no wallet is detected.
                </p>
                <button
                  onClick={wallet.connect}
                  className="px-6 py-3 rounded-xl bg-ae-accent text-white font-semibold hover:bg-ae-accent-bright transition-colors text-sm"
                >
                  Connect Wallet
                </button>
              </div>
            ) : (
              <>
                <div className="bg-ae-card/60 border border-ae-border rounded-xl p-6">
                  <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2"><Zap size={14} className="text-ae-accent" /> Quick Actions</h3>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <button
                      onClick={() => setShowCreate(true)}
                      className="p-5 rounded-xl bg-ae-accent/10 border border-ae-accent/20 hover:border-ae-accent/40 transition-colors text-left"
                    >
                      <Send size={20} className="text-ae-accent mb-3" />
                      <div className="text-sm font-semibold text-white">Create Escrow</div>
                      <div className="text-sm text-gray-500 mt-1">Lock CSPR with insurance fee deduction. Funds are held until release, dispute, or TTL expiry.</div>
                    </button>
                    <a
                      href={`${CSPR_LIVE}/contract/${CONTRACT_HASH}`}
                      target="_blank"
                      rel="noreferrer"
                      className="p-5 rounded-xl bg-ae-card/60 border border-ae-border hover:border-ae-border/80 transition-colors text-left"
                    >
                      <ExternalLink size={20} className="text-gray-400 mb-3" />
                      <div className="text-sm font-semibold text-white">View Contract</div>
                      <div className="text-sm text-gray-500 mt-1">Inspect the deployed escrow smart contract on Casper testnet explorer.</div>
                    </a>
                    <div className="p-5 rounded-xl bg-ae-card/60 border border-ae-border">
                      <Lock size={20} className="text-yellow-400 mb-3" />
                      <div className="text-sm font-semibold text-white">Insurance Pool</div>
                      <div className="text-sm text-gray-500 mt-1">{feePct}% fee on every escrow funds the dispute resolution insurance pool.</div>
                    </div>
                  </div>
                </div>

                <div className="bg-ae-card/60 border border-ae-border rounded-xl p-6">
                  <h3 className="text-sm font-bold text-white mb-4">Connected Account</h3>
                  <div className="space-y-3 text-sm">
                    <div className="flex justify-between">
                      <span className="text-gray-500">Public Key</span>
                      <span className="text-gray-300 font-mono truncate max-w-[280px]">{wallet.publicKey}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">Network</span>
                      <span className="text-yellow-400 flex items-center gap-1"><Activity size={12} /> Casper Testnet</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-500">Contract</span>
                      <a href={`${CSPR_LIVE}/contract/${CONTRACT_HASH}`} target="_blank" rel="noreferrer" className="text-ae-accent font-mono hover:text-ae-accent-bright flex items-center gap-1">
                        {CONTRACT_HASH.slice(0, 12)}... <ExternalLink size={10} />
                      </a>
                    </div>
                  </div>
                </div>

                <div className="bg-ae-card/60 border border-ae-border rounded-xl p-6">
                  <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2"><TrendingUp size={14} className="text-ae-accent" /> Escrow Lifecycle</h3>
                  <p className="text-sm text-gray-500 mb-4">
                    Every escrow follows a deterministic workflow. Funds are locked on creation, held during the service period, and resolved through one of three outcomes.
                  </p>
                  <div className="flex items-center gap-2 flex-wrap">
                    {[
                      { step: '1', label: 'Create', desc: 'Lock funds + insurance fee', Icon: Lock },
                      { step: '2', label: 'Pending', desc: 'Service delivery period', Icon: Clock },
                      { step: '3', label: 'Resolve', desc: 'Release / Dispute / Refund', Icon: CheckCircle },
                    ].map((s, i) => (
                      <div key={i} className="flex items-center gap-2">
                        {i > 0 && <ArrowRight size={14} className="text-gray-600" />}
                        <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-ae-bg/60 border border-ae-border/40">
                          <span className="w-6 h-6 rounded-full bg-ae-accent/20 text-ae-accent flex items-center justify-center text-sm font-bold"><s.Icon size={12} /></span>
                          <div>
                            <div className="font-semibold text-white text-sm">{s.label}</div>
                            <div className="text-gray-500 text-sm">{s.desc}</div>
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
            <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm ${
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
