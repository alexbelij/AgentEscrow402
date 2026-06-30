import { useState, useRef, useEffect, useCallback } from 'react'
import { Lock, Unlock, AlertTriangle, Search, Clock, Coins, Shield, Activity, Wallet, LogOut } from 'lucide-react'
import { createEscrow, releaseEscrow, refundEscrow, disputeEscrow, lookupEscrow, getHealth } from '../lib/api'
import type { EscrowRecord } from '../lib/api'
import { connectWallet, disconnectWallet, shortKey } from '../lib/wallet'
import type { WalletState } from '../lib/wallet'

interface LogLine { time: string; text: string; type: 'info' | 'success' | 'warn' | 'error' | 'hash' }

function shortAddr(a: string) { return a.length > 16 ? a.slice(0, 8) + '...' + a.slice(-6) : a }

function hashForDisplay(h: string): string {
  return h.length > 20 ? h.slice(0, 12) + '...' : h
}

export default function Dashboard() {
  const [escrows, setEscrows] = useState<EscrowRecord[]>([])
  const [receiver, setReceiver] = useState('01def7890123abcd01ef56789012345678901234567890abcdef0123456789ab')
  const [amount, setAmount] = useState('50')
  const [ttl, setTtl] = useState('300')
  const [running, setRunning] = useState(false)
  const [log, setLog] = useState<LogLine[]>([])
  const [lookupHash, setLookupHash] = useState('')
  const [lookupResult, setLookupResult] = useState<string | null>(null)
  const [wallet, setWallet] = useState<WalletState>({ connected: false, publicKey: null, accountHash: null, simulated: false })
  const [chainStatus, setChainStatus] = useState<string>('connecting...')
  const [actionRunning, setActionRunning] = useState<string | null>(null)
  const logRef = useRef<HTMLDivElement>(null)

  const addLine = useCallback((l: LogLine) => {
    setLog(p => [...p, l])
    setTimeout(() => logRef.current?.scrollTo({ top: 9999, behavior: 'smooth' }), 50)
  }, [])

  useEffect(() => {
    getHealth()
      .then(h => setChainStatus(`${h.chain}${h.sandbox ? ' (sandbox)' : ''}`))
      .catch(() => setChainStatus('offline'))
  }, [])

  const handleConnect = async () => {
    if (wallet.connected) {
      setWallet(disconnectWallet())
      setEscrows([])
      return
    }
    const state = await connectWallet()
    setWallet(state)
  }

  const handleCreate = async () => {
    if (running || !wallet.connected) return
    setRunning(true)
    setLog([])

    const ts = () => (performance.now() / 1000).toFixed(3)
    addLine({ time: ts(), text: `Creating escrow: ${amount} CSPR to ${shortAddr(receiver)}`, type: 'info' })
    addLine({ time: ts(), text: `TTL: ${ttl}s | Sender: ${shortKey(wallet.publicKey || '')}`, type: 'info' })

    try {
      const serviceHash = Array.from(crypto.getRandomValues(new Uint8Array(32)))
        .map(b => b.toString(16).padStart(2, '0')).join('')

      addLine({ time: ts(), text: `Service hash: ${hashForDisplay(serviceHash)}`, type: 'hash' })
      addLine({ time: ts(), text: 'Sending to API...', type: 'info' })

      const record = await createEscrow({
        receiver,
        amount: parseInt(amount),
        service_hash: serviceHash,
        ttl: parseInt(ttl),
      }, wallet.accountHash || undefined)

      addLine({ time: ts(), text: `Status: ${record.status}`, type: 'success' })
      addLine({ time: ts(), text: `Escrow created: ${record.amount} CSPR locked`, type: 'success' })

      setEscrows(p => [record, ...p])
    } catch (err) {
      addLine({ time: ts(), text: `Error: ${err instanceof Error ? err.message : String(err)}`, type: 'error' })
    }

    setRunning(false)
  }

  const handleAction = async (action: 'release' | 'refund' | 'dispute', hash: string) => {
    if (actionRunning) return
    setActionRunning(hash)
    try {
      let updated: EscrowRecord
      if (action === 'release') {
        updated = await releaseEscrow(hash)
      } else if (action === 'refund') {
        updated = await refundEscrow(hash)
      } else {
        const reasonHash = Array.from(crypto.getRandomValues(new Uint8Array(32)))
          .map(b => b.toString(16).padStart(2, '0')).join('')
        updated = await disputeEscrow(hash, reasonHash)
      }
      setEscrows(p => p.map(e => e.service_hash === hash ? updated : e))
      addLine({ time: (performance.now() / 1000).toFixed(3), text: `${action}: ${hashForDisplay(hash)} -> ${updated.status}`, type: 'success' })
    } catch (err) {
      addLine({ time: (performance.now() / 1000).toFixed(3), text: `${action} failed: ${err instanceof Error ? err.message : String(err)}`, type: 'error' })
    }
    setActionRunning(null)
  }

  const handleLookup = async () => {
    if (!lookupHash.trim()) return
    try {
      const rec = await lookupEscrow(lookupHash.trim())
      setLookupResult(`Found | ${rec.amount} CSPR | Status: ${rec.status.toUpperCase()} | Sender: ${shortAddr(rec.sender)}`)
    } catch {
      setLookupResult('No escrow found for this hash.')
    }
  }

  const statusColor = (s: string) => {
    switch (s) {
      case 'locked': case 'pending': return 'bg-yellow-500/10 text-yellow-400'
      case 'released': return 'bg-green-500/10 text-green-400'
      case 'refunded': return 'bg-blue-500/10 text-blue-400'
      case 'disputed': return 'bg-red-500/10 text-red-400'
      default: return 'bg-ae-gray/10 text-ae-gray'
    }
  }

  const totalLocked = escrows.filter(e => e.status === 'locked' || e.status === 'pending').reduce((s, e) => s + e.amount, 0)
  const disputes = escrows.filter(e => e.status === 'disputed').length

  return (
    <div className="pt-20 pb-16">
      <div className="ae-section">
        {/* Header */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-8">
          <div>
            <h1 className="text-2xl font-bold">Agent<span className="ae-gradient-text">Escrow</span> Dashboard</h1>
            <p className="text-sm text-ae-gray mt-1">Create, track, and manage escrow transactions on Casper testnet.</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-xs">
              <span className={`w-2 h-2 rounded-full ${chainStatus === 'offline' ? 'bg-red-500' : 'bg-green-500 animate-pulse'}`} />
              <span className="text-ae-gray font-mono">{chainStatus}</span>
            </div>
            <button onClick={handleConnect}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                wallet.connected
                  ? 'bg-ae-accent/10 text-ae-accent border border-ae-accent/30 hover:bg-ae-accent/20'
                  : 'bg-ae-accent text-white hover:bg-ae-accent/90'
              }`}>
              {wallet.connected ? (
                <><LogOut size={12} /> {shortKey(wallet.publicKey || '')}{wallet.simulated ? ' (demo)' : ''}</>
              ) : (
                <><Wallet size={12} /> Connect Wallet</>
              )}
            </button>
          </div>
        </div>

        {!wallet.connected && (
          <div className="ae-card !p-6 text-center mb-8">
            <Wallet size={32} className="mx-auto text-ae-accent mb-3" />
            <h3 className="text-lg font-semibold text-white mb-2">Connect Your Wallet</h3>
            <p className="text-sm text-ae-gray mb-4">
              Connect a Casper Wallet to interact with the escrow protocol.
              {' '}No extension? A demo account will be provided.
            </p>
            <button onClick={handleConnect}
              className="ae-btn-primary mx-auto !text-sm">
              <Wallet size={14} /> Connect Wallet
            </button>
          </div>
        )}

        {wallet.connected && (
          <>
            {/* Stats */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
              {[
                { label: 'Total Escrows', value: escrows.length, icon: Activity, color: 'text-ae-accent' },
                { label: 'Value Locked', value: `${totalLocked} CSPR`, icon: Coins, color: 'text-ae-cyan' },
                { label: 'Active Disputes', value: disputes, icon: AlertTriangle, color: 'text-yellow-400' },
                { label: 'Wallet', value: wallet.simulated ? 'Demo' : 'Live', icon: Shield, color: 'text-ae-green' },
              ].map(s => (
                <div key={s.label} className="ae-card flex items-center gap-3">
                  <div className="ae-icon !w-10 !h-10">
                    <s.icon size={18} className={s.color} />
                  </div>
                  <div>
                    <div className="text-xl font-bold text-white">{s.value}</div>
                    <div className="text-[11px] text-ae-gray">{s.label}</div>
                  </div>
                </div>
              ))}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
              {/* Create Escrow */}
              <div className="ae-card !p-5 space-y-3">
                <h3 className="font-semibold text-white flex items-center gap-2"><Lock size={16} className="text-ae-accent" /> Create Escrow</h3>
                <div>
                  <label htmlFor="ae-receiver" className="text-xs text-ae-gray mb-1 block">Receiver (account hash)</label>
                  <input id="ae-receiver" value={receiver} onChange={e => setReceiver(e.target.value)}
                    className="w-full bg-ae-bg border border-ae-border rounded-lg px-3 py-2 text-xs font-mono text-white focus:border-ae-accent/50 focus:outline-none" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="ae-amount" className="text-xs text-ae-gray mb-1 block">Amount (CSPR)</label>
                    <input id="ae-amount" type="number" value={amount} onChange={e => setAmount(e.target.value)}
                      className="w-full bg-ae-bg border border-ae-border rounded-lg px-3 py-2 text-xs font-mono text-white focus:border-ae-accent/50 focus:outline-none" />
                  </div>
                  <div>
                    <label htmlFor="ae-ttl" className="text-xs text-ae-gray mb-1 block">TTL (seconds)</label>
                    <input id="ae-ttl" type="number" value={ttl} onChange={e => setTtl(e.target.value)}
                      className="w-full bg-ae-bg border border-ae-border rounded-lg px-3 py-2 text-xs font-mono text-white focus:border-ae-accent/50 focus:outline-none" />
                  </div>
                </div>
                <button onClick={handleCreate} disabled={running}
                  className="ae-btn-primary w-full justify-center !text-sm disabled:opacity-50 disabled:cursor-not-allowed">
                  {running ? 'Locking...' : 'Lock Funds in Escrow'}
                </button>
              </div>

              {/* Terminal */}
              <div className="ae-card !p-0 overflow-hidden flex flex-col">
                <div className="flex items-center gap-2 px-4 py-2 border-b border-ae-border bg-ae-bg/50">
                  <div className="flex gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-ae-accent/60" />
                    <span className="w-2 h-2 rounded-full bg-yellow-500/60" />
                    <span className="w-2 h-2 rounded-full bg-green-500/60" />
                  </div>
                  <span className="text-[10px] font-mono text-ae-gray-dark">escrow engine</span>
                </div>
                <div ref={logRef} className="flex-1 p-3 overflow-y-auto font-mono text-[11px] space-y-0.5 min-h-[200px] max-h-[280px] bg-ae-bg">
                  {log.length === 0 && <div className="text-ae-gray-dark"><span className="animate-pulse">_</span> Ready...</div>}
                  {log.map((l, i) => (
                    <div key={i} className="flex gap-2">
                      <span className="text-ae-gray-dark shrink-0">[{l.time}]</span>
                      <span className={
                        l.type === 'success' ? 'text-green-400' :
                        l.type === 'warn' ? 'text-yellow-400' :
                        l.type === 'error' ? 'text-red-400' :
                        l.type === 'hash' ? 'text-ae-accent-bright' :
                        'text-ae-gray'
                      }>{l.text}</span>
                    </div>
                  ))}
                  {running && <div className="text-ae-gray-dark animate-pulse">_</div>}
                </div>
              </div>
            </div>

            {/* Lookup */}
            <div className="ae-card !p-5 mb-8">
              <h3 className="font-semibold text-white flex items-center gap-2 mb-3"><Search size={16} className="text-ae-accent" /> Lookup Escrow</h3>
              <div className="flex gap-3">
                <input value={lookupHash} onChange={e => setLookupHash(e.target.value)} placeholder="Service hash (64 chars)..."
                  className="flex-1 bg-ae-bg border border-ae-border rounded-lg px-3 py-2 text-sm font-mono text-white focus:border-ae-accent/50 focus:outline-none" />
                <button onClick={handleLookup} className="ae-btn-primary !text-sm">Lookup</button>
              </div>
              {lookupResult && (
                <div className={`mt-3 text-sm font-mono ${lookupResult.startsWith('Found') ? 'text-green-400' : 'text-red-400'}`}>{lookupResult}</div>
              )}
            </div>

            {/* Escrow table */}
            <div className="ae-card !p-0 overflow-hidden">
              <div className="px-5 py-4 border-b border-ae-border flex items-center justify-between">
                <h3 className="font-semibold text-white">Escrow Explorer</h3>
                <span className="text-xs text-ae-gray-dark">{escrows.length} transactions</span>
              </div>
              {escrows.length === 0 ? (
                <div className="p-8 text-center text-sm text-ae-gray">No escrows yet. Create one above to get started.</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-ae-border text-ae-gray text-xs uppercase tracking-wider">
                        <th className="text-left py-3 px-5 font-medium">Hash</th>
                        <th className="text-left py-3 px-5 font-medium">Amount</th>
                        <th className="text-left py-3 px-5 font-medium">Sender</th>
                        <th className="text-left py-3 px-5 font-medium">Receiver</th>
                        <th className="text-left py-3 px-5 font-medium">Status</th>
                        <th className="text-left py-3 px-5 font-medium">TTL</th>
                        <th className="text-left py-3 px-5 font-medium">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {escrows.map(e => (
                        <tr key={e.service_hash} className="border-b border-ae-border/50 hover:bg-ae-accent/[0.02] transition-colors">
                          <td className="py-3 px-5 font-mono text-xs text-ae-accent">{hashForDisplay(e.service_hash)}</td>
                          <td className="py-3 px-5 text-xs text-white font-semibold">{e.amount} CSPR</td>
                          <td className="py-3 px-5 font-mono text-xs text-ae-gray">{shortAddr(e.sender)}</td>
                          <td className="py-3 px-5 font-mono text-xs text-ae-gray">{shortAddr(e.receiver)}</td>
                          <td className="py-3 px-5">
                            <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${statusColor(e.status)}`}>
                              {e.status.charAt(0).toUpperCase() + e.status.slice(1)}
                            </span>
                          </td>
                          <td className="py-3 px-5 text-xs text-ae-gray-dark flex items-center gap-1"><Clock size={12} /> {e.ttl}s</td>
                          <td className="py-3 px-5">
                            {(e.status === 'locked' || e.status === 'pending') ? (
                              <div className="flex gap-1.5">
                                <button
                                  onClick={() => handleAction('release', e.service_hash)}
                                  disabled={actionRunning === e.service_hash}
                                  className="text-[10px] px-2 py-1 rounded bg-green-500/10 text-green-400 hover:bg-green-500/20 cursor-pointer transition-colors flex items-center gap-1 disabled:opacity-50">
                                  <Unlock size={10} /> Release
                                </button>
                                <button
                                  onClick={() => handleAction('dispute', e.service_hash)}
                                  disabled={actionRunning === e.service_hash}
                                  className="text-[10px] px-2 py-1 rounded bg-red-500/10 text-red-400 hover:bg-red-500/20 cursor-pointer transition-colors flex items-center gap-1 disabled:opacity-50">
                                  <AlertTriangle size={10} /> Dispute
                                </button>
                              </div>
                            ) : (
                              <span className="text-[10px] text-ae-gray-dark">completed</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
