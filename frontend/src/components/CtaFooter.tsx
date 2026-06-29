import { ArrowRight, FileText } from 'lucide-react'
import { Link } from 'react-router-dom'

export default function CtaFooter() {
  return (
    <section className="py-12 sm:py-16">
      <div className="ae-section">
        <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-ae-card to-ae-card border border-ae-border">
          <div className="absolute inset-0 bg-gradient-to-r from-ae-accent/5 to-ae-cyan/5 pointer-events-none" aria-hidden="true" />
          <div className="relative flex flex-col sm:flex-row items-center justify-between gap-6 p-8 sm:p-10">
            <div>
              <h2 className="text-xl sm:text-2xl font-bold">Ready to escrow your first transaction?</h2>
              <p className="text-ae-gray text-sm mt-1">Try the live dashboard — connected to Casper testnet.</p>
            </div>
            <div className="flex gap-3 shrink-0">
              <a href="https://github.com/alexbelij/AgentEscrow402" target="_blank" rel="noopener noreferrer" className="ae-btn-outline !text-sm">Docs <FileText size={16} /></a>
              <Link to="/app" className="ae-btn-primary !text-sm">Launch Dashboard <ArrowRight size={18} /></Link>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
