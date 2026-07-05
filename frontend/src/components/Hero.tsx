import { useEffect, useRef } from 'react'
import { Github } from 'lucide-react'

export default function Hero() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const resize = () => {
      const dpr = window.devicePixelRatio || 1
      canvas.width = canvas.offsetWidth * dpr
      canvas.height = canvas.offsetHeight * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener('resize', resize)
    const W = () => canvas.offsetWidth
    const H = () => canvas.offsetHeight

    // Orbital rings behind the mascot
    const orbitals: { angle: number; speed: number; rx: number; ry: number; size: number; hue: number }[] = []
    for (let i = 0; i < 40; i++) {
      orbitals.push({
        angle: Math.random() * Math.PI * 2,
        speed: 0.003 + Math.random() * 0.008,
        rx: 120 + Math.random() * 100,
        ry: 60 + Math.random() * 50,
        size: 1.5 + Math.random() * 3,
        hue: 250 + Math.random() * 40,
      })
    }

    let raf: number
    const draw = () => {
      const w = W(), h = H()
      ctx.clearRect(0, 0, w, h)
      const cx = w * 0.55, cy = h * 0.45

      // Draw orbital paths (faint)
      ctx.strokeStyle = 'rgba(108,92,231,0.06)'
      ctx.lineWidth = 1
      for (const r of [140, 180, 220]) {
        ctx.beginPath()
        ctx.ellipse(cx, cy, r, r * 0.5, 0.3, 0, Math.PI * 2)
        ctx.stroke()
      }

      // Particles orbiting
      for (const o of orbitals) {
        o.angle += o.speed
        const x = cx + Math.cos(o.angle) * o.rx
        const y = cy + Math.sin(o.angle) * o.ry * 0.55
        const depth = Math.sin(o.angle)
        const alpha = 0.3 + depth * 0.4
        ctx.beginPath()
        ctx.arc(x, y, o.size * (0.6 + depth * 0.4), 0, Math.PI * 2)
        ctx.fillStyle = `hsla(${o.hue}, 70%, 65%, ${Math.max(0.1, alpha)})`
        ctx.fill()
      }

      raf = requestAnimationFrame(draw)
    }
    draw()
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', resize) }
  }, [])

  return (
    <section id="home" className="relative min-h-screen flex items-center overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-br from-[#0a0a1a] via-[#0f0a2a] to-[#0a0a1a]" />

      {/* Subtle hex grid */}
      <div className="absolute inset-0 opacity-[0.03]" style={{
        backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M30 5 L55 20 L55 40 L30 55 L5 40 L5 20 Z' fill='none' stroke='%236C5CE7' stroke-width='0.5'/%3E%3C/svg%3E")`,
        backgroundSize: '60px 60px',
      }} />

      {/* Orbital canvas behind mascot */}
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none z-[3]" />

      {/* Center glow */}
      <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full bg-purple-600/15 blur-[80px] pointer-events-none" />

      {/* Mascot - hidden on mobile to avoid overlapping text, visible from md+ */}
      <div className="absolute right-[3%] sm:right-[8%] top-[18%] sm:top-[14%] w-[40%] lg:w-[34%] max-w-lg z-[5] hidden md:block">
        <img
          src="/images/mascot/maskot_fly_casper.png"
          alt="AgentEscrow402"
          className="w-full relative z-10 animate-float-cat drop-shadow-[0_0_40px_rgba(108,92,231,0.3)]"
          loading="eager"
        />
      </div>

      {/* Content - left side */}
      <div className="ae-section relative z-20 py-32">
        <div className="max-w-2xl">
          {/* Mobile mascot - small, inline, above text */}
          <div className="md:hidden flex justify-center mb-6">
            <img
              src="/images/mascot/maskot_fly_casper.png"
              alt="AgentEscrow402"
              className="w-40 animate-float-cat drop-shadow-[0_0_30px_rgba(108,92,231,0.3)]"
              loading="eager"
            />
          </div>

          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-200 text-xs font-semibold mb-5">
            Casper testnet · x402 escrow · AI agent trust layer
          </div>

          <h1 className="text-4xl sm:text-4xl lg:text-5xl font-extrabold text-white leading-[1.2] mb-5 tracking-tight">
            Commercial escrow rails for{' '}
            <span className="bg-clip-text text-transparent bg-gradient-to-r from-purple-400 to-cyan-400">autonomous AI work</span>
          </h1>

          <p className="text-lg text-gray-300 mb-8 leading-relaxed max-w-md">
            AgentEscrow402 turns agent-to-agent payments into a verifiable flow: signed x402 payment intent, Casper testnet escrow, reputation scoring, risk pricing, ML-KEM metadata privacy and VRF-assisted arbitration.
          </p>

          <div className="flex flex-wrap gap-3 mb-14">
            <a href="/console/overview" className="inline-flex items-center gap-2 px-7 py-3.5 rounded-xl bg-ae-accent text-white font-semibold shadow-lg shadow-purple-600/20 hover:bg-ae-accent-bright hover:shadow-purple-600/30 transition-all">
              Inspect live console
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" /></svg>
            </a>
            <a href="https://github.com/alexbelij/AgentEscrow402" target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 px-7 py-3.5 rounded-xl border border-ae-border text-gray-300 font-medium hover:border-gray-500 hover:text-white transition-colors">
              <Github className="w-4 h-4" />
              GitHub
            </a>
          </div>

          {/* Stats row */}
          <div className="flex gap-6 sm:gap-8 flex-wrap">
            {[
              { val: '4', label: 'Deployed Contracts' },
              { val: 'Neon', label: 'Hosted Persistence' },
              { val: 'ML-KEM', label: 'Metadata Privacy' },
              { val: 'x402', label: 'Signed Intent' },
            ].map((s, i) => (
              <div key={i} className="text-center">
                <div className="text-2xl font-bold text-white font-mono">{s.val}</div>
                <div className="text-[11px] text-gray-500 mt-0.5">{s.label}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
