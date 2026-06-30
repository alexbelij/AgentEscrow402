import { useEffect, useRef, useState } from 'react'
import { Zap, Shield, RefreshCw, Globe } from 'lucide-react'

export default function X402Protocol() {
  const ref = useRef<HTMLElement>(null)
  const [vis, setVis] = useState(false)
  useEffect(() => {
    const obs = new IntersectionObserver(([e]) => { if (e.isIntersecting) setVis(true) }, { threshold: 0.1 })
    if (ref.current) obs.observe(ref.current)
    return () => obs.disconnect()
  }, [])

  return (
    <section ref={ref} id="x402" className="py-24 bg-ae-card/30">
      <div className="ae-section">
        <div className="grid lg:grid-cols-2 gap-16 items-center">
          {/* Left: explanation */}
          <div className={`transition-all duration-700 ${vis ? 'opacity-100' : 'opacity-0 translate-y-8'}`}>
            <p className="text-xs font-semibold text-ae-cyan tracking-widest mb-3">x402 PROTOCOL</p>
            <h2 className="text-3xl font-extrabold text-white mb-5">
              HTTP 402: Payment Required.<br/>
              <span className="text-gray-500">Finally implemented.</span>
            </h2>
            <p className="text-gray-400 leading-relaxed mb-6">
              HTTP status 402 was reserved for "Payment Required" since 1999 but never standardized. The x402 protocol defines how AI agents negotiate, authorize, and settle payments over HTTP — turning every API call into a potential payment channel.
            </p>
            <p className="text-gray-400 leading-relaxed mb-8">
              AgentEscrow402 implements x402 on Casper Network, adding escrow protection so that agents only pay for services that are actually delivered.
            </p>

            <div className="grid grid-cols-2 gap-4">
              {[
                { icon: Zap, title: 'Pay-per-call', desc: 'Agents pay for exactly what they use. No subscriptions, no prepayment.' },
                { icon: Shield, title: 'Escrow protection', desc: 'Funds locked until service delivery is verified on-chain.' },
                { icon: RefreshCw, title: 'Auto-refund', desc: 'If TTL expires without delivery, funds automatically return to sender.' },
                { icon: Globe, title: 'Any HTTP API', desc: 'Works with any service that responds to HTTP requests.' },
              ].map((f, i) => (
                <div key={i} className="space-y-1.5">
                  <f.icon className="w-5 h-5 text-purple-400" />
                  <h3 className="text-white text-sm font-bold">{f.title}</h3>
                  <p className="text-xs text-gray-500 leading-relaxed">{f.desc}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Right: HTTP flow diagram */}
          <div className={`transition-all duration-700 delay-200 ${vis ? 'opacity-100' : 'opacity-0 translate-y-8'}`}>
            <div className="bg-ae-bg rounded-2xl border border-ae-border p-6 font-mono text-sm space-y-4">
              <div className="space-y-2">
                <p className="text-gray-500">{'// Agent requests service'}</p>
                <p><span className="text-cyan-400">GET</span> <span className="text-white">/api/analyze</span></p>
                <p className="text-yellow-400">← 402 Payment Required</p>
                <p className="text-gray-500">{'// x402 header:'}</p>
                <p className="text-gray-400">X-402-Price: <span className="text-purple-400">50 CSPR</span></p>
                <p className="text-gray-400">X-402-Address: <span className="text-purple-400">0x7f3a...</span></p>
              </div>
              <div className="border-t border-ae-border pt-4 space-y-2">
                <p className="text-gray-500">{'// Agent creates escrow'}</p>
                <p><span className="text-green-400">POST</span> <span className="text-white">/escrow</span></p>
                <p className="text-gray-400">X-402-Sender: <span className="text-purple-400">agent-alpha</span></p>
                <p className="text-green-400">← 201 Escrow Created</p>
              </div>
              <div className="border-t border-ae-border pt-4 space-y-2">
                <p className="text-gray-500">{'// Retry with payment proof'}</p>
                <p><span className="text-cyan-400">GET</span> <span className="text-white">/api/analyze</span></p>
                <p className="text-gray-400">X-402-Payment: <span className="text-purple-400">escrow_0x2c91...</span></p>
                <p className="text-green-400">← 200 OK + result</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
