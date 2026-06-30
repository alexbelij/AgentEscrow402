import { useEffect, useRef, useState } from 'react'
import { Send, Lock, CheckCircle, Banknote } from 'lucide-react'

const steps = [
  {
    icon: Send,
    num: '1',
    title: 'Request',
    desc: 'Agent requests a service or resource. The request includes payment amount, TTL, and service hash.',
    code: `POST /escrow
{
  "receiver": "agent-beta",
  "amount": 50,
  "service_hash": "0x7f3a...",
  "ttl": 3600
}`,
  },
  {
    icon: Lock,
    num: '2',
    title: 'Escrow',
    desc: 'Funds are locked in a smart contract escrow. Neither party can withdraw until conditions are met or TTL expires.',
    code: `// Smart contract locks funds
escrow.create({
  sender: "agent-alpha",
  amount: 50 CSPR,
  locked_until: now() + 3600,
  release_condition: service_hash
})`,
  },
  {
    icon: CheckCircle,
    num: '3',
    title: 'Execute',
    desc: 'Service is delivered and verified. The service hash is matched against the escrow condition.',
    code: `// Service delivery verification
verify({
  service_hash: "0x7f3a...",
  delivered: true,
  quality_check: "PASS"
  // Hash matches escrow condition ✓
})`,
  },
  {
    icon: Banknote,
    num: '4',
    title: 'Settle',
    desc: 'Payment is released on-chain. The receiver gets paid, reputation scores update, and the escrow closes.',
    code: `POST /release
{ "service_hash": "0x7f3a..." }
// → 50 CSPR released to agent-beta
// → Reputation: +1 completed
// → Escrow status: RELEASED`,
  },
]

export default function PaymentFlow() {
  const ref = useRef<HTMLElement>(null)
  const [vis, setVis] = useState(false)
  const [active, setActive] = useState(0)

  useEffect(() => {
    const obs = new IntersectionObserver(([e]) => { if (e.isIntersecting) setVis(true) }, { threshold: 0.1 })
    if (ref.current) obs.observe(ref.current)
    return () => obs.disconnect()
  }, [])

  return (
    <section ref={ref} id="flow" className="py-24">
      <div className="ae-section">
        <div className="text-center mb-14">
          <p className="text-xs font-semibold text-purple-400 tracking-widest mb-3">HOW IT WORKS</p>
          <h2 className="text-3xl sm:text-4xl font-extrabold text-white mb-4">
            Simple for Agents.<br/>Powerful for Builders.
          </h2>
          <p className="text-gray-500 max-w-lg mx-auto">
            Four steps from request to settlement. Fully autonomous. No human in the loop.
          </p>
        </div>

        {/* Horizontal step indicators */}
        <div className={`flex items-center justify-center gap-0 mb-12 transition-all duration-700 ${vis ? 'opacity-100' : 'opacity-0'}`}>
          {steps.map((s, i) => (
            <div key={i} className="flex items-center">
              <button
                onClick={() => setActive(i)}
                className={`flex flex-col items-center gap-2 px-4 sm:px-8 py-3 rounded-xl transition-all ${
                  active === i ? 'bg-ae-accent/10 border border-ae-accent/30' : 'hover:bg-white/[0.02]'
                }`}
              >
                <div className={`w-10 h-10 rounded-full flex items-center justify-center transition-all ${
                  active === i ? 'bg-ae-accent text-white' : i < active ? 'bg-ae-accent/20 text-purple-400' : 'bg-ae-card border border-ae-border text-gray-500'
                }`}>
                  <s.icon className="w-4 h-4" />
                </div>
                <span className={`text-xs font-semibold ${active === i ? 'text-purple-300' : 'text-gray-500'}`}>{s.title}</span>
              </button>
              {i < steps.length - 1 && (
                <div className={`w-8 sm:w-16 h-px ${i < active ? 'bg-ae-accent/40' : 'bg-ae-border'}`} />
              )}
            </div>
          ))}
        </div>

        {/* Active step detail */}
        <div className={`max-w-5xl mx-auto transition-all duration-500 ${vis ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}>
          <div className="grid lg:grid-cols-2 gap-8 items-start">
            <div>
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-purple-500/10 text-purple-300 text-xs font-bold mb-4">
                STEP {steps[active].num}
              </div>
              <h3 className="text-2xl font-bold text-white mb-3">{steps[active].title}</h3>
              <p className="text-gray-400 leading-relaxed text-lg mb-6">{steps[active].desc}</p>

              {/* Mascot accent per step */}
              <div className="w-24">
                <img
                  src={`/images/mascot/${['maskot_ok', 'maskot_sidit', 'maskot_mind', 'maskot_casper_up'][active]}.png`}
                  alt=""
                  className="w-full opacity-60"
                />
              </div>
            </div>

            {/* Code block */}
            <div className="bg-ae-card rounded-2xl border border-ae-border overflow-hidden">
              <div className="flex items-center gap-2 px-4 py-3 border-b border-ae-border bg-ae-bg">
                <div className="w-3 h-3 rounded-full bg-red-500/70" />
                <div className="w-3 h-3 rounded-full bg-yellow-500/70" />
                <div className="w-3 h-3 rounded-full bg-green-500/70" />
                <span className="text-gray-600 text-xs ml-2 font-mono">escrow-flow.ts</span>
              </div>
              <pre className="p-5 text-sm font-mono text-gray-300 overflow-x-auto leading-relaxed">
                <code>{steps[active].code}</code>
              </pre>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
