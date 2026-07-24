import { ExternalLink } from 'lucide-react'
import { Link } from 'react-router-dom'
import { CONTRACTS } from '../lib/manifest.generated'

const LINKS = [
  { label: 'GitHub', href: 'https://github.com/alexbelij/AgentEscrow402', external: true },
  { label: 'API Docs', href: '/console/docs?tab=api', external: false },
  { label: 'SDK', href: '/console/docs?tab=sdk', external: false },
  { label: 'MCP', href: '/console/docs?tab=mcp', external: false },
  { label: 'Telegram', href: 'https://t.me/AgentEscrow402', external: true },
  { label: 'Contract', href: CONTRACTS.escrowManagerV9.explorer, external: true },
]

export default function Footer() {
  return (
    <footer className="border-t border-ae-border/40 py-8">
      <div className="ae-section">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <img src="/images/logo.webp" alt="AE402" className="h-5 w-auto brightness-150 hue-rotate-[20deg]" />
            <span className="text-sm text-gray-500">&copy; 2026 AgentEscrow402</span>
          </div>

          <div className="flex items-center gap-5">
            {LINKS.map(l => l.external ? (
              <a
                key={l.label}
                href={l.href}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 text-xs text-gray-500 hover:text-ae-accent transition-colors"
              >
                {l.label} <ExternalLink size={10} />
              </a>
            ) : (
              <Link
                key={l.label}
                to={l.href}
                className="text-xs text-gray-500 hover:text-ae-accent transition-colors"
              >
                {l.label}
              </Link>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <span className="text-[10px] text-gray-600 tracking-wide">BUILT ON</span>
            <img src="/images/casper-logo.png" alt="Casper" className="h-4 w-auto brightness-200" />
          </div>
        </div>
      </div>
    </footer>
  )
}
