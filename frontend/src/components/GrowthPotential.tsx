import { ArrowUpRight } from 'lucide-react'

const VERTICALS = [
  {
    label: 'Vertical Depth',
    color: 'from-purple-500/20 to-purple-600/5',
    borderColor: 'border-purple-500/20',
    items: [
      {
        title: 'Threshold Escrow (MPC)',
        desc: 'Shamir Secret Sharing for n-of-m release — no single party holds the unlock key.',
      },
      {
        title: 'Formal Verification',
        desc: 'TLA+ specification for state machine invariants, proving escrow safety properties mathematically.',
      },
      {
        title: 'Flash Loan Protection',
        desc: 'Min hold period + block delay checks prevent manipulation of escrow state within a single block.',
      },
      {
        title: 'Advanced Risk Models',
        desc: 'Graph-based counterparty risk, cross-agent contagion scoring, real-time anomaly detection.',
      },
    ],
  },
  {
    label: 'Horizontal Expansion',
    color: 'from-cyan-500/20 to-cyan-600/5',
    borderColor: 'border-cyan-500/20',
    items: [
      {
        title: 'Multi-Chain Bridge',
        desc: 'Casper ↔ EVM atomic bridge — agents on Ethereum, Polygon, or Arbitrum can transact through the same escrow lifecycle.',
      },
      {
        title: 'Agent Discovery Marketplace',
        desc: 'A registry where agents publish capabilities, pricing, and reputation scores — other agents query and transact autonomously.',
      },
      {
        title: 'Enterprise Compliance',
        desc: 'Regulated jurisdiction support, KYC/AML hooks for enterprise agent deployments, audit trail export.',
      },
      {
        title: 'Gaming & Prediction Markets',
        desc: 'Merkle-proof result escrow for competitive AI, tournament payouts, and agent-vs-agent simulation wagers.',
      },
    ],
  },
]

export default function GrowthPotential() {
  return (
    <section id="growth" className="py-24 relative">
      {/* Mascot — left side, excited */}
      <img
        src="/images/mascot/maskot_casper_up__left.png"
        alt=""
        className="absolute left-0 top-20 w-28 lg:w-36 opacity-40 hover:opacity-70 transition-opacity pointer-events-none hidden lg:block"
        loading="lazy"
      />

      <div className="ae-section">
        <div className="text-center mb-14">
          <div className="text-xs text-ae-accent font-mono tracking-wider mb-3">GROWTH POTENTIAL</div>
          <h2 className="text-3xl font-extrabold text-white mb-4">
            Built to Scale in Every Direction
          </h2>
          <p className="text-gray-400 text-sm max-w-2xl mx-auto leading-relaxed">
            The escrow primitive is the foundation. The architecture is designed for both vertical
            depth — more sophisticated security, risk, and verification — and horizontal expansion
            across chains, agent frameworks, and industries.
          </p>
        </div>

        <div className="grid lg:grid-cols-2 gap-6">
          {VERTICALS.map((v) => (
            <div key={v.label} className={`bg-gradient-to-br ${v.color} border ${v.borderColor} rounded-2xl p-7`}>
              <div className="flex items-center gap-2 mb-6">
                <ArrowUpRight size={18} className="text-ae-accent" />
                <h3 className="text-white font-bold text-lg">{v.label}</h3>
              </div>

              <div className="space-y-4">
                {v.items.map((item) => (
                  <div key={item.title} className="flex gap-3">
                    <div className="w-1.5 h-1.5 rounded-full bg-ae-accent mt-2 shrink-0" />
                    <div>
                      <div className="text-white font-semibold text-sm mb-0.5">{item.title}</div>
                      <p className="text-gray-400 text-xs leading-relaxed">{item.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Infrastructure readiness note */}
        <div className="mt-8 bg-ae-card/40 border border-ae-border/60 rounded-xl p-5 text-center">
          <p className="text-xs text-gray-400 leading-relaxed max-w-2xl mx-auto">
            <span className="text-white font-semibold">Infrastructure already in place:</span>{' '}
            <code className="text-ae-accent/80">ChainAdapter</code> trait for multi-chain abstraction,{' '}
            <code className="text-ae-accent/80">ThresholdConfig</code> for MPC parameters,{' '}
            <code className="text-ae-accent/80">EscrowType</code> enum for extensible escrow categories,{' '}
            <code className="text-ae-accent/80">FlashGuard</code> module for anti-manipulation checks.
          </p>
        </div>
      </div>
    </section>
  )
}
