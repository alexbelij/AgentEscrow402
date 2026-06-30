import { useState, useEffect } from 'react'
import { Menu, X } from 'lucide-react'

interface Props { mobileOpen: boolean; setMobileOpen: (v: boolean) => void }

const links = [
  { href: '#home', label: 'Home' },
  { href: '#flow', label: 'How It Works' },
  { href: '#x402', label: 'x402' },
  { href: '#developers', label: 'Developers' },
  { href: '#faq', label: 'FAQ' },
]

export default function Navbar({ mobileOpen, setMobileOpen }: Props) {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const handler = () => setScrolled(window.scrollY > 50)
    window.addEventListener('scroll', handler, { passive: true })
    return () => window.removeEventListener('scroll', handler)
  }, [])

  return (
    <nav className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${scrolled ? 'bg-ae-bg/95 backdrop-blur border-b border-ae-border/50' : 'bg-transparent'}`}>
      <div className="ae-section flex items-center justify-between h-16">
        <a href="/" className="flex items-center gap-2">
          <img src="/images/logo.webp" alt="AgentEscrow402" className="h-7 w-auto" />
          <span className="font-bold text-white text-lg hidden sm:block">AgentEscrow402</span>
        </a>
        <div className="hidden md:flex items-center gap-1">
          {links.map(l => (
            <a key={l.href} href={l.href} className="px-3 py-2 text-sm font-medium text-gray-400 hover:text-purple-300 rounded-lg transition-colors">{l.label}</a>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <a href="/app" className="hidden sm:inline-flex items-center gap-2 px-5 py-2 rounded-lg bg-ae-accent text-white text-sm font-semibold hover:bg-ae-accent-bright transition-colors">
            Launch App
          </a>
          <button onClick={() => setMobileOpen(!mobileOpen)} className="md:hidden p-2 text-gray-400">
            {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>
      {mobileOpen && (
        <div className="md:hidden bg-ae-bg/95 border-t border-ae-border">
          <div className="px-4 py-3 space-y-1">
            {links.map(l => (
              <a key={l.href} href={l.href} onClick={() => setMobileOpen(false)} className="block px-3 py-2.5 text-gray-300 rounded-lg hover:bg-white/5">{l.label}</a>
            ))}
          </div>
        </div>
      )}
    </nav>
  )
}
