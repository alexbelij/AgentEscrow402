import { useEffect, useRef } from 'react'

export default function Hero() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  // Purple particle trail behind cat
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const dpr = 2
    canvas.width = canvas.offsetWidth * dpr
    canvas.height = canvas.offsetHeight * dpr
    ctx.scale(dpr, dpr)
    const W = canvas.offsetWidth, H = canvas.offsetHeight

    const particles: {x:number,y:number,vx:number,vy:number,life:number,size:number,hue:number}[] = []
    // Cat position: right side
    const catX = W * 0.62, catY = H * 0.42

    let raf: number
    const draw = () => {
      ctx.clearRect(0, 0, W, H)
      // Emit from behind the cat (left side of cat)
      if (Math.random() < 0.4) {
        particles.push({
          x: catX - 30 + Math.random() * 20,
          y: catY + (Math.random() - 0.5) * 40,
          vx: -(2 + Math.random() * 3),
          vy: (Math.random() - 0.5) * 1.5,
          life: 1,
          size: 2 + Math.random() * 4,
          hue: 260 + Math.random() * 30,
        })
      }
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i]
        p.x += p.vx; p.y += p.vy; p.life -= 0.02
        if (p.life <= 0) { particles.splice(i, 1); continue }
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.size * p.life, 0, Math.PI * 2)
        ctx.fillStyle = `hsla(${p.hue}, 80%, 60%, ${p.life * 0.5})`
        ctx.fill()
      }
      raf = requestAnimationFrame(draw)
    }
    draw()
    return () => cancelAnimationFrame(raf)
  }, [])

  return (
    <section id="home" className="relative min-h-screen flex items-center overflow-hidden">
      {/* Deep space background */}
      <div className="absolute inset-0 bg-gradient-to-br from-[#0a0a1a] via-[#0f0a2a] to-[#0a0a1a]" />

      {/* Subtle grid */}
      <div className="absolute inset-0 opacity-[0.04]" style={{
        backgroundImage: 'radial-gradient(circle, #6C5CE7 1px, transparent 1px)',
        backgroundSize: '40px 40px',
      }} />

      {/* Portal glow behind cat */}
      <div className="absolute right-[10%] top-[20%] w-[400px] h-[400px] rounded-full bg-gradient-radial from-purple-600/20 to-transparent blur-[60px] animate-portal-pulse pointer-events-none" />

      {/* Particle canvas */}
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none z-10" />

      {/* Cat mascot - flying left to right, positioned right */}
      <div className="absolute right-[5%] sm:right-[10%] top-[15%] sm:top-[12%] w-[45%] sm:w-[38%] lg:w-[32%] max-w-md z-[5]">
        {/* Purple rocket flame trail */}
        <div className="absolute left-[-20%] top-[35%] w-[50%] h-[30%] z-0">
          <div className="w-full h-full bg-gradient-to-l from-purple-500/60 via-purple-600/30 to-transparent rounded-full blur-[20px] animate-rocket-flame" />
          <div className="absolute inset-0 w-[80%] h-[60%] mx-auto my-auto bg-gradient-to-l from-white/20 via-purple-300/20 to-transparent rounded-full blur-[10px] animate-rocket-flame" style={{ animationDelay: '-0.5s' }} />
        </div>
        <img
          src="/images/mascot/maskot_fly_casper.png"
          alt="AgentEscrow402 Cat"
          className="w-full relative z-10 animate-float-cat"
          style={{ transform: 'scaleX(-1)' }}
          loading="eager"
        />
      </div>

      {/* Content - left side */}
      <div className="ae-section relative z-20 py-32">
        <div className="max-w-xl">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 mb-6 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300 text-xs font-semibold tracking-wide">
            <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse" />
            BUILT FOR AI &middot; BACKED BY CASPER
          </div>

          <h1 className="text-4xl sm:text-5xl lg:text-[3.5rem] font-extrabold text-white leading-[1.08] mb-5 tracking-tight">
            The Payment Layer<br/>
            for <span className="bg-clip-text text-transparent bg-gradient-to-r from-purple-400 to-cyan-400">AI Agents</span>
          </h1>

          <p className="text-lg text-gray-400 mb-8 leading-relaxed max-w-md">
            AgentEscrow402 enables secure, x402-compatible escrow payments for machine-to-machine commerce on Casper Network.
          </p>

          <div className="flex flex-wrap gap-3 mb-14">
            <a href="/app" className="inline-flex items-center gap-2 px-7 py-3.5 rounded-xl bg-ae-accent text-white font-semibold shadow-lg shadow-purple-600/20 hover:bg-ae-accent-bright hover:shadow-purple-600/30 transition-all">
              Start Building
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" /></svg>
            </a>
            <a href="https://github.com/alexbelij/AgentEscrow402" target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 px-7 py-3.5 rounded-xl border border-ae-border text-gray-300 font-medium hover:border-gray-500 hover:text-white transition-colors">
              Read Docs
            </a>
          </div>

          {/* Feature pills */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { title: 'x402 Compatible', desc: 'Native x402 protocol support for AI payments' },
              { title: 'Escrow by Design', desc: 'Funds held until conditions are met' },
              { title: 'Built on Casper', desc: 'Enterprise-grade finality and security' },
              { title: 'M2M Commerce', desc: 'Agents transact at machine speed' },
            ].map((f, i) => (
              <div key={i} className="bg-ae-card/60 backdrop-blur border border-ae-border rounded-xl p-3.5 hover:border-purple-500/30 transition-all">
                <h3 className="text-white text-xs font-bold mb-1">{f.title}</h3>
                <p className="text-[10px] text-gray-500 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
