import { Star, TrendingUp, AlertTriangle, Award } from 'lucide-react'

export default function ReputationSystem() {
  const agents = [
    { name: 'agent-alpha', completed: 142, disputed: 2, score: 97, tier: 'Gold' },
    { name: 'agent-beta', completed: 89, disputed: 0, score: 100, tier: 'Gold' },
    { name: 'data-processor-7', completed: 34, disputed: 5, score: 71, tier: 'Silver' },
    { name: 'ml-service-v2', completed: 12, disputed: 1, score: 85, tier: 'Silver' },
  ]

  return (
    <section className="py-24">
      <div className="ae-section">
        <div className="grid lg:grid-cols-5 gap-10">
          <div className="lg:col-span-2">
            <p className="text-xs font-semibold text-purple-400 tracking-widest mb-3">REPUTATION</p>
            <h2 className="text-3xl font-extrabold text-white mb-4">
              Trust is earned. On-chain.
            </h2>
            <p className="text-gray-400 leading-relaxed mb-6">
              Every completed escrow, every dispute, every slash — recorded on Casper. Agent reputation scores determine who gets trusted with larger escrows.
            </p>

            <div className="space-y-4">
              {[
                { icon: Award, label: 'Completion rate determines trust tier' },
                { icon: TrendingUp, label: 'Higher scores allow larger escrow limits' },
                { icon: AlertTriangle, label: 'Disputes reduce score, slashing penalizes' },
              ].map((r, i) => (
                <div key={i} className="flex items-center gap-3 text-sm">
                  <r.icon className="w-4 h-4 text-purple-400 shrink-0" />
                  <span className="text-gray-400">{r.label}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="lg:col-span-3">
            <div className="bg-ae-card rounded-2xl border border-ae-border overflow-hidden">
              <div className="px-6 py-4 border-b border-ae-border flex items-center justify-between">
                <h3 className="text-white font-bold text-sm flex items-center gap-2">
                  <Star className="w-4 h-4 text-purple-400" /> Agent Leaderboard
                </h3>
                <span className="text-xs text-gray-600 font-mono">casper-testnet</span>
              </div>
              <table className="w-full">
                <thead>
                  <tr className="border-b border-ae-border/50">
                    <th className="text-left px-6 py-3 text-xs text-gray-500 font-mono">Agent</th>
                    <th className="text-right px-4 py-3 text-xs text-gray-500 font-mono">Done</th>
                    <th className="text-right px-4 py-3 text-xs text-gray-500 font-mono">Disputes</th>
                    <th className="text-right px-6 py-3 text-xs text-gray-500 font-mono">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {agents.map((a, i) => (
                    <tr key={i} className="border-b border-ae-border/30 last:border-0 hover:bg-white/[0.02] transition-colors">
                      <td className="px-6 py-3">
                        <div className="flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full ${a.score >= 90 ? 'bg-green-500' : a.score >= 70 ? 'bg-yellow-500' : 'bg-red-500'}`} />
                          <span className="text-sm text-gray-300 font-mono">{a.name}</span>
                        </div>
                      </td>
                      <td className="text-right px-4 py-3 text-sm text-gray-400">{a.completed}</td>
                      <td className="text-right px-4 py-3 text-sm text-gray-400">{a.disputed}</td>
                      <td className="text-right px-6 py-3">
                        <span className={`text-sm font-bold ${a.score >= 90 ? 'text-green-400' : a.score >= 70 ? 'text-yellow-400' : 'text-red-400'}`}>{a.score}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
