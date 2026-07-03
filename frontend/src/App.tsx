import { Routes, Route, Navigate } from 'react-router-dom'
import { useState, useEffect, useCallback } from 'react'
import Navbar from './components/Navbar'
import Hero from './components/Hero'
import PaymentFlow from './components/PaymentFlow'
import X402Protocol from './components/X402Protocol'
import ReputationSystem from './components/ReputationSystem'
import SDKSection from './components/SDKSection'
import Scenarios from './components/Scenarios'
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
      <PaymentFlow />
      <X402Protocol />
      <ReputationSystem />
      <Scenarios />
      <SDKSection />
      <FAQ />
    </>
  )
}

export default function App() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const closeMobile = useCallback(() => setMobileOpen(false), [])

  useEffect(() => {
    document.body.style.overflow = mobileOpen ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [mobileOpen])

  return (
    <div className="min-h-screen flex flex-col">
      <ScrollToTop />
      <Navbar mobileOpen={mobileOpen} setMobileOpen={setMobileOpen} />
      <main className="flex-1" onClick={mobileOpen ? closeMobile : undefined}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/console" element={<ConsoleLayout />}>
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<Overview />} />
            <Route path="escrows" element={<Escrows />} />
            <Route path="agents" element={<Agents />} />
            <Route path="insurance" element={<Insurance />} />
            <Route path="risk" element={<Risk />} />
            <Route path="contracts" element={<Contracts />} />
            <Route path="agent-demo" element={<AgentDemo />} />
            <Route path="sandbox" element={<Sandbox />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <Footer />
    </div>
  )
}
