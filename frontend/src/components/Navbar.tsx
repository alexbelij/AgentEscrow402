import { useState, useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Menu, X, ExternalLink } from 'lucide-react'

const NAV = [
  { label: 'Home', href: '/#home' },
  { label: 'How it Works', href: '/#how-it-works' },
  { label: 'Architecture', href: '/#architecture' },
  { label: 'Docs', href: 'https://github.com/alexbelij/AgentEscrow402', external: true },
]

interface Props { mobileOpen: boolean; setMobileOpen: (v: boolean) => void }

export default function Navbar({ mobileOpen, setMobileOpen }: Props) {
  const [scrolled, setScrolled] = useState(false)
  const location = useLocation()

  useEffect(() => {
    const fn = () => setScrolled(window.scrollY > 20)
    window.addEventListener('scroll', fn, { passive: true })
    return () => window.removeEventListener('scroll', fn)
  }, [])

  const handleNav = (href: string) => {
    setMobileOpen(false)
    if (href.startsWith('/#')) {
      const id = href.slice(2)
      if (location.pathname === '/') {
        document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
      } else {
        window.location.href = href
      }
    }
  }

  return (
    <header className={`fixed top-0 left-0 w-full z-50 transition-all duration-300 ${scrolled ? 'bg-ae-bg/90 backdrop-blur-md border-b border-ae-border' : 'bg-transparent'}`}>
      <nav className="ae-section flex items-center justify-between h-16" aria-label="Main navigation">
        <Link to="/" className="flex items-center gap-2 shrink-0" aria-label="AgentEscrow402 Home">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-ae-accent to-ae-cyan flex items-center justify-center text-white font-bold text-sm">AE</div>
          <span className="text-lg font-bold tracking-tight">Agent<span className="ae-gradient-text">Escrow</span><span className="text-ae-gray text-sm font-normal ml-0.5">402</span></span>
        </Link>

        <ul className="hidden md:flex items-center gap-1">
          {NAV.map(n => (
            <li key={n.label}>
              {n.external ? (
                <a href={n.href} target="_blank" rel="noopener noreferrer" className="px-3 py-2 text-sm text-ae-gray hover:text-white transition-colors cursor-pointer">{n.label}</a>
              ) : (
                <button onClick={() => handleNav(n.href)} className="px-3 py-2 text-sm text-ae-gray hover:text-white transition-colors cursor-pointer">{n.label}</button>
              )}
            </li>
          ))}
        </ul>

        <div className="hidden md:flex items-center gap-3">
          <Link to="/app" className="ae-btn-outline !py-2 !px-4 !text-sm">Dashboard <ExternalLink size={14} /></Link>
          <button className="ae-btn-primary !py-2 !px-4 !text-sm cursor-pointer">Connect Wallet</button>
        </div>

        <button onClick={() => setMobileOpen(!mobileOpen)} className="md:hidden p-2 text-ae-gray hover:text-white cursor-pointer" aria-label={mobileOpen ? 'Close' : 'Open'} aria-expanded={mobileOpen}>
          {mobileOpen ? <X size={24} /> : <Menu size={24} />}
        </button>
      </nav>

      <div className={`md:hidden transition-all duration-300 overflow-hidden ${mobileOpen ? 'max-h-96 border-b border-ae-border' : 'max-h-0'}`} role="menu">
        <div className="ae-section pb-6 pt-2 flex flex-col gap-1 bg-ae-bg/95 backdrop-blur-md">
          {NAV.map(n => n.external ? (
            <a key={n.label} href={n.href} target="_blank" rel="noopener noreferrer" className="py-3 px-3 text-ae-gray hover:text-white cursor-pointer" role="menuitem">{n.label}</a>
          ) : (
            <button key={n.label} onClick={() => handleNav(n.href)} className="py-3 px-3 text-left text-ae-gray hover:text-white cursor-pointer" role="menuitem">{n.label}</button>
          ))}
          <div className="flex gap-3 mt-3 px-3">
            <Link to="/app" onClick={() => setMobileOpen(false)} className="ae-btn-outline !py-2 !px-4 !text-sm flex-1 justify-center">Dashboard</Link>
            <button className="ae-btn-primary !py-2 !px-4 !text-sm flex-1 justify-center cursor-pointer">Connect</button>
          </div>
        </div>
      </div>
    </header>
  )
}
