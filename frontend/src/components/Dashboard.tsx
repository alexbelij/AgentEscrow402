import { useState, useRef } from 'react'
import { Lock, Unlock, AlertTriangle, Search, Clock, Coins, Shield, Activity } from 'lucide-react'

interface Escrow {
  id: string
  sender: string
  receiver: string
  amount: number
  status: 'locked' | 'released' | 'refunded' | 'disputed'
  ttl: number
  created: string
  serviceHash: string
}

interface LogLine { time: string; text: string; type: 'info' | 'success' | 'warn' | 'hash' }

function shortAddr(a: string) { return a.slice(0, 8) + '...' + a.slice(-6) }

const DEMO_ESCROWS: Escrow[] = [
  { id: 'esc-001', sender: '01abc3f2d8e91a4b', receiver: '01def7890123abcd', amount: 50, status: 'locked', ttl: 300, created: '2026-06-29T12:00:00Z', serviceHash: '5dd33e8e7978...' },
  { id: 'esc-002', sender: '01fed321abc098ef', receiver: '01abc3f2d8e91a4b', amount: 120, status: 'released', ttl: 600, created: '2026-06-29T10:30:00Z', serviceHash: 'a1b2c3d4e5f6...' },
  { id: 'esc-003', sender: '019876543210abcd', receiver: '01abcdef01234567', amount: 200, status: 'disputed', ttl: 900, created: '2026-06-28T18:00:00Z', serviceHash: 'deadbeefcafe...' },
]

