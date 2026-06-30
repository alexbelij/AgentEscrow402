import { ArrowRight, FileText } from 'lucide-react'
import { useEffect, useRef } from 'react'

export default function Hero() {
  const mascotRef = useRef<HTMLImageElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (!mascotRef.current) return
      const x = (e.clientX / window.innerWidth - 0.5) * 10
      const y = (e.clientY / window.innerHeight - 0.5) * 10
      mascotRef.current.style.transform = `translate(${x}px, ${y}px)`
    }
    window.addEventListener('mousemove', handler)
    return () => window.removeEventListener('mousemove', handler)
  }, [])

  return (
    <section id="home" className="relative min-h-screen flex items-center overflow-hidden pt-16">
      {/* Gradient bg */}
      <div className="absolute inset-0 bg-gradient-to-b from-ae-bg via-[#0e0e28] to-ae-bg" aria-hidden="true" />

      {/* Grid */}
      <div className="absolute inset-0 opacity-[0.04]" aria-hidden="true"
        style={{ backgroundImage: 'linear-gradient(rgba(108,92,231,0.3) 1px, transparent 1px), linear-gradient(90deg, rgba(108,92,231,0.3) 1px, transparent 1px)', backgroundSize: '50px 50px' }} />

      {/* Particles */}
      {Array.from({ length: 20 }).map((_, i) => (
        <div key={i} className="particle" aria-hidden="true" style={{
          left: `${5 + Math.random() * 90}%`,
          bottom: '-5%',
          animationDuration: `${8 + Math.random() * 12}s`,
          animationDelay: `${Math.random() * 8}s`,
          width: `${1 + Math.random() * 2}px`,
          height: `${1 + Math.random() * 2}px`,
          background: i % 3 === 0 ? '#00D2FF' : '#6C5CE7',
        }} />
      ))}

      {/* Glow */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[600px] h-[400px] bg-ae-accent/10 rounded-full blur-[120px] pointer-events-none" aria-hidden="true" />
      <div className="absolute top-1/3 right-1/4 w-[300px] h-[300px] bg-purple-600/8 rounded-full blur-[100px] pointer-events-none" aria-hidden="true" />

      <div className="ae-section relative z-10 grid lg:grid-cols-2 gap-8 items-center py-20">
        {/* Left: Text */}
        <div className="flex flex-col items-start">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 px-4 py-1.5 mb-6 border border-ae-accent/30 rounded-full text-xs text-ae-accent bg-ae-accent/5 backdrop-blur-sm animate-fade-in-down">
            <span className="w-1.5 h-1.5 rounded-full bg-ae-accent animate-pulse" />
            BUILT FOR AI. BACKED BY CASPER.
          </div>

          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold leading-[1.1] mb-6 animate-fade-in-up">
            The Payment Layer<br />for{' '}
            <span className="bg-gradient-to-r from-ae-accent via-purple-400 to-cyan-400 bg-clip-text text-transparent">
              AI&nbsp;Agents
            </span>
          </h1>

          <p className="text-base sm:text-lg text-gray-400 mb-8 max-w-lg leading-relaxed animate-fade-in-up" style={{ animationDelay: '0.1s' }}>
            AgentEscrow402 enables secure, scalable, x402-compatible payments for machine-to-machine commerce on Casper Network.
          </p>

          <div className="flex flex-wrap gap-4 mb-10 animate-fade-in-up" style={{ animationDelay: '0.2s' }}>
            <a href="/app" className="group inline-flex items-center gap-2 px-6 py-3 rounded-lg bg-ae-accent text-white font-semibold shadow-lg shadow-ae-accent/25 hover:shadow-ae-accent/40 transition-all hover:scale-[1.02]">
              Start Building <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
            </a>
            <a href="https://github.com/alexbelij/AgentEscrow402" target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 px-6 py-3 rounded-lg border border-white/10 text-white/90 font-medium hover:bg-white/5 transition-colors">
              <FileText className="w-4 h-4" /> Read Docs
            </a>
          </div>

          <div className="flex items-center gap-3 text-sm text-gray-500 animate-fade-in-up" style={{ animationDelay: '0.3s' }}>
            <span>Built on</span>
            <img src="/images/casper-logo.png" alt="Casper" className="w-5 h-5" />
            <img src="/images/casper-wordmark-white.png" alt="Casper Network" className="h-4 opacity-60" />
          </div>
        </div>

        {/* Right: Mascot */}
        <div className="relative flex justify-center lg:justify-end animate-fade-in-up" style={{ animationDelay: '0.3s' }}>
          {/* Portal glow behind mascot */}
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="w-72 h-72 sm:w-96 sm:h-96 rounded-full bg-gradient-to-br from-purple-600/30 via-ae-accent/20 to-cyan-500/10 blur-[60px] animate-pulse-slow" />
          </div>
          <img
            ref={mascotRef}
            src="/images/mascot/maskot_portal.png"
            alt="AgentEscrow402 Mascot"
            className="relative z-10 w-64 sm:w-80 lg:w-[420px] drop-shadow-[0_0_40px_rgba(108,92,231,0.4)] transition-transform duration-300 ease-out"
            loading="eager"
          />
        </div>
      </div>

      {/* Feature bar below hero */}
      <div className="absolute bottom-0 inset-x-0 z-10">
        <div className="ae-section">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pb-8">
            {[
              { icon: '⚡', title: 'x402 Compatible', desc: 'Native support for the x402 protocol standard for agent payments.' },
              { icon: '🔒', title: 'Escrow by Design', desc: 'Funds held in escrow until conditions are met.' },
              { icon: '🏗️', title: 'Built on Casper', desc: 'Enterprise-grade security, finality, and scalability.' },
              { icon: '🤖', title: 'M2M Commerce', desc: 'Designed for autonomous agents transacting at machine speed.' },
            ].map((f, i) => (
              <div key={i} className="group p-4 rounded-xl border border-white/5 bg-white/[0.02] backdrop-blur-sm hover:border-ae-accent/30 hover:bg-ae-accent/5 transition-all">
                <span className="text-2xl mb-2 block">{f.icon}</span>
                <h3 className="text-sm font-semibold text-white mb-1">{f.title}</h3>
                <p className="text-xs text-gray-500 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
