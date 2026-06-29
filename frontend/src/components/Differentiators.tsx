import { Scale, TrendingDown, Shield } from 'lucide-react'

const FEATURES = [
  {
    icon: Scale,
    title: 'Multi-Sig Disputes',
    desc: '3-of-5 arbiter voting. High-value disputes get human-grade resolution without centralized authority.',
  },
  {
    icon: TrendingDown,
    title: 'Reputation Decay',
    desc: 'On-chain scoring with exponential time-decay. Agents can\'t farm old scores — reputation stays fresh.',
  },
  {
    icon: Shield,
    title: 'Insurance Pool',
    desc: 'Configurable fee funds a reserve pool. Deadlocked escrows get resolved, nobody loses everything.',
  },
]

export default function Differentiators() {
  return (
    <section className="py-16 sm:py-24">
      <div className="ae-section">
        <h2 className="text-2xl sm:text-3xl font-bold text-center mb-4">
          What Makes This <span className="ae-gradient-text">Different</span>
        </h2>
        <p className="text-ae-gray text-center max-w-lg mx-auto mb-10">
          Not just escrow. A full payment infrastructure for the agent economy.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-4xl mx-auto">
          {FEATURES.map(f => (
            <div key={f.title} className="ae-card text-center">
              <div className="ae-icon mx-auto mb-4">
                <f.icon size={24} className="text-ae-accent" />
              </div>
              <h3 className="font-bold text-white mb-2">{f.title}</h3>
              <p className="text-sm text-ae-gray leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
