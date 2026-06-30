import { useState, useEffect } from 'react'
import { ChevronUp } from 'lucide-react'

export default function ScrollToTop() {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const onScroll = () => setVisible(window.scrollY > 400)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  if (!visible) return null

  return (
    <button
      onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
      className="fixed bottom-6 right-6 z-50 w-11 h-11 rounded-full bg-ae-accent/90 text-white flex items-center justify-center shadow-lg shadow-purple-600/30 hover:bg-ae-accent-bright transition-all hover:scale-110"
      aria-label="Scroll to top"
    >
      <ChevronUp size={20} />
    </button>
  )
}
