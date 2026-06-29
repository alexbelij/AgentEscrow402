import { ExternalLink } from 'lucide-react'

const STACK = ['Python 3.11', 'FastAPI', 'Rust', 'casper-contract 5.1', 'x402 Protocol', 'TypeScript']

export default function Architecture() {
  return (
    <section id="architecture" className="py-16 sm:py-24">
      <div className="ae-section">
        <h2 className="text-2xl sm:text-3xl font-bold text-center mb-4">Architecture</h2>
        <p className="text-ae-gray text-center max-w-lg mx-auto mb-10">
          FastAPI backend + Casper smart contract. Real deployment on testnet.
        </p>

        {/* Contract info */}
        <div className="max-w-3xl mx-auto ae-card !p-5 mb-8">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
            <div>
              <span className="text-ae-gray-dark text-xs uppercase tracking-wider block mb-1">Contract</span>
              <span className="font-mono text-ae-accent text-xs">escrow</span>
            </div>
            <div>
              <span className="text-ae-gray-dark text-xs uppercase tracking-wider block mb-1">Hash</span>
              <a href="https://testnet.cspr.live/contract/5dd33e8e79789d38" target="_blank" rel="noopener noreferrer"
                className="font-mono text-xs text-ae-gray hover:text-white transition-colors inline-flex items-center gap-1 cursor-pointer">
                5dd33e8e79789d38... <ExternalLink size={10} />
              </a>
            </div>
            <div>
              <span className="text-ae-gray-dark text-xs uppercase tracking-wider block mb-1">Deploy TX</span>
              <a href="https://testnet.cspr.live/deploy/16e3787ca7307ea9" target="_blank" rel="noopener noreferrer"
                className="font-mono text-xs text-ae-gray hover:text-white transition-colors inline-flex items-center gap-1 cursor-pointer">
                16e3787ca7307ea9... <ExternalLink size={10} />
              </a>
            </div>
          </div>
        </div>

        {/* Flow diagram */}
        <div className="max-w-3xl mx-auto ae-card !p-6 mb-8">
          <div className="flex flex-wrap items-center justify-center gap-2 text-xs font-mono">
            {['AI Agent', '→', 'FastAPI Server', '→', 'Casper RPC', '→', 'escrow contract'].map((s, i) => (
              <span key={i} className={s === '→' ? 'text-ae-accent' : 'bg-ae-bg px-3 py-1.5 rounded border border-ae-border text-ae-gray'}>{s}</span>
            ))}
          </div>
          <div className="text-center mt-3">
            <span className="text-xs text-ae-gray-dark">↕ Event Monitor (async)</span>
          </div>
        </div>

        {/* Tech stack */}
        <div className="flex flex-wrap justify-center gap-2">
          {STACK.map(s => (
            <span key={s} className="px-3 py-1.5 rounded-full bg-ae-card border border-ae-border text-xs text-ae-gray">{s}</span>
          ))}
        </div>
      </div>
    </section>
  )
}
