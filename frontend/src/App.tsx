import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { useState, useEffect, useCallback } from 'react'
import Navbar from './components/Navbar'
import Hero from './components/Hero'
import WhyAE402 from './components/WhyAE402'
import TrustSignals from './components/TrustSignals'
import PaymentFlow from './components/PaymentFlow'
import X402Protocol from './components/X402Protocol'
import ReputationSystem from './components/ReputationSystem'
import Capabilities from './components/Capabilities'
import Scenarios from './components/Scenarios'
import GrowthPotential from './components/GrowthPotential'
import SDKSection from './components/SDKSection'
import FAQ from './components/FAQ'
import Footer from './components/Footer'
import ScrollToTop from './components/ScrollToTop'
import NotFound from './components/NotFound'
import ConsoleLayout from './components/console/ConsoleLayout'
import Overview from './components/console/Overview'
import Escrows from './components/console/Escrows'
import Agents from './components/console/Agents'
import Insurance from './components/console/Insurance'
import Risk from './components/console/Risk'
import Contracts from './components/console/Contracts'
import AgentDemo from './components/console/AgentDemo'
import Sandbox from './components/console/Sandbox'
import Docs from './components/console/Docs'
import AdvancedEscrow from './components/console/AdvancedEscrow'
import Arbitration from './components/console/Arbitration'
import IdentityRegistry from './components/console/IdentityRegistry'
import UseCases from './components/console/UseCases'
import Evidence from './components/console/Evidence'
import FeatureMap from './components/console/FeatureMap'

function Landing() {
  useEffect(() => {
    const hash = window.location.hash.slice(1)
    if (hash) {
      const raf = requestAnimationFrame(() => {
        const el = document.getElementById(hash)
        if (el) el.scrollIntoView({ behavior: 'smooth' })
      })
      return () => cancelAnimationFrame(raf)
    }
  }, [])

  return (
    <>
      <Hero />
      <WhyAE402 />
      <TrustSignals />
      <PaymentFlow />
      <X402Protocol />
      <ReputationSystem />
      <Capabilities />
      <Scenarios />
      <GrowthPotential />
      <SDKSection />
      <FAQ />
    </>
  )
}

export default function App() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const closeMobile = useCallback(() => setMobileOpen(false), [])
  const location = useLocation()
  // Console pages own their entire layout (fixed full-height sidebar + its
  // own sticky top bar) — the marketing Navbar/Footer would double up with
  // that and break the fixed-offset math, so they only render on the
  // marketing site.
  const isConsole = location.pathname.startsWith('/console')

  useEffect(() => {
    document.body.style.overflow = mobileOpen ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [mobileOpen])

  return (
    <div className="min-h-screen flex flex-col">
      <ScrollToTop />
      {!isConsole && <Navbar mobileOpen={mobileOpen} setMobileOpen={setMobileOpen} />}
      <main className={isConsole ? 'flex-1' : 'flex-1'} onClick={!isConsole && mobileOpen ? closeMobile : undefined}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/console" element={<ConsoleLayout />}>
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<Overview />} />
            <Route path="use-cases" element={<UseCases />} />
            <Route path="escrows" element={<Escrows />} />
            <Route path="agents" element={<Agents />} />
            <Route path="insurance" element={<Insurance />} />
            <Route path="risk" element={<Risk />} />
            <Route path="contracts" element={<Contracts />} />
            <Route path="agent-demo" element={<AgentDemo />} />
            <Route path="sandbox" element={<Sandbox />} />
            <Route path="docs" element={<Docs />} />
            <Route path="advanced" element={<AdvancedEscrow />} />
            <Route path="arbitration" element={<Arbitration />} />
            <Route path="identity-registry" element={<IdentityRegistry />} />
            <Route path="evidence" element={<Evidence />} />
            <Route path="feature-map" element={<FeatureMap />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      {!isConsole && <Footer />}
    </div>
  )
}
