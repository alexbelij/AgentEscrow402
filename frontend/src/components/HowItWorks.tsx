import { useEffect, useRef, useState } from 'react'

const steps = [
  { num: 1, title: 'Request', desc: 'Agent requests a service or resource from another agent.', icon: '📡' },
  { num: 2, title: 'Escrow', desc: 'Funds are locked in a smart escrow contract on Casper.', icon: '🔐' },
  { num: 3, title: 'Execute', desc: 'Service is delivered and verified against the conditions.', icon: '⚙️' },
  { num: 4, title: 'Settle', desc: 'Payment is released and settled on-chain automatically.', icon: '✅' },
]

export default function HowItWorks() {
  const ref = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const obs = new IntersectionObserver(([e]) => { if (e.isIntersecting) setVisible(true) }, { threshold: 0.2 })
    if (ref.current) obs.observe(ref.current)
    return () => obs.disconnect()
  }, [])

  return (
    <section id="how-it-works" className="py-24 relative overflow-hidden" ref={ref}>
      <div className="absolute inset-0 bg-gradient-to-b from-ae-bg via-[#0a0a20] to-ae-bg" />

      <div className="ae-section relative z-10">
        <p className="text-xs uppercase tracking-widest text-ae-accent mb-2">How it works</p>
        <h2 className="text-3xl sm:text-4xl font-bold mb-4">
          Simple for Agents.<br />
          <span className="text-gray-400">Powerful for Builders.</span>
        </h2>
        <p className="text-gray-500 mb-16 max-w-lg">
          Four steps from request to settlement. Fully automated, fully on-chain.
        </p>

        <div className="grid md:grid-cols-4 gap-6 relative">
          {/* Connecting line */}
          <div className="hidden md:block absolute top-12 left-[12%] right-[12%] h-px bg-gradient-to-r from-ae-accent/40 via-purple-500/40 to-cyan-500/40" />

          {steps.map((s, i) => (
            <div
              key={i}
              className={`relative group text-center transition-all duration-700 ${visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}
              style={{ transitionDelay: `${i * 150}ms` }}
            >
              {/* Step circle */}
              <div className="mx-auto w-16 h-16 rounded-full border-2 border-ae-accent/30 bg-ae-accent/5 flex items-center justify-center mb-4 group-hover:border-ae-accent group-hover:bg-ae-accent/10 transition-colors relative z-10">
                <span className="text-2xl">{s.icon}</span>
              </div>
              <div className="text-ae-accent text-xs font-bold mb-1">STEP {s.num}</div>
              <h3 className="text-lg font-semibold text-white mb-2">{s.title}</h3>
              <p className="text-sm text-gray-500 leading-relaxed">{s.desc}</p>
            </div>
          ))}
        </div>

        {/* Mascot sitting */}
        <div className="mt-16 flex items-center gap-8">
          <img src="/images/mascot/maskot_sidit.png" alt="" className="w-32 sm:w-40 drop-shadow-[0_0_20px_rgba(108,92,231,0.3)]" loading="lazy" />
          <div>
            <h3 className="text-xl font-bold text-white mb-2">Built for the AI Economy</h3>
            <div className="space-y-2 text-sm text-gray-400">
              <p>🤖 <strong className="text-white">Autonomous Payments</strong> — Agents pay and get paid without human intervention.</p>
              <p>📋 <strong className="text-white">Programmable Rules</strong> — Define conditions for release, timeouts, refunds, and more.</p>
              <p>🔍 <strong className="text-white">Audit &amp; Transparency</strong> — On-chain logs and proofs for every transaction.</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
