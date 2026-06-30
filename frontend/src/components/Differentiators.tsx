import { useEffect, useRef, useState } from 'react'

export default function Differentiators() {
  const ref = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const obs = new IntersectionObserver(([e]) => { if (e.isIntersecting) setVisible(true) }, { threshold: 0.15 })
    if (ref.current) obs.observe(ref.current)
    return () => obs.disconnect()
  }, [])

  return (
    <section id="integrate" className="py-24 relative overflow-hidden" ref={ref}>
      <div className="absolute inset-0 bg-gradient-to-b from-ae-bg to-[#0a0a20]" />

      <div className="ae-section relative z-10">
        <div className="grid lg:grid-cols-2 gap-12 items-start">
          {/* Left: Integrate */}
          <div className={`transition-all duration-700 ${visible ? 'opacity-100 translate-x-0' : 'opacity-0 -translate-x-8'}`}>
            <h2 className="text-3xl font-bold mb-4">
              Integrate in <span className="text-ae-accent">minutes</span>
            </h2>
            <p className="text-gray-400 mb-6">SDKs and APIs for popular frameworks and languages.</p>

            {/* Code block */}
            <div className="rounded-xl border border-white/10 bg-black/50 backdrop-blur overflow-hidden mb-6">
              <div className="flex items-center gap-2 px-4 py-2 border-b border-white/5">
                <span className="w-2 h-2 rounded-full bg-red-500/60" />
                <span className="w-2 h-2 rounded-full bg-yellow-500/60" />
                <span className="w-2 h-2 rounded-full bg-green-500/60" />
                <span className="text-xs text-gray-500 ml-2">POST /v1/escrow</span>
              </div>
              <pre className="p-4 text-sm text-gray-300 font-mono overflow-x-auto">
{`{
  "from": "agent_123",
  "to": "service_abc",
  "amount": "10_cspr",
  "condition": "result_hash"
}`}
              </pre>
            </div>

            {/* SDK badges */}
            <div className="flex flex-wrap gap-3">
              {['Python', 'JavaScript', 'TypeScript', 'Go'].map((lang) => (
                <span key={lang} className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs font-medium text-gray-400 hover:text-ae-accent hover:border-ae-accent/30 transition-colors cursor-default">
                  {lang}
                </span>
              ))}
            </div>
          </div>

          {/* Right: Mascot OK + mobile preview */}
          <div className={`relative transition-all duration-700 ${visible ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-8'}`} style={{ transitionDelay: '200ms' }}>
            <div className="flex items-end justify-end gap-4">
              {/* Mobile app mockup */}
              <div className="w-56 sm:w-64 rounded-2xl border border-white/10 bg-[#111127] shadow-2xl overflow-hidden">
                <div className="p-4 border-b border-white/5">
                  <div className="flex items-center gap-2 mb-3">
                    <img src="/images/logo.webp" alt="" className="w-5 h-5" />
                    <span className="text-sm font-bold text-white">AgentEscrow402</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-center">
                    <div className="p-2 rounded-lg bg-white/5">
                      <p className="text-ae-accent text-lg font-bold">1,240.80</p>
                      <p className="text-[10px] text-gray-500">CSPR Balance</p>
                    </div>
                    <div className="p-2 rounded-lg bg-white/5">
                      <p className="text-white text-lg font-bold">12</p>
                      <p className="text-[10px] text-gray-500">Active Escrows</p>
                    </div>
                  </div>
                </div>
                <div className="p-3 space-y-2 text-xs">
                  <p className="text-gray-500 font-medium">Recent Transactions</p>
                  <div className="flex justify-between items-center p-2 rounded-lg bg-white/5">
                    <div>
                      <p className="text-white font-medium">DataStream AI</p>
                      <p className="text-gray-600">Escrow &middot; 2m ago</p>
                    </div>
                    <span className="text-red-400 font-mono">-25.00</span>
                  </div>
                  <div className="flex justify-between items-center p-2 rounded-lg bg-white/5">
                    <div>
                      <p className="text-white font-medium">CodeAgent</p>
                      <p className="text-gray-600">Settled &middot; 5m ago</p>
                    </div>
                    <span className="text-green-400 font-mono">+12.50</span>
                  </div>
                </div>
                <div className="p-3">
                  <button className="w-full py-2 rounded-lg bg-ae-accent text-white text-xs font-bold">Create Escrow</button>
                </div>
              </div>

              {/* Mascot OK */}
              <img src="/images/mascot/maskot_ok.png" alt="" className="w-28 sm:w-36 drop-shadow-[0_0_20px_rgba(108,92,231,0.3)] hidden sm:block" loading="lazy" />
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