export default function Dashboard() {
  const [escrows, setEscrows] = useState<Escrow[]>(DEMO_ESCROWS)
  const [receiver, setReceiver] = useState('01def7890123abcd01ef56789012345678')
  const [amount, setAmount] = useState('50')
  const [ttl, setTtl] = useState('300')
  const [running, setRunning] = useState(false)
  const [log, setLog] = useState<LogLine[]>([])
  const [lookupId, setLookupId] = useState('')
  const [lookupResult, setLookupResult] = useState<string | null>(null)
  const logRef = useRef<HTMLDivElement>(null)

  const addLine = (l: LogLine, d: number) =>
    new Promise<void>(r => setTimeout(() => { setLog(p => [...p, l]); logRef.current?.scrollTo({ top: 9999, behavior: 'smooth' }); r() }, d))

  const createEscrow = async () => {
    if (running) return
    setRunning(true); setLog([])

    await addLine({ time: '0.000', text: `Creating escrow: ${amount} CSPR → ${shortAddr(receiver)}`, type: 'info' }, 200)
    await addLine({ time: '0.001', text: `TTL: ${ttl}s`, type: 'info' }, 200)
    await addLine({ time: '0.010', text: 'Building deploy...', type: 'info' }, 400)
    await addLine({ time: '0.250', text: 'Signing with sender key...', type: 'info' }, 500)
    await addLine({ time: '0.500', text: 'Submitting to Casper testnet...', type: 'info' }, 600)
    const fakeHash = Math.random().toString(16).slice(2, 18)
    await addLine({ time: '2.100', text: `Deploy hash: 0x${fakeHash}`, type: 'hash' }, 1200)
    await addLine({ time: '4.500', text: `Escrow locked: ${amount} CSPR`, type: 'success' }, 800)
    await addLine({ time: '4.510', text: `TTL countdown started (${ttl}s)`, type: 'warn' }, 200)

    const newEscrow: Escrow = {
      id: `esc-${String(escrows.length + 1).padStart(3, '0')}`,
      sender: '01' + Math.random().toString(16).slice(2, 18),
      receiver,
      amount: parseInt(amount),
      status: 'locked',
      ttl: parseInt(ttl),
      created: new Date().toISOString(),
      serviceHash: fakeHash.slice(0, 12) + '...',
    }
    setEscrows(p => [newEscrow, ...p])
    setRunning(false)
  }

  const lookup = () => {
    const found = escrows.find(e => e.id === lookupId || e.serviceHash.startsWith(lookupId))
    setLookupResult(found
      ? `✓ ${found.id} | ${found.amount} CSPR | Status: ${found.status.toUpperCase()}`
      : '✗ No escrow found.')
  }

  const statusColor = (s: string) => {
    switch (s) {
      case 'locked': return 'bg-yellow-500/10 text-yellow-400'
      case 'released': return 'bg-green-500/10 text-green-400'
      case 'refunded': return 'bg-blue-500/10 text-blue-400'
      case 'disputed': return 'bg-red-500/10 text-red-400'
      default: return 'bg-ae-gray/10 text-ae-gray'
    }
  }

  const totalLocked = escrows.filter(e => e.status === 'locked').reduce((s, e) => s + e.amount, 0)
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
          <div className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            <span className="text-ae-gray font-mono">casper-test</span>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
          {[
            { label: 'Total Escrows', value: escrows.length, icon: Activity, color: 'text-ae-accent' },
            { label: 'Value Locked', value: `${totalLocked} CSPR`, icon: Coins, color: 'text-ae-cyan' },
            { label: 'Active Disputes', value: disputes, icon: AlertTriangle, color: 'text-yellow-400' },
            { label: 'Insurance Pool', value: '12.5 CSPR', icon: Shield, color: 'text-ae-green' },
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
            <button onClick={createEscrow} disabled={running}
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
              {log.length === 0 && <div className="text-ae-gray-dark"><span className="animate-pulse">▌</span> Ready...</div>}
              {log.map((l, i) => (
                <div key={i} className="flex gap-2">
                  <span className="text-ae-gray-dark shrink-0">[{l.time}]</span>
                  <span className={
                    l.type === 'success' ? 'text-green-400' :
                    l.type === 'warn' ? 'text-yellow-400' :
                    l.type === 'hash' ? 'text-ae-accent-bright' :
                    'text-ae-gray'
                  }>{l.text}</span>
                </div>
              ))}
              {running && <div className="text-ae-gray-dark animate-pulse">▌</div>}
            </div>
          </div>
        </div>

        {/* Lookup */}
        <div className="ae-card !p-5 mb-8">
          <h3 className="font-semibold text-white flex items-center gap-2 mb-3"><Search size={16} className="text-ae-accent" /> Lookup Escrow</h3>
          <div className="flex gap-3">
            <input value={lookupId} onChange={e => setLookupId(e.target.value)} placeholder="Escrow ID or service hash..."
              className="flex-1 bg-ae-bg border border-ae-border rounded-lg px-3 py-2 text-sm font-mono text-white focus:border-ae-accent/50 focus:outline-none" />
            <button onClick={lookup} className="ae-btn-primary !text-sm">Lookup</button>
          </div>
          {lookupResult && (
            <div className={`mt-3 text-sm font-mono ${lookupResult.startsWith('✓') ? 'text-green-400' : 'text-red-400'}`}>{lookupResult}</div>
          )}
        </div>

        {/* Escrow table */}
        <div className="ae-card !p-0 overflow-hidden">
          <div className="px-5 py-4 border-b border-ae-border flex items-center justify-between">
            <h3 className="font-semibold text-white">Escrow Explorer</h3>
            <span className="text-xs text-ae-gray-dark">{escrows.length} transactions</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ae-border text-ae-gray text-xs uppercase tracking-wider">
                  <th className="text-left py-3 px-5 font-medium">ID</th>
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
                  <tr key={e.id} className="border-b border-ae-border/50 hover:bg-ae-accent/[0.02] transition-colors">
                    <td className="py-3 px-5 font-mono text-xs text-ae-accent">{e.id}</td>
                    <td className="py-3 px-5 text-xs text-white font-semibold">{e.amount} CSPR</td>
                    <td className="py-3 px-5 font-mono text-xs text-ae-gray">{shortAddr(e.sender)}</td>
                    <td className="py-3 px-5 font-mono text-xs text-ae-gray">{shortAddr(e.receiver)}</td>
                    <td className="py-3 px-5">
                      <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${statusColor(e.status)}`}>
                        ● {e.status.charAt(0).toUpperCase() + e.status.slice(1)}
                      </span>
                    </td>
                    <td className="py-3 px-5 text-xs text-ae-gray-dark flex items-center gap-1"><Clock size={12} /> {e.ttl}s</td>
                    <td className="py-3 px-5">
                      {e.status === 'locked' && (
                        <div className="flex gap-1.5">
                          <button className="text-[10px] px-2 py-1 rounded bg-green-500/10 text-green-400 hover:bg-green-500/20 cursor-pointer transition-colors flex items-center gap-1">
                            <Unlock size={10} /> Release
                          </button>
                          <button className="text-[10px] px-2 py-1 rounded bg-red-500/10 text-red-400 hover:bg-red-500/20 cursor-pointer transition-colors flex items-center gap-1">
                            <AlertTriangle size={10} /> Dispute
                          </button>
                        </div>
                      )}
                      {e.status !== 'locked' && <span className="text-[10px] text-ae-gray-dark">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
