import { Routes, Route } from 'react-router-dom'
import { useState, useEffect, useCallback } from 'react'
import Navbar from './components/Navbar'
import Hero from './components/Hero'
import PaymentFlow from './components/PaymentFlow'
import X402Protocol from './components/X402Protocol'
import ReputationSystem from './components/ReputationSystem'
import SDKSection from './components/SDKSection'
import FAQ from './components/FAQ'
import CtaFooter from './components/CtaFooter'
import Footer from './components/Footer'
import ScrollProgress from './components/ScrollProgress'
import NotFound from './components/NotFound'
import Dashboard from './components/Dashboard'

function Landing() {
  return (
    <>
      <Hero />
      <PaymentFlow />
      <X402Protocol />
      <ReputationSystem />
      <SDKSection />
      <FAQ />
      <CtaFooter />
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
      <ScrollProgress />
      <Navbar mobileOpen={mobileOpen} setMobileOpen={setMobileOpen} />
      <main className="flex-1" onClick={mobileOpen ? closeMobile : undefined}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/app" element={<Dashboard />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <Footer />
    </div>
  )
}
