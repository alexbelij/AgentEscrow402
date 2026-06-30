import { useState, useEffect } from 'react'
import { Lock, Unlock, AlertTriangle, Wallet, LogOut, Plus, Loader2, Clock, CheckCircle, ArrowUpRight } from 'lucide-react'
import { createEscrow, releaseEscrow, refundEscrow, disputeEscrow, lookupEscrow, getHealth } from '../lib/api'
import type { EscrowRecord } from '../lib/api'
import { connectWallet, disconnectWallet, shortKey } from '../lib/wallet'
import type { WalletState } from '../lib/wallet'

const statusColors: Record<string, string> = {
  LOCKED: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  RELEASED: 'bg-green-500/10 text-green-400 border-green-500/20',
  REFUNDED: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  DISPUTED: 'bg-red-500/10 text-red-400 border-red-500/20',
  EXPIRED: 'bg-gray-500/10 text-gray-400 border-gray-500/20',
}

export default function Dashboard() {
  const [escrows, setEscrows] = useState<EscrowRecord[]>([])
  const [wallet, setWallet] = useState<WalletState>({ connected: false, publicKey: null, accountHash: null, simulated: false })
  const [chain, setChain] = useState('connecting...')
  const [receiver, setReceiver] = useState('agent-beta')
  const [amount, setAmount] = useState('50')
  const [ttl, setTtl] = useState('3600')
  const [serviceHash, setServiceHash] = useState('')
  const [creating, setCreating] = useState(false)
  const [selected, setSelected] = useState<EscrowRecord | null>(null)
  const [actioning, setActioning] = useState(false)
  const [lookupHash, setLookupHash] = useState('')
  const [lookupResult, setLookupResult] = useState<string | null>(null)

  useEffect(() => {
    getHealth().then(h => setChain(h.status === 'ok' ? 'casper-test' : 'offline')).catch(() => setChain('offline'))
  }, [])

  const handleConnect = async () => {
    if (wallet.connected) { setWallet(disconnectWallet()); setEscrows([]); return }
    setWallet(await connectWallet())
  }

  const handleCreate = async () => {
    setCreating(true)
    try {
      const e = await createEscrow({
        receiver,
        amount: Number(amount),
        ttl: Number(ttl),
        service_hash: serviceHash || `0x${Math.random().toString(16).slice(2, 18)}`,
      }, wallet.publicKey || undefined)
      setEscrows(prev => [e, ...prev])
      setSelected(e)
    } catch {}
    setCreating(false)
  }

  const handleAction = async (action: 'release' | 'refund' | 'dispute') => {
    if (!selected || actioning) return
    setActioning(true)
    try {
      let updated: EscrowRecord
      if (action === 'release') updated = await releaseEscrow(selected.service_hash)
      else if (action === 'refund') updated = await refundEscrow(selected.service_hash)
      else updated = await disputeEscrow(selected.service_hash, 'user_dispute')
      setSelected(updated)
      setEscrows(prev => prev.map(e => e.service_hash === updated.service_hash ? updated : e))
    } catch {}
    setActioning(false)
  }

  const handleLookup = async () => {
    try {
      const e = await lookupEscrow(lookupHash.trim())
      setLookupResult(`Found | ${e.service_hash} | ${e.amount} CSPR | ${e.status}`)
      setSelected(e)
    } catch {
      setLookupResult('Escrow not found.')
    }
  }

  const locked = escrows.filter(e => e.status === 'LOCKED').length
  const released = escrows.filter(e => e.status === 'RELEASED').length
  const totalValue = escrows.reduce((a, e) => a + e.amount, 0)

  return (
    <div className="min-h-screen bg-ae-bg pt-20">
      <div className="ae-section py-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-8">
          <div>
            <h1 className="text-2xl font-extrabold text-white">Escrow Dashboard</h1>
            <p className="text-gray-500 text-sm mt-1">Create, manage, and inspect payment escrows</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-ae-card border border-ae-border text-xs">
              <span className={`w-2 h-2 rounded-full ${chain === 'casper-test' ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className="text-gray-400 font-mono">{chain}</span>
            </div>
            <button onClick={handleConnect} className={`inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all ${
              wallet.connected ? 'bg-purple-500/10 text-purple-300 border border-purple-500/20 hover:bg-purple-500/20' : 'bg-ae-accent text-white hover:bg-ae-accent-bright'
            }`}>
              {wallet.connected ? <LogOut className="w-4 h-4" /> : <Wallet className="w-4 h-4" />}
              {wallet.connected ? shortKey(wallet.publicKey || '') : 'Connect Wallet'}
            </button>
          </div>
        </div>

        {!wallet.connected ? (
          <div className="bg-ae-card rounded-2xl border border-ae-border p-16 text-center">
            <Wallet className="w-12 h-12 text-gray-700 mx-auto mb-4" />
            <h2 className="text-xl font-bold text-white mb-2">Connect wallet to begin</h2>
            <p className="text-gray-500 mb-6">Connect a Casper wallet to create and manage escrows.</p>
            <button onClick={handleConnect} className="inline-flex items-center gap-2 px-8 py-3 bg-ae-accent text-white font-semibold rounded-xl hover:bg-ae-accent-bright transition-colors">
              <Wallet className="w-4 h-4" /> Connect Wallet
            </button>
          </div>
        ) : (
          <>
            {/* Stats */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
              {[
                { icon: Lock, label: 'Active Escrows', val: String(locked), color: 'text-yellow-400 bg-yellow-500/10' },
                { icon: CheckCircle, label: 'Released', val: String(released), color: 'text-green-400 bg-green-500/10' },
                { icon: ArrowUpRight, label: 'Total Value', val: `${totalValue} CSPR`, color: 'text-purple-400 bg-purple-500/10' },
                { icon: Clock, label: 'Total', val: String(escrows.length), color: 'text-blue-400 bg-blue-500/10' },
              ].map((s, i) => (
                <div key={i} className="bg-ae-card rounded-xl border border-ae-border p-5">
                  <div className={`w-9 h-9 rounded-lg ${s.color} flex items-center justify-center mb-3`}>
                    <s.icon className="w-4 h-4" />
                  </div>
                  <p className="text-2xl font-bold text-white">{s.val}</p>
                  <p className="text-xs text-gray-500 font-medium">{s.label}</p>
                </div>
              ))}
            </div>

            <div className="grid lg:grid-cols-5 gap-6">
              {/* Left: Create + Lookup */}
              <div className="lg:col-span-2 space-y-6">
                {/* Create escrow */}
                <div className="bg-ae-card rounded-2xl border border-ae-border p-6">
                  <h3 className="text-white font-bold mb-4 flex items-center gap-2"><Plus className="w-4 h-4 text-purple-400" /> New Escrow</h3>
                  <div className="space-y-3">
                    {[
                      { l: 'Receiver', v: receiver, s: setReceiver, ph: 'agent-beta' },
                      { l: 'Amount (CSPR)', v: amount, s: setAmount, ph: '50' },
                      { l: 'TTL (seconds)', v: ttl, s: setTtl, ph: '3600' },
                      { l: 'Service Hash', v: serviceHash, s: setServiceHash, ph: 'auto-generated if empty' },
                    ].map((f, i) => (
                      <div key={i}>
                        <label className="text-xs text-gray-600 font-mono mb-1 block">{f.l}</label>
                        <input value={f.v} onChange={e => f.s(e.target.value)} placeholder={f.ph} className="w-full px-3 py-2 bg-ae-bg border border-ae-border rounded-lg text-sm text-white font-mono focus:outline-none focus:border-purple-500/50" />
                      </div>
                    ))}
                    <button onClick={handleCreate} disabled={creating} className="w-full mt-2 inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-ae-accent text-white text-sm font-semibold rounded-lg hover:bg-ae-accent-bright disabled:opacity-50 transition-all">
                      {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Lock className="w-4 h-4" />}
                      {creating ? 'Creating...' : 'Create Escrow'}
                    </button>
                  </div>
                </div>

                {/* Lookup */}
                <div className="bg-ae-card rounded-2xl border border-ae-border p-6">
                  <h3 className="text-white font-bold mb-3 text-sm">Lookup Escrow</h3>
                  <div className="flex gap-2">
                    <input value={lookupHash} onChange={e => setLookupHash(e.target.value)} placeholder="Service hash" className="flex-1 px-3 py-2 bg-ae-bg border border-ae-border rounded-lg text-sm text-white font-mono focus:outline-none focus:border-purple-500/50" />
                    <button onClick={handleLookup} className="px-3 py-2 bg-ae-bg border border-ae-border rounded-lg text-gray-400 hover:text-white hover:border-purple-500/50 transition-colors">
                      <ArrowUpRight className="w-4 h-4" />
                    </button>
                  </div>
                  {lookupResult && <p className="mt-2 text-xs font-mono text-purple-300">{lookupResult}</p>}
                </div>
              </div>

              {/* Right: Escrow list / detail */}
              <div className="lg:col-span-3 bg-ae-card rounded-2xl border border-ae-border p-6">
                {selected ? (
                  <div>
                    <button onClick={() => setSelected(null)} className="text-xs text-gray-500 hover:text-gray-300 mb-4">&larr; Back to list</button>
                    <div className="bg-ae-bg rounded-xl p-5 font-mono text-xs space-y-1.5 mb-4 overflow-x-auto">
                      <p className="text-gray-400">service_hash: <span className="text-purple-400 break-all">{selected.service_hash}</span></p>
                      <p className="text-gray-400">sender: <span className="text-white">{selected.sender}</span></p>
                      <p className="text-gray-400">receiver: <span className="text-white">{selected.receiver}</span></p>
                      <p className="text-gray-400">amount: <span className="text-cyan-400">{selected.amount} CSPR</span></p>
                      <p className="text-gray-400">status: <span className={selected.status === 'RELEASED' ? 'text-green-400' : selected.status === 'LOCKED' ? 'text-yellow-400' : 'text-red-400'}>{selected.status}</span></p>
                      <p className="text-gray-400">ttl: <span className="text-gray-300">{selected.ttl}s</span></p>
                      <p className="text-gray-400">created_at: <span className="text-gray-300">{new Date(selected.created_at * 1000).toISOString()}</span></p>
                    </div>
                    {selected.status === 'LOCKED' && (
                      <div className="flex gap-2">
                        <button onClick={() => handleAction('release')} disabled={actioning} className="flex-1 px-4 py-2 bg-green-600/20 text-green-400 text-sm font-semibold rounded-lg hover:bg-green-600/30 disabled:opacity-50 transition-all flex items-center justify-center gap-1">
                          <Unlock className="w-3.5 h-3.5" /> Release
                        </button>
                        <button onClick={() => handleAction('refund')} disabled={actioning} className="flex-1 px-4 py-2 bg-blue-600/20 text-blue-400 text-sm font-semibold rounded-lg hover:bg-blue-600/30 disabled:opacity-50 transition-all text-center">
                          Refund
                        </button>
                        <button onClick={() => handleAction('dispute')} disabled={actioning} className="flex-1 px-4 py-2 bg-red-600/20 text-red-400 text-sm font-semibold rounded-lg hover:bg-red-600/30 disabled:opacity-50 transition-all flex items-center justify-center gap-1">
                          <AlertTriangle className="w-3.5 h-3.5" /> Dispute
                        </button>
                      </div>
                    )}
                  </div>
                ) : (
                  <>
                    <h3 className="text-white font-bold mb-4 flex items-center gap-2"><Lock className="w-4 h-4 text-purple-400" /> Escrows</h3>
                    <div className="space-y-2 max-h-96 overflow-y-auto">
                      {escrows.length === 0 ? (
                        <p className="text-gray-600 text-sm text-center py-8">No escrows yet. Create one to get started.</p>
                      ) : escrows.map((e, i) => (
                        <button key={i} onClick={() => setSelected(e)} className="w-full flex items-center justify-between p-3 rounded-lg bg-ae-bg hover:bg-ae-bg/80 transition-colors text-left border border-ae-border/50">
                          <div className="min-w-0">
                            <p className="font-mono text-xs text-gray-300 truncate">{e.service_hash}</p>
                            <p className="text-xs text-gray-600">{e.sender} → {e.receiver} | {e.amount} CSPR</p>
                          </div>
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold border shrink-0 ml-2 ${statusColors[e.status] || 'text-gray-400'}`}>
                            {e.status}
                          </span>
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
