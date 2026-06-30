import { useState, useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { X, ExternalLink, Home, Repeat, Shield, Code, HelpCircle, LayoutDashboard, BookOpen, Plug, FileCode, Activity } from 'lucide-react'

const NAV_ITEMS = [
  { label: 'HOME', href: '/#home', icon: Home },
  { label: 'FLOW', href: '/#flow', icon: Repeat },
  { label: 'X402', href: '/#x402', icon: Shield },
  { label: 'REPUTATION', href: '/#reputation', icon: Activity },
  { label: 'SDK', href: '/#developers', icon: Code },
  { label: 'FAQ', href: '/#faq', icon: HelpCircle },
]

const DASHBOARD_ITEMS = [
  { label: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },
  { label: 'Landing', href: '/', icon: Home },
]

const EXTERNAL_LINKS = [
  { label: 'GitHub', href: 'https://github.com/alexbelij/AgentEscrow402', icon: FileCode },
  { label: 'SDK Docs', href: 'https://github.com/alexbelij/AgentEscrow402/tree/main/sdk', icon: BookOpen },
  { label: 'MCP Server', href: 'https://github.com/alexbelij/AgentEscrow402/tree/main/sdk', icon: Plug },
  { label: 'Contracts', href: 'https://testnet.cspr.live/contract/5dd33e8e79789d386832a80c39006002383fa44dd76ba677cae3279f3a134451', icon: Shield },
]

export default function Navbar({ mobileOpen, setMobileOpen }: { mobileOpen: boolean; setMobileOpen: (v: boolean) => void }) {
  const location = useLocation()
  const isLanding = location.pathname === '/'
  const isDashboard = location.pathname === '/dashboard'
  const [activeSection, setActiveSection] = useState('home')

  useEffect(() => {
    if (!isLanding) return
    const sections = NAV_ITEMS.map(n => n.href.replace('/#', '')).filter(Boolean)
    const observer = new IntersectionObserver(
      entries => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActiveSection(entry.target.id)
        }
      },
      { threshold: 0.3, rootMargin: '-80px 0px -50% 0px' }
    )
    sections.forEach(id => {
      const el = document.getElementById(id)
      if (el) observer.observe(el)
    })
    return () => observer.disconnect()
  }, [isLanding])

  const navItems = isDashboard ? DASHBOARD_ITEMS : NAV_ITEMS

  return (
    <>
      <nav className="fixed top-0 left-0 right-0 z-50 bg-ae-bg/80 backdrop-blur-lg border-b border-ae-border/40">
        <div className="ae-section flex items-center justify-between h-14">
          {/* Logo */}
          <a href="/" className="flex items-center gap-2">
            <img src="/images/logo.webp" alt="AE402" className="h-6 w-auto" />
            <span className="font-bold text-white text-sm hidden sm:inline">AgentEscrow402</span>
          </a>

          {/* Desktop nav — always visible */}
          <div className="hidden md:flex items-center gap-6 ml-8 flex-1">
            {navItems.map(item => {
              const sectionId = item.href.replace('/#', '')
              const isActive = isLanding && activeSection === sectionId
              const Icon = item.icon
              return (
                <a
                  key={item.label}
                  href={item.href}
                  className={`text-[11px] tracking-[0.15em] font-semibold transition-all py-1 border-b-2 flex items-center gap-1.5 ${
                    isActive
                      ? 'text-ae-accent border-ae-accent'
                      : 'text-gray-500 border-transparent hover:text-gray-300 hover:border-gray-600'
                  }`}
                >
                  <Icon size={12} />
                  {item.label}
                </a>
              )
            })}
          </div>

          {/* Desktop external links (on dashboard page) */}
          {isDashboard && (
            <div className="hidden lg:flex items-center gap-3 mr-4">
              {EXTERNAL_LINKS.slice(0, 2).map(link => (
                <a
                  key={link.label}
                  href={link.href}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 text-[10px] text-gray-600 hover:text-ae-accent transition-colors"
                >
                  <link.icon size={10} />
                  {link.label}
                  <ExternalLink size={8} />
                </a>
              ))}
            </div>
          )}

          <div className="flex items-center gap-3">
            {!isDashboard && (
              <a href="/dashboard" className="px-4 py-1.5 rounded-lg bg-ae-accent text-white text-xs font-semibold hover:bg-ae-accent-bright transition-colors">
                Dashboard
              </a>
            )}
            <button
              onClick={() => setMobileOpen(!mobileOpen)}
              className="md:hidden text-gray-400 hover:text-white"
              aria-label="Menu"
            >
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
          </div>
        </div>
      </nav>

      {/* Fullscreen mobile menu */}
      {mobileOpen && (
        <div className="fixed inset-0 z-[60] bg-ae-bg flex flex-col animate-fade-in-up">
          <div className="flex justify-end p-5">
            <button onClick={() => setMobileOpen(false)} className="text-gray-400 hover:text-white">
              <X size={28} />
            </button>
          </div>
          <div className="flex-1 flex flex-col items-center justify-center gap-6">
            {NAV_ITEMS.map(item => (
              <a
                key={item.label}
                href={item.href}
                onClick={() => setMobileOpen(false)}
                className="text-2xl font-bold text-white tracking-wider hover:text-ae-accent transition-colors"
              >
                {item.label}
              </a>
            ))}
            <div className="w-16 h-px bg-ae-border my-4" />
            <a
              href="/dashboard"
              onClick={() => setMobileOpen(false)}
              className="px-8 py-3 rounded-xl bg-ae-accent text-white font-semibold text-lg"
            >
              Launch Dashboard
            </a>
          </div>
          <div className="flex flex-wrap justify-center gap-4 pb-10 px-6">
            {EXTERNAL_LINKS.map(link => (
              <a
                key={link.label}
                href={link.href}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300"
              >
                {link.label} <ExternalLink size={10} />
              </a>
            ))}
          </div>
        </div>
      )}
    </>
  )
}
