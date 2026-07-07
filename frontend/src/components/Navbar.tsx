import { useState, useEffect } from 'react'
import { X, ExternalLink, Home, Repeat, Shield, Code, HelpCircle, LayoutDashboard, Bot, Grid3x3, CheckCircle, TrendingUp } from 'lucide-react'

// This Navbar only renders on the marketing site (App.tsx skips it on
// /console/* routes — the console owns its own fixed sidebar + top bar).
// Order matches the actual section order on the page.
const NAV_ITEMS = [
  { label: 'HOME', href: '/#home', icon: Home },
  { label: 'WHY', href: '/#why', icon: Shield },
  { label: 'EVIDENCE', href: '/#evidence', icon: CheckCircle },
  { label: 'FLOW', href: '/#flow', icon: Repeat },
  { label: 'FEATURES', href: '/#capabilities', icon: Grid3x3 },
  { label: 'USE CASES', href: '/#scenarios', icon: Bot },
  { label: 'GROWTH', href: '/#growth', icon: TrendingUp },
  { label: 'SDK', href: '/#developers', icon: Code },
  { label: 'FAQ', href: '/#faq', icon: HelpCircle },
]

const EXTERNAL_LINKS = [
  { label: 'GitHub', href: 'https://github.com/alexbelij/AgentEscrow402' },
  { label: 'SDK Docs', href: 'https://github.com/alexbelij/AgentEscrow402/blob/main/docs/SDK.md' },
]

export default function Navbar({ mobileOpen, setMobileOpen }: { mobileOpen: boolean; setMobileOpen: (v: boolean) => void }) {
  const [activeSection, setActiveSection] = useState('home')

  useEffect(() => {
    const sectionIds = NAV_ITEMS.map(n => n.href.replace('/#', '')).filter(Boolean)

    // Scroll-spy: pick the section whose top is closest to (but above) the
    // viewport top + a small offset.  For the very bottom of the page we
    // force the last visible section so FAQ/SDK always highlight.
    const onScroll = () => {
      const offset = 120 // navbar height + margin
      let current = sectionIds[0]
      for (const id of sectionIds) {
        const el = document.getElementById(id)
        if (el && el.getBoundingClientRect().top <= offset) current = id
      }
      // If scrolled to page bottom, pick the last section
      if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 40) {
        current = sectionIds[sectionIds.length - 1]
      }
      setActiveSection(current)
    }

    window.addEventListener('scroll', onScroll, { passive: true })
    onScroll() // initial
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

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
            {NAV_ITEMS.map(item => {
              const sectionId = item.href.replace('/#', '')
              const isActive = activeSection === sectionId
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

          <div className="flex items-center gap-3">
            <a
              href="/console/overview"
              className="hidden sm:inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-ae-accent text-white text-xs font-semibold hover:bg-ae-accent-bright transition-colors"
            >
              <LayoutDashboard size={13} />
              Console
            </a>
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
            <a
              href="/console/overview"
              onClick={() => setMobileOpen(false)}
              className="inline-flex items-center gap-2 px-6 py-2.5 rounded-lg bg-ae-accent text-white text-sm font-semibold hover:bg-ae-accent-bright transition-colors"
            >
              <LayoutDashboard size={14} />
              Console
            </a>
            <div className="w-16 h-px bg-ae-border my-4" />
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
