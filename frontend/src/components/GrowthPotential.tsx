import { ArrowUpRight, CheckCircle2 } from 'lucide-react'

// Six of the eight items originally listed here as roadmap/"growth potential"
// (Threshold Escrow, Formal Verification, Flash Loan Protection, Multi-Chain
// Bridge, Agent Discovery Marketplace, Enterprise Compliance) were actually
// shipped during the final-round hardening push and are now live in the
// console (see Capabilities.tsx / feature-map). Reframed below as delivered
// velocity instead of leaving them as stale future-tense claims.
const SHIPPED_SINCE_TIER1 = [
  {
    title: 'Threshold Escrow (MPC)',
    desc: 'Shamir Secret Sharing for n-of-m release, shipped — no single party holds the unlock key.',
  },
  {
    title: 'Formal Verification',
    desc: 'TLA+ specification for state machine invariants, proving escrow safety properties mathematically.',
  },
  {
    title: 'Flash Loan Protection (FlashGuard)',
    desc: 'Min hold period + block delay checks, fully wired onto release/refund/dispute, shipped.',
  },
  {
    title: 'Multi-Chain Bridge',
    desc: 'Casper ↔ EVM (Sepolia) HTLC atomic bridge — same sha256 hashlock on both legs, live on testnet.',
  },
  {
    title: 'Agent Discovery Marketplace',
    desc: 'Live registry where agents publish capabilities, pricing and reputation — see /console/marketplace.',
  },
  {
    title: 'Enterprise Compliance',
    desc: 'Jurisdiction checks, KYC tiering and reporting-threshold flags, live on every escrow creation.',
  },
]

const VERTICALS = [
  {
    label: 'Vertical Depth',
    color: 'from-purple-500/20 to-purple-600/5',
    borderColor: 'border-purple-500/20',
    items: [
      {
        title: 'Advanced Risk Models',
        desc: 'Graph-based counterparty risk, cross-agent contagion scoring, real-time anomaly detection — beyond the live IsolationForest model.',
      },
      {
        title: 'On-chain batch cap/quorum guard',
        desc: 'Contract upgrade to enforce the server-side batch cap and arbiter quorum logic on-chain instead of in the API layer.',
      },
      {
        title: 'Security audit',
        desc: 'Third-party firm review of all contracts before any mainnet deployment.',
      },
    ],
  },
  {
    label: 'Horizontal Expansion',
    color: 'from-cyan-500/20 to-cyan-600/5',
    borderColor: 'border-cyan-500/20',
    items: [
      {
        title: 'Challenge Arbiter, Range Proof Registry, Governance DAO, Two-Key Account',
        desc: 'Code-complete and tests green on main; queued for testnet deploy — see the Feature Map for status on each.',
      },
      {
        title: 'Prediction markets',
        desc: 'Extending the live Merkle-proof gaming-reward escrow from tournament payouts to open agent-vs-agent wager markets.',
      },
      {
        title: 'Mainnet deployment',
        desc: 'With a governance-multisig upgrade path, after the security audit above.',
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

        <div className="mb-10 bg-gradient-to-br from-emerald-500/10 to-emerald-600/5 border border-emerald-500/20 rounded-2xl p-7">
          <div className="flex items-center gap-2 mb-6">
            <CheckCircle2 size={18} className="text-emerald-400" />
            <h3 className="text-white font-bold text-lg">Shipped since the Tier-1 baseline</h3>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {SHIPPED_SINCE_TIER1.map((item) => (
              <div key={item.title} className="flex gap-3">
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 mt-2 shrink-0" />
                <div>
                  <div className="text-white font-semibold text-sm mb-0.5">{item.title}</div>
                  <p className="text-gray-400 text-xs leading-relaxed">{item.desc}</p>
                </div>
              </div>
            ))}
          </div>
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
            <span className="text-white font-semibold">Also live under the hood:</span>{' '}
            <code className="text-ae-accent/80">ChainAdapter</code> trait backing the multi-chain bridge,{' '}
            <code className="text-ae-accent/80">ThresholdConfig</code> driving the shipped MPC escrow,{' '}
            <code className="text-ae-accent/80">EscrowType</code> enum for extensible escrow categories,{' '}
            <code className="text-ae-accent/80">FlashGuard</code> module wired onto release/refund/dispute.
          </p>
        </div>
      </div>
    </section>
  )
}
