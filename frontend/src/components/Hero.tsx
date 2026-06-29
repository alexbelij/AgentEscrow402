import { ArrowRight, FileText } from 'lucide-react'

export default function Hero() {
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

      <div className="ae-section relative z-10 flex flex-col items-center text-center py-20">
        {/* Badge */}
        <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-ae-accent/10 border border-ae-accent/20 text-sm text-ae-accent-bright mb-8 animate-fade-in-up">
          <span className="w-2 h-2 rounded-full bg-ae-green animate-pulse" />
          x402 Protocol · Casper Testnet
        </div>

        <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold leading-[1.1] tracking-tight mb-6 max-w-3xl animate-fade-in-up">
          AI Agents Can't Sign Contracts.<br />
          <span className="ae-gradient-text">They Need Escrow.</span>
        </h1>

        <p className="text-lg sm:text-xl text-ae-gray leading-relaxed mb-10 max-w-2xl animate-fade-in-up">
          x402-compatible payment protocol that lets autonomous agents lock CSPR, verify work, and settle trustlessly. No humans required.
        </p>

        <div className="flex flex-wrap justify-center gap-4 mb-12 animate-fade-in-up">
          <a href="#how-it-works" className="ae-btn-primary">
            See How It Works <ArrowRight size={18} />
          </a>
          <a href="https://github.com/alexbelij/AgentEscrow402" target="_blank" rel="noopener noreferrer" className="ae-btn-outline">
            Read Docs <FileText size={16} />
          </a>
        </div>

        {/* Trust bar */}
        <div className="flex flex-wrap justify-center gap-4 sm:gap-8 text-xs text-ae-gray-dark animate-fade-in-up">
          {[
            { label: 'Casper Testnet', icon: '🔗' },
            { label: '1 Smart Contract', icon: '📄' },
            { label: '103 Tests Passing', icon: '✅' },
            { label: 'x402 Standard', icon: '🔐' },
          ].map(t => (
            <span key={t.label} className="flex items-center gap-1.5">
              <span>{t.icon}</span>
              <span>{t.label}</span>
            </span>
          ))}
        </div>

        {/* Animated escrow diagram */}
        <div className="mt-16 ae-card !p-4 sm:!p-6 max-w-2xl w-full animate-fade-in-up">
          <div className="flex items-center justify-between gap-2 sm:gap-4 text-xs font-mono">
            <div className="text-center shrink-0">
              <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-xl bg-ae-accent/15 border border-ae-accent/25 flex items-center justify-center mb-1.5 mx-auto">
                <span className="text-lg">🤖</span>
              </div>
              <span className="text-ae-gray text-[10px]">Agent A</span>
            </div>

            <div className="flex-1 flex flex-col items-center gap-1">
              <div className="w-full h-px bg-gradient-to-r from-ae-accent via-ae-cyan to-ae-accent relative">
                <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-ae-accent animate-pulse" />
              </div>
              <span className="text-ae-gray-dark text-[9px]">50 CSPR locked</span>
            </div>

            <div className="text-center shrink-0">
              <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-xl bg-ae-cyan/15 border border-ae-cyan/25 flex items-center justify-center mb-1.5 mx-auto animate-pulse-glow">
                <span className="text-lg">🔒</span>
              </div>
              <span className="text-ae-cyan text-[10px]">Escrow</span>
            </div>

            <div className="flex-1 flex flex-col items-center gap-1">
              <div className="w-full h-px bg-gradient-to-r from-ae-cyan via-ae-green to-ae-green relative">
                <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-ae-green animate-pulse" />
              </div>
              <span className="text-ae-gray-dark text-[9px]">verified → release</span>
            </div>

            <div className="text-center shrink-0">
              <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-xl bg-ae-green/15 border border-ae-green/25 flex items-center justify-center mb-1.5 mx-auto">
                <span className="text-lg">🤖</span>
              </div>
              <span className="text-ae-gray text-[10px]">Agent B</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
