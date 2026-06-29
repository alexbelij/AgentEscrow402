import { Github, ExternalLink } from 'lucide-react'

export default function Footer() {
  return (
    <footer className="border-t border-ae-border py-8" role="contentinfo">
      <div className="ae-section flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-ae-gray-dark">
        <div className="flex items-center gap-2">
          <div className="w-5 h-5 rounded bg-gradient-to-br from-ae-accent to-ae-cyan flex items-center justify-center text-white text-[8px] font-bold">AE</div>
          <span>© {new Date().getFullYear()} AgentEscrow402. Built on Casper Network.</span>
        </div>
        <div className="flex items-center gap-4">
          <a href="https://github.com/alexbelij/AgentEscrow402" target="_blank" rel="noopener noreferrer" className="hover:text-white transition-colors cursor-pointer" aria-label="GitHub"><Github size={18} /></a>
          <a href="https://testnet.cspr.live" target="_blank" rel="noopener noreferrer" className="hover:text-white transition-colors cursor-pointer inline-flex items-center gap-1"><ExternalLink size={14} /> Explorer</a>
        </div>
      </div>
    </footer>
  )
}
