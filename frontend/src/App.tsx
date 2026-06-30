import { Routes, Route, useLocation } from 'react-router-dom'
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
import Dashboard from './components/Dashboard'

function Landing() {
  return (
    <>
      <Hero />
      <PaymentFlow />
      <X402Protocol />
      <Scenarios />
      <ReputationSystem />
      <SDKSection />
      <FAQ />
    </>
  )
}

export default function App() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const closeMobile = useCallback(() => setMobileOpen(false), [])
  const location = useLocation()
  const isDashboard = location.pathname === '/app'

  useEffect(() => {
    document.body.style.overflow = mobileOpen ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [mobileOpen])

  return (
    <div className="min-h-screen flex flex-col">
      <ScrollToTop />
      {!isDashboard && <Navbar mobileOpen={mobileOpen} setMobileOpen={setMobileOpen} />}
      <main className="flex-1" onClick={mobileOpen ? closeMobile : undefined}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/app" element={<Dashboard />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      {!isDashboard && <Footer />}
    </div>
  )
}
