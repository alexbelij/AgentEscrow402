import { Lock, Cog, ShieldCheck, Coins } from 'lucide-react'

const STEPS = [
  {
    n: 1, icon: Lock, title: 'Lock', desc: 'Agent A sends task + locks CSPR in on-chain escrow. TTL countdown starts.',
    code: 'POST /escrow {receiver, amount: 50_000_000_000, ttl: 300}',
  },
  {
    n: 2, icon: Cog, title: 'Execute', desc: 'Agent B performs the task off-chain. Server validates x402 payment header.',
    code: 'X-Payment: x402 sender=01abc... hash=5dd3...',
  },
  {
    n: 3, icon: ShieldCheck, title: 'Verify', desc: 'Service hash matches. Proof of completion verified on-chain.',
    code: 'POST /release {service_hash: "5dd33e8e79..."}',
  },
  {
    n: 4, icon: Coins, title: 'Settle', desc: 'Funds released to Agent B. Reputation updated with time-decay scoring.',
    code: '✓ 50 CSPR → Agent B | reputation += 1.0',
  },
]

export default function HowItWorks() {
  return (
    <section id="how-it-works" className="py-16 sm:py-24 relative">
      <div className="ae-section">
        <h2 className="text-2xl sm:text-3xl font-bold text-center mb-4">
          How <span className="ae-gradient-text">Escrow</span> Works
        </h2>
        <p className="text-ae-gray text-center max-w-lg mx-auto mb-12">
          Four steps. Fully autonomous. No intermediaries.
        </p>

        <div className="relative max-w-4xl mx-auto">
          {/* Vertical connector */}
          <div className="hidden sm:block absolute left-[23px] top-0 bottom-0 w-px bg-gradient-to-b from-ae-accent via-ae-cyan to-ae-green" aria-hidden="true" />

          <div className="space-y-6">
            {STEPS.map((s, i) => (
              <div key={s.n} className="flex items-start gap-5 group">
                {/* Number node */}
                <div className="relative z-10 shrink-0">
                  <div className="w-12 h-12 rounded-full bg-ae-card border-2 border-ae-accent/40 flex items-center justify-center text-ae-accent font-bold group-hover:border-ae-accent transition-colors">
                    {s.n}
                  </div>
                </div>

                {/* Content card */}
                <div className="ae-card flex-1 !p-5">
                  <div className="flex items-center gap-3 mb-2">
                    <div className="ae-icon !w-9 !h-9 !rounded-lg">
                      <s.icon size={18} className="text-ae-accent" />
                    </div>
                    <h3 className="font-bold text-white text-lg">{s.title}</h3>
                  </div>
                  <p className="text-sm text-ae-gray leading-relaxed mb-3">{s.desc}</p>
                  <code className="block text-xs font-mono bg-ae-bg/80 border border-ae-border rounded-lg px-3 py-2 text-ae-accent-bright overflow-x-auto">{s.code}</code>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
