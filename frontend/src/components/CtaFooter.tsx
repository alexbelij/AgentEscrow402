import { ArrowRight } from 'lucide-react'

export default function CtaFooter() {
  return (
    <section className="py-20 relative overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-t from-ae-bg via-[#0e0e28] to-ae-bg" />

      {/* Banner bg */}
      <div className="ae-section relative z-10">
        <div className="relative rounded-2xl border border-ae-accent/20 bg-gradient-to-r from-ae-accent/10 via-purple-900/10 to-ae-accent/5 p-8 sm:p-12 overflow-hidden">
          {/* Glow */}
          <div className="absolute -top-20 -right-20 w-60 h-60 bg-ae-accent/20 rounded-full blur-[80px] pointer-events-none" />

          <div className="flex flex-col md:flex-row items-center gap-8">
            <img src="/images/mascot/maskot_fly_casper.png" alt="" className="w-24 sm:w-32 drop-shadow-[0_0_30px_rgba(108,92,231,0.4)]" loading="lazy" />

            <div className="flex-1 text-center md:text-left">
              <h2 className="text-2xl sm:text-3xl font-bold text-white mb-2">
                Ready to build agent commerce?
              </h2>
              <p className="text-gray-400 mb-6">
                Join the future of machine-to-machine payments on <span className="text-ae-accent">Casper Network</span>.
              </p>
              <div className="flex flex-wrap gap-4 justify-center md:justify-start">
                <a href="/app" className="group inline-flex items-center gap-2 px-6 py-3 rounded-lg bg-ae-accent text-white font-semibold hover:scale-[1.02] transition-transform shadow-lg shadow-ae-accent/25">
                  Launch App <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
                </a>
                <a href="https://github.com/alexbelij/AgentEscrow402" target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 px-6 py-3 rounded-lg border border-white/10 text-white/90 font-medium hover:bg-white/5 transition-colors">
                  Explore Docs
                </a>
              </div>
            </div>

            <img src="/images/casper-logo.png" alt="Casper" className="w-10 h-10 opacity-40 hidden md:block" />
          </div>
        </div>
      </div>
    </section>
  )
}
